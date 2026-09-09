"""Episode watch state written off-thread must reach the open series tree (#836).

The queue path marks each auto-advanced episode 100%-complete from a worker
while the series tree is already drawn.  Nothing told the tree, so it kept
showing whatever it was populated with — and the user then acted on that stale
view: they unmarked the episodes the tree *did* show as watched, left the ones
it did not, and came back to a season with an unwatched hole in the middle of a
watched run.  Same window, two disagreeing answers about the same rows.

These tests drive the real render helpers and assert the RENDERED result — the
season row's text glyph and the episode row's painted icon pixmap — not just
the DTO, because a DTO that updates while the glyph does not is exactly the bug.

Covered:
1. refresh_episode_watch_state repaints a row whose DB state moved behind it.
2. ...and re-derives the season rollup glyph (◐ partial → ✓ all watched).
3. It is a no-op (never raises) when the tree holds none of those episodes.
4. "No" to the queue-end prompt UNMARKS — it used to leave them watched.
5. "Yes" promotes to manual and still refreshes.
6. mark_watched_bulk(..., False) clears last_played_via, so the stored row and
   the tree's unwatched DTO cannot disagree at the next repopulate.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem

from metatv.core.database import Database, EpisodeDB
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.dtos import EpisodeDTO
from metatv.gui import icons as _icons
from metatv.gui.main_window_series import _SeriesMixin


# ---------------------------------------------------------------------------
# Fixtures / host
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class _Cfg:
    watch_partial_threshold = 0.10
    prompt_after_autoplay = True


class _SeriesHost(_SeriesMixin):
    """Minimal host: only what refresh_episode_watch_state actually touches.

    ``_SeriesMixin`` is a plain mixin (not a QObject), so a real instance is
    safe here — no ``__new__``-skipped Qt base to explode on attribute access.
    """

    def __init__(self, db, tree):
        self.db = db
        self.config = _Cfg()
        self.series_tree = tree


def _make_db(tmp_path) -> Database:
    db = Database(f"sqlite:///{tmp_path / 'watch.db'}")
    db.create_tables()
    return db


def _add_episode(db, ep_id: str, num: int, *, watched: bool) -> None:
    with db.session_scope() as session:
        session.add(EpisodeDB(
            id=ep_id, season_id="s1", series_id="series-1", provider_id="p",
            episode_id=str(num), episode_num=num, season_num=1,
            title=f"Episode {num}",
            is_watched=watched, watch_completed=watched,
            watch_percent=100 if watched else 0,
            last_played_via="manual" if watched else None,
        ))


def _dto(ep_id: str, num: int, *, watched: bool) -> EpisodeDTO:
    return EpisodeDTO(
        id=ep_id, episode_num=num, season_num=1, title=f"Episode {num}",
        series_name="Becker", stream_url=None, duration="22:00",
        is_watched=watched, rating=8.0, series_id="series-1", provider_id="p",
        season_id="s1", watch_completed=watched, watch_percent=100 if watched else 0,
        last_played_via="manual" if watched else None,
    )


def _build_tree(host, episodes) -> tuple[QTreeWidgetItem, dict[str, QTreeWidgetItem]]:
    """Populate one season node with *episodes* = [(id, num, watched)]."""
    tree = host.series_tree
    season_item = QTreeWidgetItem(tree)
    dtos = []
    items: dict[str, QTreeWidgetItem] = {}
    for ep_id, num, watched in episodes:
        dto = _dto(ep_id, num, watched=watched)
        dtos.append(dto)
        child = QTreeWidgetItem(season_item)
        child.setData(0, Qt.ItemDataRole.UserRole, {"type": "episode", "data": dto})
        host._update_episode_item_icon(child, dto)
        items[ep_id] = child
    season_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "season", "data": None})
    season_item.setText(0, host._season_label("Season 1", dtos))
    return season_item, items


def _icon_bytes(item: QTreeWidgetItem) -> bytes:
    """Rendered pixel content of the row's watch glyph — the thing the user sees."""
    img = item.icon(0).pixmap(24, 24).toImage()
    return bytes(img.constBits().asstring(img.sizeInBytes()))


# ---------------------------------------------------------------------------
# 1 + 2. A write behind the tree's back reaches the row AND the season rollup
# ---------------------------------------------------------------------------

def test_offthread_write_repaints_row_and_season_rollup(qapp, tmp_path, owned_widgets):
    db = _make_db(tmp_path)
    for n in (1, 2):
        _add_episode(db, f"e{n}", n, watched=(n == 1))

    tree = QTreeWidget()
    owned_widgets.own(tree)
    host = _SeriesHost(db, tree)
    season_item, items = _build_tree(host, [("e1", 1, True), ("e2", 2, False)])

    # The season starts PARTIAL and e2's row is painted unwatched.
    assert _icons.partial_watched_icon in season_item.text(0)
    before = _icon_bytes(items["e2"])

    # A worker marks e2 complete — exactly what the queue's auto-advance does.
    with db.session_scope() as session:
        RepositoryFactory(session).episodes.record_watch_progress("e2", 1.0, 1.0, 0.9, "queue")

    # Nothing has told the tree yet: it still shows the stale state.
    assert _icon_bytes(items["e2"]) == before
    assert _icons.partial_watched_icon in season_item.text(0)

    host.refresh_episode_watch_state(["e2"])

    # Rendered appearance moved, not merely the DTO.
    assert _icon_bytes(items["e2"]) != before
    assert items["e2"].data(0, Qt.ItemDataRole.UserRole)["data"].watch_completed is True
    assert items["e2"].data(0, Qt.ItemDataRole.UserRole)["data"].last_played_via == "queue"
    # Season rolled up from partial to all-watched.
    assert _icons.watched_icon in season_item.text(0)
    assert _icons.partial_watched_icon not in season_item.text(0)
    # Untouched fields survive the round trip (dataclasses.replace, not a rebuild).
    assert items["e2"].data(0, Qt.ItemDataRole.UserRole)["data"].rating == 8.0


