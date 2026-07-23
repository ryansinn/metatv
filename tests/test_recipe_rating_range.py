"""Behavioral tests for the recipe rating-range ingredient + slim recipe card.

Covers the four requirements of the rating-range slice:

(a) ``rating_range`` threaded through the faceted query chokepoint — a real DB
    with channels rated 3.0 / 7.5 / unrated proves the SQL band + NULL semantics.
(b) Slider interaction — a click moves the NEAREST handle to that point.
(c) The saved-recipe data model round-trips the rating band, and an old-format
    recipe (no ``rating_range`` key) loads as the full span (no filter).
(d) The recipe card puts Clear in the title row + Save alone at content width,
    shrinking the card's minimum width (Deliverable A).
"""

from __future__ import annotations

import uuid

import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QScrollArea

from metatv.core.database import ChannelDB, Database, ProviderDB
from metatv.core.recipe_state import (
    DEFAULT_RATING_RANGE,
    deserialize_recipe,
    serialize_recipe,
)
from metatv.core.repositories import RepositoryFactory


# ---------------------------------------------------------------------------
# (a) rating_range threaded through the faceted query — real DB
# ---------------------------------------------------------------------------

@pytest.fixture
def rated_session(tmp_path):
    """A file-backed DB seeded with three Drama channels: 3.0, 7.5, unrated."""
    db = Database(f"sqlite:///{tmp_path / 'rating.db'}")
    db.create_tables()
    s = db.get_session()

    p = ProviderDB(
        id="p1", name="P1", type="xtream", url="u",
        username="u", password="p", is_active=True,
    )
    s.add(p)
    s.flush()

    ids: dict[str, str] = {}

    def _mk(key: str, rating) -> str:
        cid = str(uuid.uuid4())
        raw = {} if rating is None else {"rating": rating}
        ch = ChannelDB(
            id=cid, source_id=str(uuid.uuid4()), provider_id="p1",
            name=f"Ch {key}", media_type="movie", raw_data=raw,
        )
        s.add(ch)
        s.flush()
        RepositoryFactory(s).tags.set_content_tags(cid, [("genre", "Drama", "test")])
        s.flush()
        ids[key] = cid
        return cid

    _mk("low", "3.0")
    _mk("high", "7.5")
    _mk("unrated", None)
    s.commit()

    yield s, ids
    s.close()
    db.close()


def _drama_ids(session, rating_range):
    return RepositoryFactory(session).tags.get_channel_ids_by_tag_facets(
        {"genre": {"Drama"}}, rating_range=rating_range
    )


def _drama_count(session, rating_range):
    return RepositoryFactory(session).tags.count_channels_by_tag_facets(
        includes={"genre": {"Drama"}}, rating_range=rating_range
    )


def test_full_range_returns_all_three(rated_session):
    """[0, 10] (and None) impose no filter → all three channels."""
    s, _ = rated_session
    assert _drama_count(s, (0.0, 10.0)) == 3
    assert _drama_count(s, None) == 3


def test_floor_seven_returns_only_high_and_drops_unrated(rated_session):
    """[7, 10] returns only the 7.5 channel; 3.0 below floor, unrated dropped."""
    s, ids = rated_session
    got = _drama_ids(s, (7.0, 10.0))
    assert got == {ids["high"]}


def test_floor_five_drops_unrated(rated_session):
    """[5, 10] returns only the 7.5 channel — unrated dropped because min > 0."""
    s, ids = rated_session
    got = _drama_ids(s, (5.0, 10.0))
    assert got == {ids["high"]}
    assert ids["unrated"] not in got


def test_floor_zero_keeps_unrated(rated_session):
    """[0, 5] keeps unrated content (floor is 0) plus the 3.0; drops the 7.5."""
    s, ids = rated_session
    got = _drama_ids(s, (0.0, 5.0))
    assert got == {ids["low"], ids["unrated"]}


def test_sample_cards_respect_rating_range(rated_session):
    """The card sampler (Now Plating) honours the same band as the count."""
    s, ids = rated_session
    cards = RepositoryFactory(s).tags.sample_channels_by_tag_facets(
        includes={"genre": {"Drama"}}, rating_range=(7.0, 10.0), limit=10,
    )
    assert {c.channel_id for c in cards} == {ids["high"]}


# ---------------------------------------------------------------------------
# (b) Slider interaction — click moves the nearest handle
# ---------------------------------------------------------------------------

