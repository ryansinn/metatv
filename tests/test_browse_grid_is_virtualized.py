"""The browse card grid must not materialize a widget per result.

``_BrowseView`` used ``_FlowLayout``, which MEASURES each widget to place it —
so every card had to exist before the layout knew where anything went. Cards
were created in batches of 40 as you scrolled and then kept **forever**: nothing
was ever destroyed, and every scroll tick swept every card ever created.

Discover caps its fetch at 500 so it never hurt. The recipe "Show all" path
pages 60 at a time until the facet's full match count is exhausted, and the
owner's library holds 115,377 distinct movie titles — so one broad genre
include is an unbounded grid.

Measured on this machine: 0.26 ms and 84 KB per card. At 20,000 cards that is
5.2 s of building and 1.6 GB resident.

Every card is ``setFixedSize(card_metrics(zoom))``, so position is arithmetic,
not measurement — which is what makes ``UniformCardGrid`` possible: it sizes
itself for N cards while materializing only the window. The tests below assert
the property that the old design could not have: the live widget count is a
function of the VIEWPORT, not the result count.
"""

import tempfile

import pytest

from metatv.core.config import Config
from metatv.core.discovery_engine import ContentCard
from metatv.core.image_cache import ImageCache
from metatv.gui.discover_browse import _BrowseView


def _card(i: int) -> ContentCard:
    return ContentCard(f"c{i}", f"Title {i}", "movie", "", 7.5, "2024", "Drama")


@pytest.fixture
def view(qapp):
    v = _BrowseView(ImageCache(), Config(config_dir=tempfile.mkdtemp()))
    v.resize(1200, 800)
    v.show()
    qapp.processEvents()
    return v


def test_live_widget_count_does_not_scale_with_the_result_count(view, qapp):
    """The assertion the old grid could never have passed.

    A 40× bigger result set must not produce a 40× bigger widget count. The
    bound is generous — it does not care how many cards fit a viewport, only
    that the number stops tracking the results.
    """
    view.load("Small", [_card(i) for i in range(50)])
    qapp.processEvents()
    small = len(view._grid.live_widgets())

    view.load("Huge", [_card(i) for i in range(20_000)])
    qapp.processEvents()
    huge = len(view._grid.live_widgets())

    assert view._grid.count() == 20_000, "every card is still addressable"
    assert huge <= small + 60, (
        f"{small} live widgets for 50 cards but {huge} for 20,000 — the grid is "
        f"materializing per result again. Use UniformCardGrid."
    )


def test_scrolling_to_the_end_does_not_accumulate_widgets(view, qapp):
    """The old grid never destroyed a card; this one must.

    Scrolling the full height of a 20,000-card grid used to leave 20,000 live
    widgets behind it. The live set must stay bounded at every scroll position,
    which is the difference between recycling and merely deferring.
    """
    view.load("Huge", [_card(i) for i in range(20_000)])
    qapp.processEvents()
    bar = view._grid_scroll.verticalScrollBar()

    counts = []
    for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
        bar.setValue(int(bar.maximum() * fraction))
        qapp.processEvents()
        counts.append(len(view._grid.live_widgets()))

    assert max(counts) <= 250, (
        f"live widget counts across the scroll were {counts} — the grid is "
        f"accumulating rather than recycling")


def test_the_scrollbar_spans_the_whole_result_set_immediately(view, qapp):
    """Height comes from the COUNT, not from the widgets that exist.

    The old grid grew its container as batches were created, so the scrollbar
    lied about how much content there was until you had scrolled through it.
    """
    view.load("Huge", [_card(i) for i in range(20_000)])
    qapp.processEvents()

    width = view._grid_scroll.viewport().width()
    cols = view._grid.columns(width)
    assert cols >= 1
    expected_rows = (20_000 + cols - 1) // cols

    assert view._grid_container.height() >= expected_rows * 100, (
        "the container is not sized for the whole result set")
    assert view._grid_scroll.verticalScrollBar().maximum() > 0


def test_a_recycled_card_comes_back_with_the_right_content(view, qapp):
    """Destroying an off-screen card is only safe if it rebuilds identically."""
    view.load("Huge", [_card(i) for i in range(20_000)])
    qapp.processEvents()
    bar = view._grid_scroll.verticalScrollBar()

    first_titles = [w._card.title for w in view._grid.live_widgets()[:3]]
    assert first_titles == ["Title 0", "Title 1", "Title 2"]

    bar.setValue(bar.maximum())
    qapp.processEvents()
    bar.setValue(0)
    qapp.processEvents()

    assert [w._card.title for w in view._grid.live_widgets()[:3]] == first_titles, (
        "a card that scrolled away and back came back wrong")


def test_geometry_is_pure_index_arithmetic(view):
    """No widget need exist for the grid to know where a card goes.

    This is the property the whole design rests on, so it is asserted directly
    rather than inferred from a rendering.
    """
    grid = view._grid
    grid.set_cards([_card(i) for i in range(100)])
    width = 1000
    cols = grid.columns(width)

    first = grid.rect_for(0, width)
    second = grid.rect_for(1, width)
    next_row = grid.rect_for(cols, width)

    assert first.top() == second.top(), "cards 0 and 1 share a row"
    assert second.left() > first.left(), "card 1 sits to the right of card 0"
    assert next_row.top() > first.top(), "card `cols` wraps to the next row"
    assert next_row.left() == first.left(), "and starts back at the left edge"
