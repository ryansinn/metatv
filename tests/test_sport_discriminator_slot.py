"""The leading slot shows whatever still discriminates (SPORT-3).

The settled rule, from *Sport Rundown*: unfiltered the sport glyph carries the
row; once one sport is selected that glyph is constant on every visible row and
the slot becomes the region CODE; once nothing varies the slot **collapses**
rather than blanking, because the audit found these rows clip long fixture names
and ~28px is better spent on the title than on a reserved empty column.

Three filter states, three geometries — which is what makes this testable the
way CLAUDE.md demands: assertions on painted rects, not on token existence or
cell order. ``test_the_collapsed_slot_gives_its_width_back_to_the_title`` is the
one that would have caught a "paint nothing but keep the column" implementation,
which passes every order-based check and is precisely the wrong answer.

Measured alternatives, recorded so they are not re-proposed: **team badges are
out** — only 12.8% of sports rows carry a ``team_name`` — and **league is out**,
because within a single sport it is one value or absent.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QRect

from metatv.gui import channel_row_layout as layout
from metatv.gui.channel_list_delegate import ChannelRowDelegate
from metatv.gui.channel_row_lead import (DISCRIMINATOR_REGION,
                                         DISCRIMINATOR_SPORT,
                                         discriminator_for)
from tests.conftest import paint_channel_row, row_model

ROW = QRect(0, 0, 620, 68)


@pytest.fixture
def delegate(qapp):
    deleg = ChannelRowDelegate()
    deleg.set_density("comfy")
    deleg.set_thumbnails_enabled(True)
    return deleg


def _index(**overrides):
    model = row_model(**overrides)
    index = model.index(0)
    index._model_keepalive = model  # noqa: SLF001
    return index


# ── the rule ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rows,expected", [
    ([("soccer", "US"), ("tennis", "GB")], DISCRIMINATOR_SPORT),
    ([("soccer", "US"), ("soccer", "GB")], DISCRIMINATOR_REGION),
    ([("soccer", "US"), ("soccer", "US")], ""),
    ([], ""),
    ([("soccer", ""), ("soccer", "")], ""),
])
def test_the_rule_is_whatever_still_discriminates(rows, expected):
    """The design's three filter states, plus the two it did not enumerate.

    An empty result set and a set where no row carries a region both collapse:
    a facet nothing carries cannot tell anything apart. The second case is the
    reason this is written as a criterion rather than as a case analysis of the
    filter — a library holding one sport shows a constant glyph on every row
    with no filter active at all, and a filter-shaped implementation would
    happily paint it.
    """
    assert discriminator_for(rows) == expected


def test_a_row_missing_its_value_does_not_veto_the_facet():
    """An absent region among varied ones must not collapse the slot."""
    assert discriminator_for(
        [("soccer", "US"), ("soccer", ""), ("soccer", "GB")]
    ) == DISCRIMINATOR_REGION


# ── geometry: three states, three shapes ────────────────────────────────────

def test_the_collapsed_slot_gives_its_width_back_to_the_title():
    """Collapse means reclaim, not blank.

    This is the assertion that separates the design from the implementation
    that looks identical in every other test: reserving the column and painting
    nothing in it satisfies "the glyph is absent" while stealing 28px from every
    fixture name on screen — the exact complaint the slot came from.
    """
    with_slot = layout.row_layout(ROW, has_art=True, art_square=False,
                                  rail_w=0, lead_w=layout.LEAD_W)
    collapsed = layout.row_layout(ROW, has_art=True, art_square=False,
                                  rail_w=0, lead_w=0)

    assert collapsed.lead.isEmpty(), "a collapsed slot has no rect at all"
    assert not with_slot.lead.isEmpty()
    reclaimed = collapsed.text.width() - with_slot.text.width()
    assert reclaimed == layout.LEAD_W + layout.LEAD_GAP, (
        f"collapsing returned {reclaimed}px to the title, expected "
        f"{layout.LEAD_W + layout.LEAD_GAP}"
    )
    assert collapsed.art.left() < with_slot.art.left(), \
        "the artwork well must move left too, not just the text"


def test_the_slot_sits_after_the_kind_mark_and_before_the_artwork():
    """Leading, but inside the content — the kind gutter stays structural."""
    box = layout.row_layout(ROW, has_art=True, art_square=False,
                            rail_w=0, lead_w=layout.LEAD_W)

    assert box.kind.right() <= box.lead.left(), "the slot overlaps the kind mark"
    assert box.lead.right() < box.art.left(), "the slot overlaps the artwork"
    assert box.lead.width() == layout.LEAD_W
    assert box.fill.top() <= box.lead.top() and box.lead.bottom() <= box.fill.bottom(), \
        "the slot paints outside the row fill"


def test_the_slot_is_vertically_centred_in_the_row():
    box = layout.row_layout(ROW, has_art=True, art_square=False,
                            rail_w=0, lead_w=layout.LEAD_W)
    above = box.lead.top() - box.fill.top()
    below = box.fill.bottom() - box.lead.bottom()
    assert abs(above - below) <= 1, f"off-centre: {above}px above, {below}px below"
    assert above > 0 and below > 0, "non-degenerate: the slot is not the whole row"


def test_geometry_takes_no_state_argument_still():
    """The slot arrives as a WIDTH, never as a mode flag.

    ``row_layout``'s contract is geometry from geometry alone — that is what
    makes "nothing moves when a row is selected" unrepresentable rather than
    remembered. A ``discriminator=`` parameter here would have re-opened it.
    """
    import inspect

    params = set(inspect.signature(layout.row_layout).parameters)
    assert "lead_w" in params
    assert not (params & {"selected", "hovered", "current", "state", "opt",
                          "option", "discriminator", "index"})


# ── what actually gets painted ──────────────────────────────────────────────

def test_the_region_code_is_painted_in_the_slot(delegate):
    """The region path draws a CODE, positioned exactly where the layout said."""
    delegate.set_row_discriminator(DISCRIMINATOR_REGION)
    painted = paint_channel_row(delegate, _index(LANGUAGE_ROLE="us"), rect=ROW)

    box = layout.row_layout(
        ROW, has_art=True, art_square=False,
        rail_w=0, lead_w=layout.LEAD_W)
    hits = [(r, t) for r, t, _c, _f in painted.texts if t == "US"]
    assert hits, f"no region code was painted; got {[t for _, t, _, _ in painted.texts]}"
    rect, _ = hits[0]
    assert rect.left() == box.lead.left(), \
        f"the code was painted at x={rect.left()}, the layout reserved {box.lead.left()}"


def test_the_region_code_is_normalized_not_the_raw_value(delegate):
    """It reads the stored ``detected_region`` through the shared vocabulary."""
    delegate.set_row_discriminator(DISCRIMINATOR_REGION)
    painted = paint_channel_row(delegate, _index(LANGUAGE_ROLE="us"), rect=ROW)
    assert "US" in [t for _, t, _, _ in painted.texts]
    assert "us" not in [t for _, t, _, _ in painted.texts]


def test_no_discriminator_paints_no_slot(delegate):
    """The default on every row outside Sports."""
    assert delegate.row_discriminator == ""
    painted = paint_channel_row(delegate, _index(LANGUAGE_ROLE="us"), rect=ROW)

    box = layout.row_layout(ROW, has_art=True, art_square=False, rail_w=0)
    assert box.lead.isEmpty()
    titles = [t for _, t, _, _ in painted.texts]
    assert "The Murky Stream" in titles, "sanity: the row painted at all"


def test_the_title_really_is_wider_when_the_slot_collapses(delegate):
    """End to end, through the real paint: the reclaimed width reaches the title.

    The geometry test above proves ``row_layout`` returns a wider box. This
    proves the painter uses it — a delegate is free to ignore what the layout
    handed it, which is why this suite asserts painted rects rather than
    layout return values.
    """
    delegate.set_row_discriminator(DISCRIMINATOR_REGION)
    with_slot = paint_channel_row(delegate, _index(LANGUAGE_ROLE="us"), rect=ROW)
    delegate.set_row_discriminator("")
    collapsed = paint_channel_row(delegate, _index(LANGUAGE_ROLE="us"), rect=ROW)

    def title_rect(p):
        for r, t, _c, _f in p.texts:
            if t == "The Murky Stream":
                return r
        raise AssertionError("the title was not painted")

    assert title_rect(collapsed).left() < title_rect(with_slot).left(), \
        "the title did not move left when the slot collapsed"
    assert title_rect(collapsed).width() > title_rect(with_slot).width(), \
        "the title box did not grow when the slot collapsed"


def test_an_unknown_discriminator_falls_back_to_collapsed(delegate):
    """Matches ``set_density``: an unknown value is not a crash and not a guess."""
    delegate.set_row_discriminator("teams")
    assert delegate.row_discriminator == ""


def test_a_sport_with_no_icon_collapses_rather_than_reserving_a_blank(delegate):
    """A sport outside VECTOR_KEYS has nothing to draw, so it takes no width."""
    delegate.set_row_discriminator(DISCRIMINATOR_SPORT)
    painted = paint_channel_row(
        delegate, _index(SPORT_ROLE="underwater_basketweaving"), rect=ROW)

    def title_rect(p):
        return next(r for r, t, _c, _f in p.texts if t == "The Murky Stream")

    delegate.set_row_discriminator("")
    bare = paint_channel_row(delegate, _index(SPORT_ROLE=""), rect=ROW)
    assert title_rect(painted) == title_rect(bare), \
        "an unpaintable sport still stole the title's width"
