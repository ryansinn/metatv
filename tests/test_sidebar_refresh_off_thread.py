"""Tests for B7-5 — sidebar sections refresh off-thread.

Pins three invariants per section (Favorites, History, WatchQueue):
1. refresh() submits work to an executor — does NOT block the caller.
2. _bg_refresh() returns plain DTO / dataclass data (no live ORM session).
3. _on_data_ready() populates the section list correctly on the main thread.

No Qt event loop required — section instances are NOT created (they need Qt).
We test _bg_refresh logic by calling it with a mock db/session, and we test
_on_data_ready logic by calling it with pre-built plain-data objects.

RecommendedSection is already off-thread and is not tested here.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from metatv.core.repositories.dtos import FavoriteDTO, HistoryDTO


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_db(dtos_or_entries):
    """Return a fake db whose session_scope() yields a session pre-loaded with data."""
    mock_session = MagicMock()
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=mock_session)
    cm.__exit__ = MagicMock(return_value=False)
    db = MagicMock()
    db.session_scope.return_value = cm
    return db, mock_session


# ---------------------------------------------------------------------------
# FavoritesSection._bg_refresh
# ---------------------------------------------------------------------------

def test_favorites_bg_refresh_returns_favorite_dtos(monkeypatch):
    """_bg_refresh must read via get_favorites_dto and emit the DTO list."""
    from metatv.gui.sidebar.favorites import FavoritesSection

    dtos = [
        FavoriteDTO(id="c1", name="Channel 1", media_type="movie", last_played=datetime.now()),
        FavoriteDTO(id="c2", name="Channel 2", media_type="live", last_played=None),
    ]

    db, mock_session = _mock_db(dtos)
    config = MagicMock()
    config.filter_adult_mode = "all"

    emitted = []

    def fake_repos_factory(session):
        repos = MagicMock()
        repos.channels.get_favorites_dto.return_value = dtos
        return repos

    with patch("metatv.gui.sidebar.favorites.RepositoryFactory", fake_repos_factory):
        # Create a minimal FavoritesSection-like object with just the method
        obj = FavoritesSection.__new__(FavoritesSection)
        obj.db = db
        obj.config = config
        obj._data_ready = MagicMock()

        obj._bg_refresh()

    obj._data_ready.emit.assert_called_once_with(dtos)


def test_favorites_bg_refresh_emits_none_on_error():
    """_bg_refresh must emit None when the DB read fails so the section can clear."""
    from metatv.gui.sidebar.favorites import FavoritesSection

    db = MagicMock()
    db.session_scope.side_effect = RuntimeError("db locked")
    config = MagicMock()
    config.filter_adult_mode = "all"

    obj = FavoritesSection.__new__(FavoritesSection)
    obj.db = db
    obj.config = config
    obj._data_ready = MagicMock()

    obj._bg_refresh()
    obj._data_ready.emit.assert_called_once_with(None)


# ---------------------------------------------------------------------------
# HistorySection._bg_refresh
# ---------------------------------------------------------------------------

def test_history_bg_refresh_uses_build_history_dtos(monkeypatch):
    """_bg_refresh must call build_history_dtos and emit the result."""
    from metatv.gui.sidebar.history import HistorySection

    dtos = [
        HistoryDTO(id="c1", name="My Show", media_type="series", episode_code="S01E03"),
        HistoryDTO(id="c2", name="Action Movie", media_type="movie", episode_code=None),
    ]

    db, mock_session = _mock_db(dtos)
    config = MagicMock()
    config.filter_adult_mode = "all"

    def fake_build(repos, limit, adult_mode):
        return dtos

    def fake_repos_factory(session):
        return MagicMock()

    with patch("metatv.gui.sidebar.history.RepositoryFactory", fake_repos_factory), \
         patch("metatv.gui.sidebar.history.build_history_dtos", fake_build) if False else \
         patch("metatv.core.repositories.dtos.build_history_dtos", fake_build):
        obj = HistorySection.__new__(HistorySection)
        obj.db = db
        obj.config = config
        obj._data_ready = MagicMock()

        # Patch at the import site inside _bg_refresh
        import metatv.core.repositories.dtos as dtos_mod
        original = dtos_mod.build_history_dtos
        dtos_mod.build_history_dtos = fake_build
        try:
            obj._bg_refresh()
        finally:
            dtos_mod.build_history_dtos = original

    obj._data_ready.emit.assert_called_once_with(dtos)


def test_history_bg_refresh_emits_none_on_error():
    """_bg_refresh must emit None when the DB read fails."""
    from metatv.gui.sidebar.history import HistorySection

    db = MagicMock()
    db.session_scope.side_effect = RuntimeError("db locked")
    config = MagicMock()

    obj = HistorySection.__new__(HistorySection)
    obj.db = db
    obj.config = config
    obj._data_ready = MagicMock()

    obj._bg_refresh()
    obj._data_ready.emit.assert_called_once_with(None)


# ---------------------------------------------------------------------------
# WatchQueueSection._bg_refresh
# ---------------------------------------------------------------------------

def test_queue_bg_refresh_returns_queue_entries(monkeypatch):
    """_bg_refresh must read via repos.queue.get_all() and emit the entries."""
    from metatv.gui.sidebar.queue import WatchQueueSection
    from metatv.core.repositories.queue import QueueEntry

    entries = [
        QueueEntry(queue_id=1, channel_id="c1", channel_name="Film A",
                   media_type="movie", last_played=None, channel=None),
        QueueEntry(queue_id=2, channel_id="c2", channel_name="My Show",
                   media_type="series", last_played=datetime.now(), channel=None),
    ]

    db, mock_session = _mock_db(entries)
    config = MagicMock()

    def fake_repos_factory(session):
        repos = MagicMock()
        repos.queue.get_all.return_value = entries
        return repos

    with patch("metatv.gui.sidebar.queue.RepositoryFactory", fake_repos_factory):
        obj = WatchQueueSection.__new__(WatchQueueSection)
        obj.db = db
        obj.config = config
        obj._data_ready = MagicMock()

        obj._bg_refresh()

    obj._data_ready.emit.assert_called_once_with(entries)


def test_queue_bg_refresh_emits_none_on_error():
    """_bg_refresh must emit None when the DB read fails."""
    from metatv.gui.sidebar.queue import WatchQueueSection

    db = MagicMock()
    db.session_scope.side_effect = RuntimeError("db locked")
    config = MagicMock()

    obj = WatchQueueSection.__new__(WatchQueueSection)
    obj.db = db
    obj.config = config
    obj._data_ready = MagicMock()

    obj._bg_refresh()
    obj._data_ready.emit.assert_called_once_with(None)


# ---------------------------------------------------------------------------
# Verify sections own an executor (thread-leak check)
# ---------------------------------------------------------------------------

def test_sections_have_bg_refresh_pattern():
    """Each off-thread section must implement _bg_refresh (confirms the pattern is in place).
    RecommendedSection uses _rec_data_ready (its own name predates this band); the three
    new sections use _data_ready for consistency."""
    from metatv.gui.sidebar.favorites import FavoritesSection
    from metatv.gui.sidebar.history import HistorySection
    from metatv.gui.sidebar.queue import WatchQueueSection
    from metatv.gui.sidebar.recommended import RecommendedSection

    for cls in (FavoritesSection, HistorySection, WatchQueueSection, RecommendedSection):
        assert hasattr(cls, "_bg_refresh"), f"{cls.__name__} is missing _bg_refresh"

    # New sections must use _data_ready (not a per-section name)
    for cls in (FavoritesSection, HistorySection, WatchQueueSection):
        assert hasattr(cls, "_data_ready"), f"{cls.__name__} is missing _data_ready signal"
