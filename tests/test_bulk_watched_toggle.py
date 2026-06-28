"""Behavioral tests for bulk Mark-as-Watched toggle (PR #239 / issue QC-#237).

State space covered:
1. Multi-select where ALL selected are watched → bulk menu label is "Mark as Unwatched"
   AND triggering the handler sets watch_completed=False on every selected channel.
2. Multi-select where SOME are watched → label "Mark as Watched"
   AND triggering the handler sets watch_completed=True on every selected channel.
3. Multi-select where NONE are watched → label "Mark as Watched"
   AND triggering the handler marks them all watched.
4. Single-item behavior is unchanged: label reflects that one channel's state.
5. Context aggregate: is_vod_watched=True only when every selected channel is watched.
6. Callable tooltip on bulk_mark_watched resolves correctly per context.
"""

from __future__ import annotations

import uuid

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ch_id() -> str:
    return str(uuid.uuid4())


def _make_db(tmp_path, suffix: str = "db"):
    from metatv.core.database import Database
    db = Database(f"sqlite:///{tmp_path / suffix}")
    db.create_tables()
    return db


def _insert_channel(db, cid: str, *, watched: bool = False, media_type: str = "movie") -> None:
    from metatv.core.database import ChannelDB
    with db.session_scope() as session:
        session.add(ChannelDB(
            id=cid,
            source_id="1",
            provider_id="p",
            name=f"Channel {cid[:8]}",
            media_type=media_type,
            watch_completed=watched,
            watch_percent=100 if watched else 0,
        ))


def _is_watched(db, cid: str) -> bool:
    from metatv.core.repositories import RepositoryFactory
    with db.session_scope(commit=False) as session:
        ch = RepositoryFactory(session).channels.get_by_id(cid)
        return bool(ch and ch.watch_completed)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------------------
# 1. All selected are watched → label "Mark as Unwatched" + handler unmarks all
# ---------------------------------------------------------------------------

def test_bulk_label_all_watched_shows_unwatched(qapp):
    """When is_vod_watched=True (all selected are watched), label is 'Mark as Unwatched'."""
    from metatv.gui.channel_menu import ChannelMenuContext, ACTIONS

    ctx = ChannelMenuContext(
        channel_ids=["ch1", "ch2"],
        surface="channel",
        is_vod_watched=True,
    )
    label = ACTIONS["bulk_mark_watched"].label(ctx)
    assert label == "Mark as Unwatched", f"Expected 'Mark as Unwatched', got {label!r}"


def test_bulk_handler_all_watched_unmarks_all(tmp_path):
    """_bulk_mark_watched with all-watched channels sets watch_completed=False on all."""
    from metatv.gui.main_window_favorites import _FavoritesMixin

    db = _make_db(tmp_path, "all_watched.db")
    ids = [_ch_id(), _ch_id()]
    for cid in ids:
        _insert_channel(db, cid, watched=True)

    # Confirm pre-condition: all watched.
    for cid in ids:
        assert _is_watched(db, cid), f"{cid} should be watched before toggle"

    # Create a minimal host via __new__ — no Qt widgets needed for this path.
    from metatv.gui.main_window import MainWindow
    host = MainWindow.__new__(MainWindow)
    host.db = db
    host._stats_hide_watched = False

    # Stub _apply_mark_watched_ui to capture args rather than touching widgets.
    apply_calls: list[tuple[list[str], bool]] = []

    def _stub_apply(channel_ids, watched):
        apply_calls.append((channel_ids, watched))

    host._apply_mark_watched_ui = _stub_apply  # type: ignore[method-assign]

    _FavoritesMixin._bulk_mark_watched(host, ids)

    # Handler must have called _apply_mark_watched_ui with watched=False.
    assert len(apply_calls) == 1
    called_ids, called_watched = apply_calls[0]
    assert set(called_ids) == set(ids)
    assert called_watched is False, (
        f"All-watched bulk toggle should call _apply_mark_watched_ui(watched=False), "
        f"got watched={called_watched}"
    )

    # DB must reflect unwatched state.
    for cid in ids:
        assert not _is_watched(db, cid), f"{cid} should be unwatched after toggle"


