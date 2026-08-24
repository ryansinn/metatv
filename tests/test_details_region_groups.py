"""Also-available, grouped by region — 65 chips become 12 and a tail.

Kraven The Hunter carries 65 versions across 19 regions in the real library;
Nickelodeon 94 across 32. One chip per version is a wall you cannot read, and
for anything popular it is the common case rather than the edge.

The grouping rules are tested as plain functions. The GRID is tested by its
rendered geometry, because "twelve chips exist" is satisfied by twelve chips
drawn on top of each other.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from metatv.gui.details_version_groups import (
    DEFAULT_VISIBLE_REGIONS, UNKNOWN_REGION,
    group_by_region, region_key, summarise,
)


def _v(region=None, prefix=None, quality=None, cid="x"):
    return SimpleNamespace(
        channel_id=cid, detected_region=region,
        detected_prefix=prefix, detected_quality=quality,
    )


# ── The rules ────────────────────────────────────────────────────────────────

def test_region_wins_over_prefix():
    """Prefix-first over-splits: it is often a language where a region exists."""
    assert region_key(_v(region="DE", prefix="EN")) == "DE"


def test_prefix_is_the_fallback_not_the_key():
    """Region alone strands 8 of Kraven's 65; the fallback places all of them."""
    assert region_key(_v(region=None, prefix="NL")) == "NL"


def test_a_version_with_neither_is_still_counted():
    """Never dropped.

    A header reading "65 versions" over a grid accounting for 57 is worse than
    no grouping at all, so the unidentifiable get a named bucket.
    """
    assert region_key(_v()) == UNKNOWN_REGION
    groups = group_by_region([_v(region="DE"), _v(), _v()])
    assert sum(g.count for g in groups) == 3


def test_groups_are_biggest_first_then_alphabetical():
    """Stable between renders — a chip that moves cannot be learned."""
    versions = ([_v(region="FR")] * 2) + ([_v(region="DE")] * 5) + [_v(region="AT")]
    assert [g.code for g in group_by_region(versions)] == ["DE", "FR", "AT"]


def test_the_unknown_bucket_sorts_last_however_big_it_is():
    versions = ([_v()] * 40) + ([_v(region="DE")] * 2)
    assert [g.code for g in group_by_region(versions)] == ["DE", UNKNOWN_REGION]


def test_a_regions_qualities_are_collected_without_blanks():
    versions = [_v(region="DE", quality="4K"), _v(region="DE"),
                _v(region="DE", quality="4K"), _v(region="DE", quality="hd")]
    assert group_by_region(versions)[0].qualities == ("4K", "HD")


def test_the_summary_states_the_real_scale():
    versions = ([_v(region="DE")] * 9) + ([_v(region="NL")] * 6)
    assert summarise(group_by_region(versions)) == "15 versions · 2 regions"


def test_the_summary_is_singular_when_it_should_be():
    assert summarise(group_by_region([_v(region="DE")])) == "1 version · 1 region"


def test_every_version_survives_grouping():
    """The property that makes the collapse safe to do at all."""
    versions = [_v(region="DE", cid=f"a{i}") for i in range(9)] + \
               [_v(prefix="NL", cid=f"b{i}") for i in range(6)] + \
               [_v(cid=f"c{i}") for i in range(4)]
    groups = group_by_region(versions)
    seen = {v.channel_id for g in groups for v in g.versions}
    assert seen == {v.channel_id for v in versions}
    assert len(seen) == 19


# ── The grid ─────────────────────────────────────────────────────────────────

@pytest.fixture
def section(qapp, tmp_path):
    from metatv.core.config import Config
    from metatv.gui.details_versions import _VersionSection

    sec = _VersionSection(Config(config_dir=tmp_path))
    sec.resize(460, 240)
    sec.show()
    qapp.processEvents()
    return sec


def _kraven(n_regions=19):
    """A version list shaped like the real Kraven group."""
    from metatv.gui.details_versions import ChannelVersion

    counts = [9, 6, 6, 6, 5, 4, 4, 4, 4, 3, 2, 2, 2, 2, 2, 1, 1, 1, 1][:n_regions]
    codes = ["DE", "EN", "NL", "PL", "IN", "BG", "ES", "FR", "RU", "ALB",
             "AR", "EXYU", "GR", "IR", "IT", "AL", "SE", "TE", "TR"][:n_regions]
    out = []
    for code, count in zip(codes, counts):
        for i in range(count):
            out.append(ChannelVersion(
                channel_id=f"{code}{i}", name=f"{code} Kraven {i}",
                in_queue=False, detected_region=code,
            ))
    return out


def _chip_texts(section):
    lay = section._chips_layout
    return [lay.itemAt(i).widget().text() for i in range(lay.count())]


def test_sixty_five_versions_render_as_twelve_chips_and_a_tail(section, qapp):
    section.load(_kraven())
    qapp.processEvents()
    texts = _chip_texts(section)
    assert len(texts) == DEFAULT_VISIBLE_REGIONS + 1
    assert texts[0].startswith("DE")
    assert texts[-1] == "+ 7 more"
    assert section._header.summary() == "65 versions · 19 regions"


