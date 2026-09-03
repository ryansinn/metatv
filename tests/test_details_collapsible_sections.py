"""Six details sections, one header, and every one of them remembers.

Before this there were four hand-rolled collapsible sections and two that could
not collapse at all — not by decision, but because collapsing Overview would
have meant a fifth copy of the same forty lines. The four had already drifted:
two read their glyphs from ``config``, one from ``icons``, and none could show
a count beside the title, which the V3 render asks for on Cast, Also-available
and Similar Titles.

These test the consequences: every section collapses, every section persists
under its own key, and the pane restores and saves all six through one list
rather than a hand-written block per section.
"""

from __future__ import annotations

import pytest

from metatv.gui.details_section_header import CollapsibleHeader


@pytest.fixture
def pane(qapp, tmp_path):
    from unittest.mock import MagicMock

    from metatv.core.config import Config
    from metatv.gui.details_pane import DetailsPaneWidget

    cfg = Config(config_dir=tmp_path)
    # MagicMock cache, matching the other details-pane tests: the pane connects
    # to image_loaded/image_failed at construction, and this file is about
    # collapse state, not image loading.
    widget = DetailsPaneWidget(cfg, image_cache=MagicMock(), db=None)
    widget.resize(460, 900)
    widget.show()
    qapp.processEvents()
    return widget


def test_all_six_sections_are_collapsible(pane):
    assert len(pane._collapsible_sections) == 6
    for section in pane._collapsible_sections:
        assert isinstance(section._header, CollapsibleHeader)


def test_overview_and_also_available_gained_the_ability(pane):
    """The two that previously had no way to fold away."""
    keys = {s.COLLAPSE_KEY for s in pane._collapsible_sections}
    assert "overview" in keys, "Overview still cannot collapse"
    assert "versions" in keys, "Also available still cannot collapse"


def test_collapsing_a_section_hides_its_body_and_nothing_else(pane, qapp):
    overview = pane._plot
    other_visible = [s for s in pane._collapsible_sections if s is not overview]
    before = [s._content.isVisibleTo(pane) for s in other_visible]

    overview._header.toggle()
    qapp.processEvents()

    assert not overview._content.isVisibleTo(pane), "collapsing did not hide the body"
    assert [s._content.isVisibleTo(pane) for s in other_visible] == before, (
        "collapsing one section changed another"
    )


@pytest.mark.parametrize("index", range(6))
def test_every_section_actually_hides_its_body(pane, qapp, index):
    """Each section, individually. Not one of them, six times.

    This is the test that was missing, and the bug it now catches shipped
    because of the gap: three of the six sections never connected their
    header's ``toggled`` signal to the code that hides the body, so they
    flipped their chevron and saved their state while staying open. The
    original test drove ``pane._plot`` — which happened to be one of the three
    that WAS wired — and passed.

    The body is shown first because two sections (Also available, Tags) hide
    themselves entirely until they have content, and a section that is hidden
    for that reason would report "not visible" and pass without collapsing
    anything.
    """
    section = pane._collapsible_sections[index]
    section._header.set_collapsed(False)
    section._content.show()
    qapp.processEvents()
    assert not section._content.isHidden()

    section._header.toggle()
    qapp.processEvents()

    assert section._content.isHidden(), (
        f"{section.COLLAPSE_KEY!r} flips its chevron but never hides its body "
        f"— its header is not connected to _apply_collapsed"
    )

    section._header.toggle()
    qapp.processEvents()
    assert not section._content.isHidden(), (
        f"{section.COLLAPSE_KEY!r} does not come back when expanded"
    )


def test_every_section_persists_its_own_state(pane):
    """Six keys, six independent memories."""
    for section in pane._collapsible_sections:
        section._header.set_collapsed(True)
        section.save_state(pane)

    stored = set(pane.config.details_pane_collapsed_sections)
    assert stored == {s.COLLAPSE_KEY for s in pane._collapsible_sections}

    for section in pane._collapsible_sections:
        section._header.set_collapsed(False)
        section.save_state(pane)
    assert not pane.config.details_pane_collapsed_sections


def test_a_toggle_saves_without_anyone_wiring_it_per_section(pane, qapp):
    """The pane connects from the same tuple it restores from.

    A hand-listed block per section is how a seventh section ends up restored
    but never saved — the shape this replaced.
    """
    similar = pane._similar
    similar._header.toggle()
    qapp.processEvents()

    assert similar.COLLAPSE_KEY in pane.config.details_pane_collapsed_sections, (
        "toggling a section did not persist it"
    )


def test_restore_puts_each_section_back(pane, qapp):
    pane.config.details_pane_collapsed_sections = ["overview", "cast"]
    for section in pane._collapsible_sections:
        section.restore_collapse_state(pane.config.details_pane_collapsed_sections)
    qapp.processEvents()

    collapsed = {s.COLLAPSE_KEY for s in pane._collapsible_sections
                 if s._header.is_collapsed()}
    assert collapsed == {"overview", "cast"}


def test_an_unknown_key_in_config_does_not_collapse_anything(pane, qapp):
    """A key from a removed section must not be mistaken for a live one."""
    pane.config.details_pane_collapsed_sections = ["a_section_that_left"]
    for section in pane._collapsible_sections:
        section.restore_collapse_state(pane.config.details_pane_collapsed_sections)
    assert not any(s._header.is_collapsed() for s in pane._collapsible_sections)


# ── The header's own behaviour ───────────────────────────────────────────────

def test_the_summary_hides_when_empty(qapp):
    """An empty slot on some headers and not others reads as a missing value."""
    header = CollapsibleHeader("Cast")
    assert header._summary.isHidden()
    header.set_summary("18")
    assert not header._summary.isHidden()
    header.set_summary("")
    assert header._summary.isHidden()


def test_set_collapsed_does_not_emit(qapp):
    """Restoring from config must not look like a user toggle, or the pane
    would write the state back on every load."""
    header = CollapsibleHeader("Cast")
    seen = []
    header.toggled.connect(seen.append)
    header.set_collapsed(True)
    assert seen == []
    header.toggle()
    assert seen == [False]


def test_the_header_lays_title_left_and_summary_right(qapp):
    """Rendered geometry — "there is a summary widget" is not the same as
    "the count reads at the right-hand end of the row"."""
    header = CollapsibleHeader("Also available")
    header.set_summary("65 versions · 19 regions")
    header.resize(420, 28)
    header.show()
    qapp.processEvents()

    chevron = header._chevron.geometry()
    title = header._title.geometry()
    summary = header._summary.geometry()

    assert chevron.right() <= title.x(), "the chevron overlaps the title"
    assert title.right() <= summary.x(), "the title overlaps the summary"
    assert summary.right() <= header.width(), "the summary is drawn off the end"
    assert summary.x() > header.width() // 2, (
        f"the summary sits at x={summary.x()} in a {header.width()}px header — "
        f"it is not right-aligned"
    )


def test_section_headings_are_title_case(pane):
    """One capitalisation rule across all six, so the column reads as a set.

    The V3 render used sentence case throughout ("Also available", "Technical
    details", "Similar titles"). The owner asked for Title Case on review, so
    that is what ships — and it ships for ALL of them, because a column where
    two headings are capitalised differently from the rest looks like an
    oversight whichever convention is right.
    """
    for section in pane._collapsible_sections:
        title = section._header.title()
        words = [w for w in title.split() if w.isalpha()]
        assert words, f"{title!r} has no words to check"
        assert all(w[0].isupper() for w in words), (
            f"{title!r} is not Title Case — every word should start capitalised"
        )