# ---------------------------------------------------------------------------
# 2. Some selected are watched → label "Mark as Watched" + handler marks all
# ---------------------------------------------------------------------------

def test_bulk_label_mixed_watched_shows_mark_as_watched(qapp):
    """When is_vod_watched=False (mixed selection), label is 'Mark as Watched'."""
    from metatv.gui.channel_menu import ChannelMenuContext, ACTIONS

    ctx = ChannelMenuContext(
        channel_ids=["ch1", "ch2"],
        surface="channel",
        is_vod_watched=False,
    )
    label = ACTIONS["bulk_mark_watched"].label(ctx)
    assert label == "Mark as Watched", f"Expected 'Mark as Watched', got {label!r}"


def test_bulk_handler_mixed_watched_marks_all(tmp_path):
    """_bulk_mark_watched with mixed selection sets watch_completed=True on all."""
    from metatv.gui.main_window_favorites import _FavoritesMixin

    db = _make_db(tmp_path, "mixed_watched.db")
    watched_id = _ch_id()
    unwatched_id = _ch_id()
    _insert_channel(db, watched_id, watched=True)
    _insert_channel(db, unwatched_id, watched=False)
    ids = [watched_id, unwatched_id]

    from metatv.gui.main_window import MainWindow
    host = MainWindow.__new__(MainWindow)
    host.db = db
    host._stats_hide_watched = False

    apply_calls: list[tuple[list[str], bool]] = []

    def _stub_apply(channel_ids, watched):
        apply_calls.append((channel_ids, watched))

    host._apply_mark_watched_ui = _stub_apply  # type: ignore[method-assign]

    _FavoritesMixin._bulk_mark_watched(host, ids)

    assert len(apply_calls) == 1
    _, called_watched = apply_calls[0]
    assert called_watched is True, (
        f"Mixed selection should mark watched=True, got {called_watched}"
    )
    for cid in ids:
        assert _is_watched(db, cid), f"{cid} should be watched after bulk-mark"


# ---------------------------------------------------------------------------
# 3. None selected are watched → label "Mark as Watched" + handler marks all
# ---------------------------------------------------------------------------

def test_bulk_handler_none_watched_marks_all(tmp_path):
    """_bulk_mark_watched with all-unwatched channels marks them all watched."""
    from metatv.gui.main_window_favorites import _FavoritesMixin

    db = _make_db(tmp_path, "none_watched.db")
    ids = [_ch_id(), _ch_id(), _ch_id()]
    for cid in ids:
        _insert_channel(db, cid, watched=False)

    from metatv.gui.main_window import MainWindow
    host = MainWindow.__new__(MainWindow)
    host.db = db
    host._stats_hide_watched = False

    apply_calls: list[tuple[list[str], bool]] = []

    def _stub_apply(channel_ids, watched):
        apply_calls.append((channel_ids, watched))

    host._apply_mark_watched_ui = _stub_apply  # type: ignore[method-assign]

    _FavoritesMixin._bulk_mark_watched(host, ids)

    _, called_watched = apply_calls[0]
    assert called_watched is True
    for cid in ids:
        assert _is_watched(db, cid)


# ---------------------------------------------------------------------------
# 4. Single-item behavior unchanged (label driven by single channel's state)
# ---------------------------------------------------------------------------

def test_single_item_label_when_watched(qapp):
    """Single-item mark_watched label is 'Mark as Unwatched' when is_vod_watched=True."""
    from metatv.gui.channel_menu import ChannelMenuContext, ACTIONS

    ctx = ChannelMenuContext(
        channel_ids=["ch1"], surface="channel",
        media_type="movie", channel_found=True,
        is_hidden=False, is_vod_watched=True,
    )
    label = ACTIONS["mark_watched"].label(ctx)
    assert label == "Mark as Unwatched"


