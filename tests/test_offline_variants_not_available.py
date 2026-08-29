"""A source you turned off is not somewhere you can watch.

Owner, from a screenshot of the details pane: "Also Available: 3 versions · 2
regions" with three chips, one of which was on TREX — a source they had
disabled. Its tooltip said, in as many words, "(source is inactive)".

Two rules were broken at once:

* ``docs/CRITICAL_RULES.md:188`` — content from inactive or expired sources
  "must never appear in a forward-looking view". The documented exception is
  the record/engaged views (History, Favorites, Queue). "Also Available" is
  the opposite of those: it is a statement about what you can watch NOW.
* the accessibility rule against encoding state by appearance alone — the only
  signal was a slightly dimmer chip plus hover text.

It was also COUNTED, so the headline read three versions when two were
available.

The fix does not delete the variant. The chip already offers "right-click to
reactivate & play", and that recovery path is worth keeping — it moves to its
own OFFLINE SOURCES section, a sibling of FILTERED VARIANTS and deliberately
not a child of it: filtered is the user's own soft exclusion and is revealable,
while an inactive source is an absolute gate (``CRITICAL_RULES.md:219``).
"""

import pytest

from metatv.gui.details_versions import ChannelVersion


def _v(cid: str, *, inactive: bool = False, filtered: bool = False,
       prefix: str = "US") -> ChannelVersion:
    return ChannelVersion(
        channel_id=cid, name=f"Movie ({cid})", in_queue=False,
        detected_prefix=prefix, provider_id=f"p-{cid}",
        is_inactive=inactive, is_filtered=filtered,
    )


def _chips(layout):
    return [layout.itemAt(i).widget() for i in range(layout.count())
            if layout.itemAt(i).widget()]


@pytest.fixture
def section(qapp):
    from tests.test_cross_source_playback import _make_version_section
    return _make_version_section(qapp)


def test_an_offline_variant_is_not_listed_as_available(section) -> None:
    """The reported bug. Pre-fix the inactive chip rendered here."""
    section.load([_v("live"), _v("dead", inactive=True)], provider_map={})

    available = [c.text() for c in _chips(section._chips_layout)]
    assert len(available) == 1, (
        f"a disabled source's variant is being offered as available: {available!r}"
    )


def test_an_offline_variant_is_not_counted_as_available(section) -> None:
    """The header said "3 versions" when only 2 could be played."""
    from metatv.gui.details_version_groups import group_by_region, summarise

    section.load([_v("a"), _v("b", prefix="GB"), _v("dead", inactive=True)],
                 provider_map={})
    summary = summarise(group_by_region(section._active_versions))

    assert "2 version" in summary, f"offline variant counted in the header: {summary!r}"


def test_an_offline_variant_is_still_reachable(section) -> None:
    """It is hidden from "available", not deleted — recovery is the point."""
    section.load([_v("live"), _v("dead", inactive=True)], provider_map={})

    offline = _chips(section._offline_chips_layout)
    assert len(offline) == 1, "the offline variant vanished entirely"
    assert section._offline_section.isVisibleTo(section), "OFFLINE SOURCES not shown"


def test_the_offline_section_stays_out_of_filtered_variants(section) -> None:
    """A hard gate must not be reachable by revealing the soft one.

    If offline variants were folded into FILTERED VARIANTS, expanding that
    disclosure would surface disabled-source content — which is exactly what
    "never a soft filter" forbids.
    """
    # Distinct prefixes so the two chips carry different labels — same-label
    # chips would make the disjointness assertion below pass for the wrong
    # reason (or fail for one, as the first draft of this test did).
    section.load([_v("f", filtered=True, prefix="GB"),
                  _v("dead", inactive=True, prefix="DE")], provider_map={})

    filtered_labels = {c.text() for c in _chips(section._filtered_chips_layout)}
    offline_labels = {c.text() for c in _chips(section._offline_chips_layout)}

    assert len(filtered_labels) == 1, f"filtered bucket: {filtered_labels!r}"
    assert len(offline_labels) == 1, f"offline bucket: {offline_labels!r}"
    assert not (filtered_labels & offline_labels), (
        f"a chip is in both buckets: filtered={filtered_labels!r} offline={offline_labels!r}"
    )


def test_both_sections_are_absent_when_nothing_qualifies(section) -> None:
    """Neither disclosure should be furniture on an ordinary title."""
    section.load([_v("a"), _v("b", prefix="GB")], provider_map={})

    assert section._offline_section.isHidden()
    assert section._filtered_section.isHidden()


def test_a_reload_does_not_leave_the_previous_titles_offline_chips(section) -> None:
    """The clear path has to cover BOTH sub-sections, not just the first one."""
    section.load([_v("dead", inactive=True)], provider_map={})
    assert len(_chips(section._offline_chips_layout)) == 1

    section.load([_v("live")], provider_map={})
    assert _chips(section._offline_chips_layout) == [], "stale offline chips survived a reload"
    assert section._offline_section.isHidden()
