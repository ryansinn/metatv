"""The active-filter chip line: what it says, and what it looks like saying it.

Two halves, deliberately kept apart.

``describe_active_filters`` has no Qt in it, so its rules — which facets count
as active, how several values collapse, what order they read in — are tested as
plain functions.

The widget half is tested by **looking at pixels**. That is not belt-and-braces:
the first build of this bar had correct tokens, a correct stylesheet, correct
geometry, and rendered the chips as bare text on the page colour, because a
plain ``QWidget`` does not paint a stylesheet background without
``WA_StyledBackground``. Nothing about the style was wrong, so no style test
could see it. Sampling the render is what sees it.
"""

from __future__ import annotations

import pytest

from metatv.gui.filter_chips import (
    FilterChip, MEDIA_ALL, describe_active_filters,
)


# ── The rules ────────────────────────────────────────────────────────────────

def test_nothing_constrained_says_nothing():
    """All three media kinds and no tag includes is not a filter."""
    state = {"media_types": sorted(MEDIA_ALL), "tag_includes": None}
    assert describe_active_filters(state) == []


def test_one_value_drops_the_facet_name():
    """``4K``, not ``Quality: 4K`` — the shortness is the point of the line."""
    chips = describe_active_filters({"tag_includes": {"quality": {"4k"}}})
    assert [c.label for c in chips] == ["4k"]
    assert chips[0].tooltip == "Quality: 4k"


def test_several_values_bring_the_facet_name_back():
    """``English +6`` alone does not say WHICH language axis — there are three."""
    chips = describe_active_filters(
        {"tag_includes": {"subtitle": {"en", "fr", "de", "es"}}}
    )
    assert chips[0].label == "Subtitles: de, en +2"
    assert chips[0].tooltip == "Subtitles: de, en, es, fr"


def test_each_media_kind_is_its_own_chip():
    """So one of two can be dropped without opening the panel."""
    chips = describe_active_filters({"media_types": ["movie", "series"]})
    assert [(c.facet, c.label) for c in chips] == [
        ("media:movie", "Movies"), ("media:series", "Series"),
    ]


def test_media_leads_and_hide_watched_trails():
    chips = describe_active_filters({
        "media_types": ["movie"],
        "tag_includes": {"genre": {"Drama"}},
        "hide_watched": True,
    })
    assert [c.facet for c in chips] == ["media:movie", "genre", "hide_watched"]


def test_labels_are_resolved_through_the_panel():
    """Values are stored as keys and shown as labels."""
    chips = describe_active_filters(
        {"tag_includes": {"language": {"en"}}},
        label_for=lambda facet, key: {"en": "English"}[key],
    )
    assert chips[0].label == "English"


def test_an_unknown_key_still_gets_a_chip():
    """A persisted filter can name a value this library no longer has.

    A chip reading the raw key is far better than a chip that silently is not
    there, because the query IS still constrained by it.
    """
    chips = describe_active_filters(
        {"tag_includes": {"language": {"xx"}}},
        label_for=lambda facet, key: key,
    )
    assert chips[0].label == "xx"


def test_all_values_ticked_but_untagged_hidden_says_so():
    """The constraint is the footer, not the values — say the true thing.

    ``tag_includes`` carries a full value set in this case exactly as it does
    for a real value constraint, so without the totals the chip would read
    "Language: Arabic +40" and be a lie about what is filtering.
    """
    chips = describe_active_filters(
        {"tag_includes": {"language": {"en", "fr"}},
         "facets_hiding_untagged": {"language"}},
        facet_totals={"language": 2},
    )
    assert [c.label for c in chips] == ["Language: tagged only"]


def test_a_real_value_constraint_is_not_mistaken_for_the_untagged_case():
    chips = describe_active_filters(
        {"tag_includes": {"language": {"en"}},
         "facets_hiding_untagged": {"language"}},
        facet_totals={"language": 40},
    )
    assert chips[0].label == "en"
    assert "untagged hidden" in chips[0].tooltip


# ── The widget ───────────────────────────────────────────────────────────────

@pytest.fixture
def bar(qapp):
    from metatv.gui.filter_chip_bar import FilterChipBar
    w = FilterChipBar()
    w.resize(900, 32)
    w.show()
    qapp.processEvents()
    return w


def _three(bar, qapp):
    bar.set_chips([
        FilterChip("media:movie", "Movies", "t"),
        FilterChip("quality", "4K", "t"),
        FilterChip("language", "English", "t"),
    ])
    qapp.processEvents()
    return bar


def test_chips_are_laid_out_left_to_right_at_a_uniform_height(bar, qapp):
    """Rendered geometry, not list order. Order is not position."""
    from metatv.gui.filter_chip_bar import CHIP_HEIGHT

    _three(bar, qapp)
    rects = [c.geometry() for c in bar._chips]
    assert [r.height() for r in rects] == [CHIP_HEIGHT] * 3
    xs = [r.x() for r in rects]
    assert xs == sorted(xs) and len(set(xs)) == 3, "chips overlap or are unordered"
    for a, b in zip(rects, rects[1:]):
        assert b.x() >= a.right(), "chips overlap"
    tops = {r.y() for r in rects}
    assert len(tops) == 1, "chips do not share a baseline"