def _slider(qtbot):
    from metatv.gui.rating_range_slider import RatingRangeSlider
    w = RatingRangeSlider()
    qtbot.addWidget(w)
    w.resize(220, 30)
    w.show()
    return w


def _click_value(w, value):
    """QTest-click the bar at *value*'s pixel position."""
    x = round(w._value_to_x(value))
    QTest.mouseClick(w, Qt.MouseButton.LeftButton, pos=QPoint(int(x), w.height() // 2))


def test_open_bar_click_left_sets_floor(qtbot):
    """An open-bar click near value 2 (left of center) sets the MIN floor there."""
    w = _slider(qtbot)
    _click_value(w, 2.0)
    assert w.values() == (2.0, 10.0)


def test_open_bar_click_right_still_sets_floor(qtbot):
    """An open-bar click near value 8 (right of center) also sets the floor.

    The dominant gesture is "at least X": an open-bar click always moves the
    MIN handle (the ceiling is adjusted by grabbing/dragging the max handle).
    """
    w = _slider(qtbot)
    _click_value(w, 8.0)
    assert w.values() == (8.0, 10.0)


def test_click_near_seven_sets_at_least_seven(qtbot):
    """A click near 7 sets "at least 7" and emits that band."""
    w = _slider(qtbot)
    seen: list[tuple[float, float]] = []
    w.rangeChanged.connect(lambda lo, hi: seen.append((lo, hi)))
    _click_value(w, 7.0)
    assert w.values() == (7.0, 10.0)
    assert seen and seen[-1] == (7.0, 10.0)


def test_press_near_max_handle_grabs_ceiling(qtbot):
    """A press on/near the max handle grabs it; an open-bar press sets the floor."""
    w = _slider(qtbot)
    # Right at the max handle → grab "hi"; mid-bar (open) → "lo" (floor).
    assert w._handle_for_press(10.0, w._value_to_x(10.0)) == "hi"
    assert w._handle_for_press(5.0, w._value_to_x(5.0)) == "lo"


def test_drag_ceiling_lowers_max_handle(qtbot):
    """Once the max handle is grabbed, dragging it lowers the ceiling."""
    w = _slider(qtbot)
    w._dragging = "hi"
    w._move_active(6.0)
    assert w.values() == (0.0, 6.0)


def test_set_values_is_silent_and_clamped(qtbot):
    """set_values restores state without emitting and clamps to the scale."""
    w = _slider(qtbot)
    fired: list = []
    w.rangeChanged.connect(lambda *_: fired.append(1))
    w.set_values(-3.0, 42.0, emit=False)
    assert w.values() == (0.0, 10.0)   # clamped to the 0–10 scale
    assert not fired                    # silent restore


# ---------------------------------------------------------------------------
# (c) Saved-recipe data model — rating round-trip + old-format compatibility
# ---------------------------------------------------------------------------

def test_serialize_deserialize_round_trips_rating_range():
    """A saved recipe preserves includes/excludes AND the rating band."""
    includes = {"genre": {"Drama"}}
    excludes = {"language": {"French"}}
    payload = serialize_recipe(includes, excludes, (6.5, 9.0), name="Test")

    got_inc, got_exc, got_rr = deserialize_recipe(payload)
    assert got_inc == includes
    assert got_exc == excludes
    assert got_rr == (6.5, 9.0)


def test_old_format_recipe_loads_as_full_range():
    """A recipe dict written before the rating axis (no key) → full span."""
    old = {"name": "Legacy", "includes": {"genre": ["Comedy"]}, "excludes": {}}
    inc, exc, rr = deserialize_recipe(old)
    assert inc == {"genre": {"Comedy"}}
    assert rr == DEFAULT_RATING_RANGE   # (0.0, 10.0) — no rating filter


def test_malformed_rating_range_falls_back_to_full():
    """A malformed rating_range value degrades to the full span, not a crash."""
    _, _, rr = deserialize_recipe({"rating_range": "nonsense"})
    assert rr == DEFAULT_RATING_RANGE


def test_view_save_then_reload_keeps_rating_range(qtbot, tmp_path):
    """End-to-end: saving a recipe then reloading it restores the rating band."""
    from metatv.core.config import Config
    from metatv.gui.recipe_view import RecipeView
    from PyQt6.QtCore import QObject, pyqtSignal

    class _FakeDB:
        pass

    class _ImgCache(QObject):
        image_loaded = pyqtSignal(str, object)
        image_failed = pyqtSignal(str, str)

        def get_image_async(self, url):
            pass

    def _inert_seam(query_fn, on_ready, token_ref=None, on_error=None):
        # Save/reload path doesn't depend on the async result landing.
        return None

    cfg = Config(config_dir=tmp_path)   # real config on disk (isolated tmp)
    view = RecipeView(_FakeDB(), cfg, _inert_seam, image_cache=_ImgCache())
    qtbot.addWidget(view)

    # Build a recipe with a bounded rating band, then Save.
    view._recipe_includes = {"genre": {"Drama"}}
    view._rating_range = (7.0, 10.0)
    view._on_save_recipe()

    assert cfg.recipe_saved, "recipe was not persisted to Config"
    saved = cfg.recipe_saved[-1]
    assert saved["rating_range"] == [7.0, 10.0]
    name = saved["name"]

    # Clear the recipe → rating band resets to full span.
    view.clear_recipe()
    assert view.rating_range == DEFAULT_RATING_RANGE

    # Reload the saved recipe → the rating band (and ingredient) come back.
    view._on_saved_recipe_selected(name)
    assert view.rating_range == (7.0, 10.0)
    assert view.recipe_includes == {"genre": {"Drama"}}


# ---------------------------------------------------------------------------
# (d) Recipe card layout — Clear in title row, Save alone, slimmer min width
# ---------------------------------------------------------------------------

def _has_ancestor_type(widget, cls) -> bool:
    """True if *widget* has an ancestor of type *cls* in its parent chain."""
    node = widget.parentWidget()
    while node is not None:
        if isinstance(node, cls):
            return True
        node = node.parentWidget()
    return False


# Pre-redesign card minimum width (Save 107 + spacing 8 + Clear 66 + margins 24).
_CARD_MIN_WIDTH_BEFORE = 205


def test_clear_in_title_row_save_stands_alone(qtbot):
    """Clear lives in the scrolled title row; Save stands alone in the footer."""
    from metatv.gui.recipe_widgets import _RecipeRail
    rail = _RecipeRail()
    qtbot.addWidget(rail)
    rail.update_recipe({}, {}, 0)

    # Clear moved into the title row (inside the scroll's inner content).
    assert _has_ancestor_type(rail.clear_btn, QScrollArea)
    # Save is the standalone footer button (NOT inside the scroll area).
    assert not _has_ancestor_type(rail.save_btn, QScrollArea)

    # Footer keeps Save at content width via a trailing stretch (not expanded).
    footer_layout = rail.save_btn.parentWidget().layout()
    has_stretch = any(
        footer_layout.itemAt(i).spacerItem() is not None
        for i in range(footer_layout.count())
    )
    assert has_stretch, "footer must have a trailing stretch so Save is content-width"


def test_card_min_width_shrinks_below_button_row(qtbot):
    """The card's minimum width drops below the old two-button footer width."""
    from metatv.gui.recipe_widgets import _PantrySidebar, _RecipeRail
    rail = _RecipeRail()
    qtbot.addWidget(rail)
    rail.update_recipe({}, {}, 0)

    after = rail.minimumSizeHint().width()
    assert after < _CARD_MIN_WIDTH_BEFORE, (
        f"card min width {after} should be < the pre-redesign {_CARD_MIN_WIDTH_BEFORE}"
    )

    # Spirit of the deliverable: no wider than the pantry list's natural width.
    pantry = _PantrySidebar()
    qtbot.addWidget(pantry)
    assert after <= pantry.width()


def test_rating_line_renders_when_band_active(qtbot):
    """A bounded rating band renders a RATING menu line in the card; full span hides it."""
    from metatv.gui.recipe_widgets import _RecipeRail
    rail = _RecipeRail()
    qtbot.addWidget(rail)

    # Full span → no RATING line.
    rail.update_recipe({}, {}, 0, rating_range=(0.0, 10.0))
    labels_full = [c.text() for c in rail.findChildren(type(rail._name_lbl))]
    assert not any("RATING" in t for t in labels_full)

    # Bounded band → a "RATING" line + a "≥ 7.0" value appear.
    rail.update_recipe({}, {}, 0, rating_range=(7.0, 10.0))
    labels = [c.text() for c in rail.findChildren(type(rail._name_lbl))]
    assert any(t == "RATING" for t in labels)
    assert any("7.0" in t for t in labels)