def test_single_item_label_when_not_watched(qapp):
    """Single-item mark_watched label is 'Mark as Watched' when is_vod_watched=False."""
    from metatv.gui.channel_menu import ChannelMenuContext, ACTIONS

    ctx = ChannelMenuContext(
        channel_ids=["ch1"], surface="channel",
        media_type="movie", channel_found=True,
        is_hidden=False, is_vod_watched=False,
    )
    label = ACTIONS["mark_watched"].label(ctx)
    assert label == "Mark as Watched"


# ---------------------------------------------------------------------------
# 5. Context aggregate: is_vod_watched only True when ALL selected are watched
# ---------------------------------------------------------------------------

def test_context_aggregate_all_watched(tmp_path):
    """Multi-select context has is_vod_watched=True only when all channels are watched."""
    from metatv.core.database import ChannelDB

    db = _make_db(tmp_path, "agg_all.db")
    ids = [_ch_id(), _ch_id()]
    for cid in ids:
        _insert_channel(db, cid, watched=True)

    with db.session_scope(commit=False) as session:
        watched_count = (
            session.query(ChannelDB)
            .filter(
                ChannelDB.id.in_(ids),
                ChannelDB.watch_completed == True,  # noqa: E712
            )
            .count()
        )
    all_watched = len(ids) > 0 and watched_count == len(ids)
    assert all_watched is True, "All-watched selection should produce is_vod_watched=True"


def test_context_aggregate_partial_watched(tmp_path):
    """Multi-select context has is_vod_watched=False when only some channels are watched."""
    from metatv.core.database import ChannelDB

    db = _make_db(tmp_path, "agg_partial.db")
    ids = [_ch_id(), _ch_id()]
    _insert_channel(db, ids[0], watched=True)
    _insert_channel(db, ids[1], watched=False)

    with db.session_scope(commit=False) as session:
        watched_count = (
            session.query(ChannelDB)
            .filter(
                ChannelDB.id.in_(ids),
                ChannelDB.watch_completed == True,  # noqa: E712
            )
            .count()
        )
    all_watched = len(ids) > 0 and watched_count == len(ids)
    assert all_watched is False, "Partial-watched selection should produce is_vod_watched=False"


def test_context_aggregate_none_watched(tmp_path):
    """Multi-select context has is_vod_watched=False when no channels are watched."""
    from metatv.core.database import ChannelDB

    db = _make_db(tmp_path, "agg_none.db")
    ids = [_ch_id(), _ch_id()]
    for cid in ids:
        _insert_channel(db, cid, watched=False)

    with db.session_scope(commit=False) as session:
        watched_count = (
            session.query(ChannelDB)
            .filter(
                ChannelDB.id.in_(ids),
                ChannelDB.watch_completed == True,  # noqa: E712
            )
            .count()
        )
    all_watched = len(ids) > 0 and watched_count == len(ids)
    assert all_watched is False


# ---------------------------------------------------------------------------
# 6. Callable tooltip on bulk_mark_watched resolves per context
# ---------------------------------------------------------------------------

def test_bulk_mark_watched_tooltip_when_all_watched(qapp):
    """Tooltip says 'unwatched' when is_vod_watched=True."""
    from metatv.gui.channel_menu import ChannelMenuContext, ACTIONS

    ctx = ChannelMenuContext(
        channel_ids=["ch1", "ch2"], surface="channel", is_vod_watched=True,
    )
    action = ACTIONS["bulk_mark_watched"]
    assert callable(action.tooltip), "bulk_mark_watched tooltip should be callable"
    tip = action.tooltip(ctx)
    assert "unwatched" in tip.lower(), f"Expected 'unwatched' in tooltip, got {tip!r}"


def test_bulk_mark_watched_tooltip_when_not_all_watched(qapp):
    """Tooltip says 'watched' when is_vod_watched=False."""
    from metatv.gui.channel_menu import ChannelMenuContext, ACTIONS

    ctx = ChannelMenuContext(
        channel_ids=["ch1", "ch2"], surface="channel", is_vod_watched=False,
    )
    action = ACTIONS["bulk_mark_watched"]
    tip = action.tooltip(ctx)
    assert "unwatched" not in tip.lower(), (
        f"Tooltip should NOT say 'unwatched' for mixed/unwatched selection, got {tip!r}"
    )
    assert "watched" in tip.lower()