def test_a_chip_paints_a_fill_distinct_from_the_bar(bar, qapp):
    """The bug that shipped in the first build, caught the only way it can be.

    Tokens, stylesheet and geometry were all correct while the chips rendered
    as bare text: a plain QWidget leaves its stylesheet background unpainted
    unless WA_StyledBackground is set. So this samples the actual render.
    """
    _three(bar, qapp)
    image = bar.grab().toImage()
    chip = bar._chips[0].geometry()

    # Inside the chip's fill: past the 1px border, before the label's padding.
    inside = image.pixelColor(chip.x() + 4, chip.y() + chip.height() // 2)
    # The bar itself, in the gap after the last chip.
    last = bar._chips[-1].geometry()
    outside = image.pixelColor(last.right() + 2, last.y() + last.height() // 2)

    assert inside != outside, (
        f"chip fill {inside.name()} is identical to the bar behind it "
        f"{outside.name()} — the chip is invisible"
    )


def test_the_chip_label_is_legible_on_the_chip(bar, qapp):
    """A fill nobody can read text on is not an improvement on no fill."""
    from metatv.gui import theme as _theme
    from metatv.gui.token_color import to_qcolor

    def _lum(c):
        def ch(v):
            v /= 255
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
        return 0.2126 * ch(c.red()) + 0.7152 * ch(c.green()) + 0.0722 * ch(c.blue())

    fill = to_qcolor(_theme.COLOR_BG_CARD)
    text = to_qcolor(_theme.COLOR_TEXT_HI)
    a, b = sorted((_lum(fill), _lum(text)))
    ratio = (b + 0.05) / (a + 0.05)
    assert ratio >= 4.5, f"chip label contrast {ratio:.2f}:1 is below 4.5:1"


def test_the_bar_can_be_squeezed(bar, qapp):
    """A chip must never hold the window open.

    A QHBoxLayout publishes the sum of its children as the widget's minimum
    width. Left alone, one long chip would make the bar — and so the whole
    window — un-shrinkable, and the bar would never get narrow enough to
    notice it was short of room.
    """
    _three(bar, qapp)
    # minimumSizeHint() is still computed from the layout's children; what
    # decides whether the bar can actually BE narrow is minimumSize, which is
    # set explicitly and overrides the hint. So assert the outcome, not the
    # hint: ask for 140px and check we got 140px.
    assert bar.minimumWidth() == 0
    bar.resize(140, 32)
    qapp.processEvents()
    assert bar.width() == 140, (
        f"asked for 140px, got {bar.width()}px — the chip bar imposes a "
        f"minimum width on everything above it"
    )


def test_chips_that_do_not_fit_are_hidden_behind_a_counted_marker(bar, qapp):
    _three(bar, qapp)
    assert bar.visible_chip_labels() == ["Movies", "4K", "English"]
    assert not bar._overflow.isVisible()

    bar.resize(300, 32)
    qapp.processEvents()

    shown = bar.visible_chip_labels()
    assert len(shown) < 3, "nothing was hidden in a bar too narrow to hold it"
    assert bar._overflow.isVisible()
    assert bar._overflow.text() == f"+{3 - len(shown)}"
    for chip in bar._chips:
        if chip.isVisible():
            assert chip.geometry().right() <= bar.width(), "a visible chip overflows"

    # The marker has to fit too, and it is the only way to the hidden chips.
    assert bar._overflow.geometry().right() <= bar.width()
    assert bar._add.geometry().right() <= bar.width()


def test_the_marker_and_add_button_survive_the_squeeze(bar, qapp):
    """Hiding the way back in would strand the user in a filter they cannot see."""
    _three(bar, qapp)
    bar.resize(240, 32)
    qapp.processEvents()
    assert bar._add.isVisible(), "+ Add filter was squeezed out"
    assert bar._overflow.isVisible(), "the overflow marker was squeezed out"


def test_the_empty_state_replaces_the_chips_and_hides_clear_all(bar, qapp):
    _three(bar, qapp)
    assert bar._clear.isVisible()
    bar.set_chips([])
    qapp.processEvents()
    assert bar.chip_labels() == []
    assert bar._empty.isVisible()
    assert not bar._clear.isVisible()


def test_the_close_button_reports_the_facet_not_the_label(bar, qapp):
    """The host clears by facet; a label is not routable."""
    seen = []
    bar.remove_requested.connect(seen.append)
    _three(bar, qapp)
    bar._chips[1]._close.click()
    assert seen == ["quality"]


@pytest.mark.parametrize("width", [320, 300, 280, 260, 240, 220])
def test_a_shown_chip_is_never_squashed(bar, qapp, width):
    """A chip is shown whole or not at all.

    Room for the ``+N`` marker is reserved BEFORE deciding what fits. Without
    that, the last chip that "fits" takes the space the marker then needs, and
    Qt resolves the overrun by squeezing the chips — so the line keeps one more
    chip at the price of clipping its label. A chip reading "Langua…" is worse
    than a chip counted in the marker, because the whole point of the line is
    that you can read it at a glance.
    """
    _three(bar, qapp)
    bar.resize(width, 32)
    qapp.processEvents()
    for chip in bar._chips:
        if chip.isVisible():
            assert chip.width() >= chip.sizeHint().width(), (
                f"at {width}px the chip {chip.label()!r} is drawn "
                f"{chip.width()}px wide against a natural "
                f"{chip.sizeHint().width()}px — its label is clipped"
            )