def test_the_chips_are_actually_laid_out_side_by_side(section, qapp):
    """Rendered geometry. Twelve chips that exist can still all be at (0, 0).

    Asserts they occupy distinct rectangles, wrap onto more than one row at the
    pane's real width, and none is drawn past the right edge.
    """
    section.load(_kraven())
    qapp.processEvents()
    lay = section._chips_layout
    rects = [lay.itemAt(i).widget().geometry() for i in range(lay.count())]

    assert len({(r.x(), r.y()) for r in rects}) == len(rects), "chips overlap"
    assert len({r.y() for r in rects}) > 1, "the grid did not wrap onto a second row"
    for rect in rects:
        assert rect.right() <= section._chips_row.width() + 1, (
            f"a chip is drawn past the grid's right edge "
            f"({rect.right()} > {section._chips_row.width()})"
        )
    rows = {}
    for rect in rects:
        rows.setdefault(rect.y(), []).append(rect)
    for row in rows.values():
        row.sort(key=lambda r: r.x())
        for a, b in zip(row, row[1:]):
            assert b.x() >= a.right(), "two chips in the same row overlap"


def test_re_rendering_the_grid_leaves_nothing_behind(section, qapp):
    """The old chips must leave the SCREEN, not just the layout.

    ``deleteLater()`` schedules destruction for the next event-loop pass; until
    then the widget is still a visible child painting where it was. Removing it
    from the layout only stops it being positioned. Drilling into a region
    therefore drew the version chips straight on top of the region chips — and
    a test that reads layout items cannot see it, because the stale widgets are
    exactly the ones no longer IN the layout.
    """
    from PyQt6.QtWidgets import QPushButton

    section.load(_kraven())
    qapp.processEvents()
    section._expand_region("DE")
    qapp.processEvents()

    live = [c for c in section._chips_row.findChildren(QPushButton)
            if c.isVisible()]
    in_layout = {section._chips_layout.itemAt(i).widget()
                 for i in range(section._chips_layout.count())}
    orphans = [c.text() for c in live if c not in in_layout]
    assert not orphans, (
        f"chips left visible after a re-render: {orphans} — they are drawn "
        f"over the new grid"
    )


def test_more_reveals_every_region_and_the_tail_goes(section, qapp):
    section.load(_kraven())
    qapp.processEvents()
    section._show_every_region()
    qapp.processEvents()
    texts = _chip_texts(section)
    assert len(texts) == 19
    assert not any(t.startswith("+") for t in texts)


def test_clicking_a_region_shows_that_regions_versions(section, qapp):
    """Drill-down, not a lucky pick.

    A region chip stands for nine things; making it select one of them would be
    choosing on the user's behalf. It opens them instead, and every per-version
    interaction (right-click menu, play, favourite) is still there one click in.
    """
    section.load(_kraven())
    qapp.processEvents()
    section._expand_region("DE")
    qapp.processEvents()

    texts = _chip_texts(section)
    assert texts[0].endswith("All regions"), "no way back out of the region"
    assert len(texts) == 1 + 9, "expanded region did not show its nine versions"


def test_going_back_restores_the_capped_grid(section, qapp):
    section.load(_kraven())
    qapp.processEvents()
    section._expand_region("DE")
    section._collapse_region()
    qapp.processEvents()
    assert len(_chip_texts(section)) == DEFAULT_VISIBLE_REGIONS + 1


def test_a_reload_that_drops_the_open_region_does_not_strand_the_pane(section, qapp):
    """Navigating to another title while drilled in must not show an empty grid."""
    section.load(_kraven())
    section._expand_region("DE")
    qapp.processEvents()

    section.load(_kraven(n_regions=13))
    qapp.processEvents()

    assert section._region_expanded is None, "still drilled into the old title"
    assert _chip_texts(section)[0].startswith("DE")


# ── When NOT to group ────────────────────────────────────────────────────────

def test_a_handful_of_versions_are_not_grouped_at_all(section, qapp):
    """Grouping trades detail for scale, and is only worth it at scale.

    Three versions rendered as three region chips costs a click to reach any of
    them and drops the source icon and quality tier from the face — strictly
    worse than the flat list it replaced. So below the threshold nothing
    changes: the chips are the versions, exactly as before.
    """
    from metatv.gui.details_versions import ChannelVersion

    versions = [
        ChannelVersion(channel_id=f"v{i}", name=f"V{i}", in_queue=False,
                       detected_prefix="US", detected_quality="HD")
        for i in range(3)
    ]
    section.load(versions)
    qapp.processEvents()

    texts = _chip_texts(section)
    assert len(texts) == 3, "three versions should render as three chips"
    assert not any(t.startswith("+") for t in texts), "no tail for three chips"
    assert all("HD" in t for t in texts), (
        "the flat chip still carries its quality tier — that detail is what "
        "grouping gives up, and there is no reason to give it up here"
    )


def test_the_grid_groups_the_moment_the_flat_list_would_be_a_wall(section, qapp):
    """One past the threshold is where the trade starts paying."""
    from metatv.gui.details_version_groups import GROUPING_THRESHOLD
    from metatv.gui.details_versions import ChannelVersion

    def _n(count):
        return [ChannelVersion(channel_id=f"v{i}", name=f"V{i}", in_queue=False,
                               detected_region=f"R{i % 4}")
                for i in range(count)]

    section.load(_n(GROUPING_THRESHOLD))
    qapp.processEvents()
    assert len(_chip_texts(section)) == GROUPING_THRESHOLD, "grouped too early"

    section.load(_n(GROUPING_THRESHOLD + 1))
    qapp.processEvents()
    assert len(_chip_texts(section)) == 4, "did not group once the list got long"