def test_refresh_carries_unwatch_back_to_the_row(qapp, tmp_path, owned_widgets):
    """The inverse direction: a row shown watched must go back to unwatched."""
    db = _make_db(tmp_path)
    _add_episode(db, "e1", 1, watched=True)

    tree = QTreeWidget()
    owned_widgets.own(tree)
    host = _SeriesHost(db, tree)
    season_item, items = _build_tree(host, [("e1", 1, True)])
    before = _icon_bytes(items["e1"])
    assert _icons.watched_icon in season_item.text(0)

    with db.session_scope() as session:
        RepositoryFactory(session).episodes.mark_watched_bulk(["e1"], False)
    host.refresh_episode_watch_state(["e1"])

    assert _icon_bytes(items["e1"]) != before
    dto = items["e1"].data(0, Qt.ItemDataRole.UserRole)["data"]
    assert dto.watch_completed is False and dto.last_played_via is None
    assert _icons.watched_icon not in season_item.text(0)


# ---------------------------------------------------------------------------
# 3. Safe to call from any writer, whatever the tree currently holds
# ---------------------------------------------------------------------------

def test_refresh_is_a_noop_for_episodes_not_in_the_tree(qapp, tmp_path, owned_widgets):
    db = _make_db(tmp_path)
    _add_episode(db, "e1", 1, watched=False)
    tree = QTreeWidget()
    owned_widgets.own(tree)
    host = _SeriesHost(db, tree)
    _season_item, items = _build_tree(host, [("e1", 1, False)])
    before = _icon_bytes(items["e1"])

    host.refresh_episode_watch_state(["some-other-series-episode"])
    host.refresh_episode_watch_state([])

    assert _icon_bytes(items["e1"]) == before


def test_refresh_without_a_series_tree_does_not_raise(tmp_path):
    """An off-thread writer calls this unconditionally — before any drill-in."""
    host = _SeriesHost(_make_db(tmp_path), None)
    del host.series_tree
    host.refresh_episode_watch_state(["e1"])  # must not raise


# ---------------------------------------------------------------------------
# 4 + 5. Both answers to "Still watching?" write, and both refresh
# ---------------------------------------------------------------------------

class _PromptHost:
    """Host for the two queue-end workers: db + the refresh signal's emit."""

    def __init__(self, db):
        self.db = db
        self.emitted: list[list[str]] = []

        class _Sig:
            def __init__(self, sink):
                self._sink = sink

            def emit(self, ids):
                self._sink.append(list(ids))

        self._episode_watch_state_changed = _Sig(self.emitted)


def _prompt_host(db):
    from metatv.gui.queue_end_prompt import _QueueEndPromptMixin

    class _H(_QueueEndPromptMixin, _PromptHost):
        pass

    return _H(db)


def test_answering_no_unmarks_the_auto_advanced_episodes(tmp_path):
    """"Did you watch them?" → No must take the mark back, not just grey it."""
    db = _make_db(tmp_path)
    for n in (1, 2):
        _add_episode(db, f"e{n}", n, watched=False)
    # The queue already wrote them complete while it was advancing.
    with db.session_scope() as session:
        repo = RepositoryFactory(session).episodes
        for n in (1, 2):
            repo.record_watch_progress(f"e{n}", 1.0, 1.0, 0.9, "queue")

    host = _prompt_host(db)
    host._bg_unmark_queue_episodes(["e1", "e2"])

    with db.session_scope(commit=False) as session:
        repo = RepositoryFactory(session).episodes
        for n in (1, 2):
            ep = repo.get_by_id(f"e{n}")
            assert ep.watch_completed is False, "answering No left the episode watched"
            assert ep.is_watched is False
            assert ep.watch_percent == 0
            assert ep.last_played_via is None
    assert host.emitted == [["e1", "e2"]], "the tree was never told about the unmark"


def test_answering_yes_promotes_and_still_refreshes(tmp_path):
    db = _make_db(tmp_path)
    _add_episode(db, "e1", 1, watched=False)
    with db.session_scope() as session:
        RepositoryFactory(session).episodes.record_watch_progress("e1", 1.0, 1.0, 0.9, "queue")

    host = _prompt_host(db)
    host._bg_promote_queue_episodes(["e1"])

    with db.session_scope(commit=False) as session:
        ep = RepositoryFactory(session).episodes.get_by_id("e1")
        assert ep.watch_completed is True
        assert ep.last_played_via == "manual"
    assert host.emitted == [["e1"]]


# ---------------------------------------------------------------------------
# 6. The stored row and the tree's unwatched DTO must agree
# ---------------------------------------------------------------------------

def test_bulk_unmark_clears_played_via(tmp_path):
    db = _make_db(tmp_path)
    _add_episode(db, "e1", 1, watched=True)
    with db.session_scope() as session:
        RepositoryFactory(session).episodes.mark_watched_bulk(["e1"], False)
    with db.session_scope(commit=False) as session:
        ep = RepositoryFactory(session).episodes.get_by_id("e1")
        assert ep.last_played_via is None
        assert ep.watch_progress == 0
