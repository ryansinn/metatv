"""D60, the rest of the reader half: rows outside the main list take a change made elsewhere.

Each surface subscribes to ``channel_state_bus`` and patches its own rows
through ``channel_state_bus.row_changes`` — the one delta → field table:

* details pane — Similar and Other versions rows;
* trail map — column rows (drawn from ``_seed_rows``/``_similars_cache``) and
  the detail strip;
* Similar lightbox — the main card and the strip, without a reload;
* Discover — the card badges, rebuilding only the shelves that hold the card.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from PyQt6.QtWidgets import QLabel, QPushButton

from tests.conftest import destroy_widget


def _tips(widget) -> list[str]:
    return [w.toolTip() for w in widget.findChildren((QLabel, QPushButton)) if not w.isHidden()]


# ── the one translator ──────────────────────────────────────────────────────

def test_row_changes_speaks_each_rows_field_names():
    from metatv.core.discovery_engine import ContentCard
    from metatv.gui.channel_state_bus import row_changes
    from metatv.gui.details_versions import ChannelVersion
    v = ChannelVersion(channel_id="a", name="A", in_queue=False)
    assert row_changes({"rating": -1, "is_suppressed": True, "watch_completed": True}, v) == {
        "user_rating": -1, "is_rec_suppressed": True, "watch_completed": True}
    card = ContentCard(channel_id="a", title="A", media_type="movie", thumbnail_url=None,
                       rating=None, year=None, genre=None, progress_fraction=0.4)
    assert row_changes({"rating": 1, "watch_completed": True}, card) == {
        "is_liked": True, "already_watched": True, "progress_fraction": 0.0}
    assert row_changes({"watch_completed": True, "in_queue": True}, {"id": "a", "watched": False,
                                                                     "in_queue": False}) == {
        "watched": True, "in_queue": True}
    assert row_changes({"is_hidden": True}, {"id": "a"}) == {}, "a field the row lacks is left out"


# ── details pane ────────────────────────────────────────────────────────────

def test_a_similar_row_takes_a_queue_change_made_elsewhere(qapp):
    from metatv.gui.details_versions import ChannelVersion
    from tests.test_episode_grain_queue_favorites import _fake_channel, _make_details_pane
    pane = _make_details_pane(qapp)
    try:
        pane.show_channel(_fake_channel("movie", name="Origin"))
        pane.set_similar_titles([ChannelVersion(channel_id="sim-1", name="Akira", in_queue=False,
                                                media_type="movie")])
        assert "Add to Watch Later" in _tips(pane._similar)
        pane.on_channel_state("sim-1", {"in_queue": True})
        assert "Remove from Watch Later" in _tips(pane._similar)
        pane.on_channel_state("someone-else", {"in_queue": False})
        assert "Remove from Watch Later" in _tips(pane._similar)
    finally:
        destroy_widget(pane)


# ── trail map ───────────────────────────────────────────────────────────────

def test_trail_map_column_rows_take_a_change_made_elsewhere(tmp_path, qapp):
    from tests.test_trail_map import _dto, _make_view, _seed_db
    tm = _make_view(_seed_db(tmp_path / "t.db"), qapp)
    row = _dto(id="r1", title="Paprika")
    tm._seed_rows = [row]
    tm._row_cache = {"r1": row}
    try:
        tm.show()
        tm._render_columns()
        qapp.processEvents()
        assert "Watched" not in _tips(tm)
        tm.on_channel_state("r1", {"watch_completed": True})
        qapp.processEvents()
        assert "Watched" in _tips(tm), "the column row's badge shows it"
        assert tm._row_cache["r1"].watch_completed and tm._row_cache["r1"].watch_percent == 100
    finally:
        from tests.test_trail_map import _LIVE_VIEWS
        _LIVE_VIEWS.remove((tm, tm._host_ref))
        tm.shutdown()
        destroy_widget(tm)
        destroy_widget(tm._host_ref)


# ── Similar lightbox ────────────────────────────────────────────────────────

def test_lightbox_patches_the_card_and_strip_without_a_reload(qapp):
    from metatv.gui.similar_lightbox import SimilarTitleLightbox
    lb = SimilarTitleLightbox.__new__(SimilarTitleLightbox)
    applied: list = []
    lb._apply_data = lambda cid, data: applied.append((cid, data))
    lb._current_id = "main"
    lb.isVisible = lambda: True
    lb._last_data = {"id": "main", "in_queue": False, "is_favorite": False, "user_rating": 0,
                     "similar": [{"id": "s1", "watched": False, "in_queue": False}]}
    lb.on_channel_state("s1", {"watch_completed": True})
    assert applied[-1][1]["similar"][0]["watched"] is True
    lb.on_channel_state("main", {"is_favorite": True})
    assert applied[-1][1]["is_favorite"] is True
    n = len(applied)
    lb.on_channel_state("elsewhere", {"is_favorite": True})
    assert len(applied) == n, "a channel the lightbox does not show changes nothing"


# ── Discover ────────────────────────────────────────────────────────────────

def test_discover_rebuilds_only_the_shelf_holding_the_card(qapp):
    from metatv.core.discovery_engine import ContentCard
    from metatv.gui.discover_view import DiscoverView

    def card(cid):
        return ContentCard(channel_id=cid, title=cid, media_type="movie", thumbnail_url=None,
                           rating=None, year=None, genre=None)
    view = DiscoverView.__new__(DiscoverView)
    view._image_cache = view._config = None
    view._trigger_image_load_all = lambda: None
    shelves = {"a": MagicMock(), "b": MagicMock()}
    view._shelf_widgets = shelves
    view._shelf_data_cache = {"a": [card("x"), card("y")], "b": [card("z")]}
    view.on_channel_state("y", {"in_queue": True, "is_favorite": True})
    shelves["b"].set_cards.assert_not_called()
    rebuilt = shelves["a"].set_cards.call_args[0][0]
    assert [c.in_queue for c in rebuilt] == [False, True] and rebuilt[1].is_favorite
    assert view._shelf_data_cache["a"][1].in_queue
