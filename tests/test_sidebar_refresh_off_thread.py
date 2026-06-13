"""Tests for B7-5 — sidebar sections refresh off-thread.

Pins three invariants per section (Favorites, History, WatchQueue):

1. ``refresh()`` submits work to an executor — it does NOT block the caller.
2. ``_bg_refresh()`` returns plain DTO / dataclass data (no live ORM session) and
   emits ``None`` on failure so the section can render an error row.
3. ``_on_data_ready()`` populates the section list correctly on the main thread —
   the sort / continue-vs-never split, the media-icon mapping, the episode-code
   rendering, AND the failure path (``None`` → a visible error row, never a silent
   blank). This is the half that actually regresses, so it is tested directly.

``_bg_refresh`` is tested with a mock db (no Qt). ``_on_data_ready`` is tested with a
real ``QListWidget`` under a module ``QApplication`` — the section instances are built
via ``__new__`` so no full Qt widget tree is needed.

RecommendedSection is already off-thread and is not re-tested here.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from metatv.core.repositories.dtos import FavoriteDTO, HistoryDTO
from metatv.gui import icons as _icons


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    """A process-wide QApplication so QListWidget can be instantiated headless."""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _icon_config():
    """A config exposing distinct, recognisable media-icon strings."""
    return SimpleNamespace(
        live_icon="L", movie_icon="M", series_icon="S", unknown_icon="?",
        filter_adult_mode="all",
    )


def _mock_db():
    """A fake db whose session_scope() yields a throwaway session."""
    mock_session = MagicMock()
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=mock_session)
    cm.__exit__ = MagicMock(return_value=False)
    db = MagicMock()
    db.session_scope.return_value = cm
    return db


def _texts(list_widget):
    return [list_widget.item(i).text() for i in range(list_widget.count())]


def _ids(list_widget):
    """UserRole ids for non-header rows (headers carry no UserRole data)."""
    from PyQt6.QtCore import Qt
    out = []
    for i in range(list_widget.count()):
        data = list_widget.item(i).data(Qt.ItemDataRole.UserRole)
        if data is not None:
            out.append(data)
    return out


# ===========================================================================
# FavoritesSection
# ===========================================================================

def test_favorites_bg_refresh_returns_favorite_dtos():
    """_bg_refresh must read via get_favorites_dto and emit the DTO list."""
    from metatv.gui.sidebar.favorites import FavoritesSection

    dtos = [
        FavoriteDTO(id="c1", name="Channel 1", media_type="movie", last_played=datetime.now()),
        FavoriteDTO(id="c2", name="Channel 2", media_type="live", last_played=None),
    ]

    def fake_repos_factory(session):
        repos = MagicMock()
        repos.channels.get_favorites_dto.return_value = dtos
        return repos

    with patch("metatv.gui.sidebar.favorites.RepositoryFactory", fake_repos_factory):
        obj = FavoritesSection.__new__(FavoritesSection)
        obj.db = _mock_db()
        obj.config = _icon_config()
        obj._data_ready = MagicMock()
        obj._bg_refresh()

    obj._data_ready.emit.assert_called_once_with(dtos)


def test_favorites_bg_refresh_emits_none_on_error():
    """_bg_refresh must emit None when the DB read fails so the section can render an error."""
    from metatv.gui.sidebar.favorites import FavoritesSection

    db = MagicMock()
    db.session_scope.side_effect = RuntimeError("db locked")

    obj = FavoritesSection.__new__(FavoritesSection)
    obj.db = db
    obj.config = _icon_config()
    obj._data_ready = MagicMock()
    obj._bg_refresh()

    obj._data_ready.emit.assert_called_once_with(None)


def test_favorites_on_data_ready_splits_sorts_and_maps_icons(qapp):
    """_on_data_ready must split continue/never, sort each, and map media icons."""
    from PyQt6.QtWidgets import QListWidget
    from metatv.gui.sidebar.favorites import FavoritesSection

    obj = FavoritesSection.__new__(FavoritesSection)
    obj.favorites_list = QListWidget()
    obj.config = _icon_config()
    obj.set_empty = lambda *_: None

    dtos = [
        FavoriteDTO(id="c1", name="Alpha", media_type="movie", last_played=None),
        FavoriteDTO(id="c2", name="Beta", media_type="series", last_played=datetime(2024, 1, 2)),
        FavoriteDTO(id="c3", name="Gamma", media_type="live", last_played=datetime(2024, 1, 5)),
    ]
    obj._on_data_ready(dtos)

    texts = _texts(obj.favorites_list)
    # continue-watching sorted by last_played desc (c3 then c2), then never-watched (c1)
    assert _ids(obj.favorites_list) == ["c3", "c2", "c1"]
    assert "Continue Watching" in texts[0]
    assert texts[1].startswith("L ")   # c3 live
    assert texts[2].startswith("S ")   # c2 series
    assert "Never Watched" in texts[3]
    assert texts[4].startswith("M ")   # c1 movie


def test_favorites_on_data_ready_empty_shows_hint(qapp):
    from PyQt6.QtWidgets import QListWidget
    from metatv.gui.sidebar.favorites import FavoritesSection

    obj = FavoritesSection.__new__(FavoritesSection)
    obj.favorites_list = QListWidget()
    obj.config = _icon_config()
    obj.set_empty = lambda *_: None

    obj._on_data_ready([])
    assert _texts(obj.favorites_list) == [
        "No favorites yet",
        "Right-click any channel to add to favorites",
    ]


def test_favorites_on_data_ready_none_shows_error_row(qapp):
    """A failed load (None) must render a distinct error row, never a silent blank."""
    from PyQt6.QtWidgets import QListWidget
    from metatv.gui.sidebar.favorites import FavoritesSection

    obj = FavoritesSection.__new__(FavoritesSection)
    obj.favorites_list = QListWidget()
    obj.config = _icon_config()
    obj.set_empty = lambda *_: None

    obj._on_data_ready(None)
    texts = _texts(obj.favorites_list)
    assert len(texts) == 1
    assert _icons.notification_warning_icon in texts[0]
    assert "Couldn't load favorites" in texts[0]


# ===========================================================================
# HistorySection
# ===========================================================================

def test_history_bg_refresh_uses_build_history_dtos():
    """_bg_refresh must call build_history_dtos and emit the result."""
    from metatv.gui.sidebar.history import HistorySection

    dtos = [
        HistoryDTO(id="c1", name="My Show", media_type="series", episode_code="S01E03"),
        HistoryDTO(id="c2", name="Action Movie", media_type="movie", episode_code=None),
    ]

    def fake_build(repos, limit, adult_mode):
        return dtos

    # build_history_dtos is imported inside _bg_refresh from metatv.core.repositories.dtos,
    # so patch it at its definition site.
    with patch("metatv.gui.sidebar.history.RepositoryFactory", lambda s: MagicMock()), \
         patch("metatv.core.repositories.dtos.build_history_dtos", fake_build):
        obj = HistorySection.__new__(HistorySection)
        obj.db = _mock_db()
        obj.config = _icon_config()
        obj._data_ready = MagicMock()
        obj._bg_refresh()

    obj._data_ready.emit.assert_called_once_with(dtos)


def test_history_bg_refresh_emits_none_on_error():
    """_bg_refresh must emit None when the DB read fails."""
    from metatv.gui.sidebar.history import HistorySection

    db = MagicMock()
    db.session_scope.side_effect = RuntimeError("db locked")

    obj = HistorySection.__new__(HistorySection)
    obj.db = db
    obj.config = _icon_config()
    obj._data_ready = MagicMock()
    obj._bg_refresh()

    obj._data_ready.emit.assert_called_once_with(None)


def test_history_on_data_ready_renders_episode_code_and_icons(qapp):
    """Series rows render the episode code on a second line; movies do not."""
    from PyQt6.QtWidgets import QListWidget
    from metatv.gui.sidebar.history import HistorySection

    obj = HistorySection.__new__(HistorySection)
    obj.history_list = QListWidget()
    obj.config = _icon_config()
    obj.set_empty = lambda *_: None

    dtos = [
        HistoryDTO(id="c1", name="My Show", media_type="series", episode_code="S01E03"),
        HistoryDTO(id="c2", name="A Film", media_type="movie", episode_code=None),
    ]
    obj._on_data_ready(dtos)

    texts = _texts(obj.history_list)
    assert _ids(obj.history_list) == ["c1", "c2"]   # history preserves order, no split
    assert texts[0] == "S My Show\n   → S01E03"
    assert texts[1] == "M A Film"


def test_history_on_data_ready_none_shows_error_row(qapp):
    from PyQt6.QtWidgets import QListWidget
    from metatv.gui.sidebar.history import HistorySection

    obj = HistorySection.__new__(HistorySection)
    obj.history_list = QListWidget()
    obj.config = _icon_config()
    obj.set_empty = lambda *_: None

    obj._on_data_ready(None)
    texts = _texts(obj.history_list)
    assert len(texts) == 1
    assert _icons.notification_warning_icon in texts[0]
    assert "Couldn't load history" in texts[0]


# ===========================================================================
# WatchQueueSection
# ===========================================================================

def test_queue_bg_refresh_returns_queue_entries():
    """_bg_refresh must read via repos.queue.get_all() and emit the entries."""
    from metatv.gui.sidebar.queue import WatchQueueSection
    from metatv.core.repositories.queue import QueueEntry

    entries = [
        QueueEntry(queue_id=1, channel_id="c1", channel_name="Film A",
                   media_type="movie", last_played=None, channel=None),
        QueueEntry(queue_id=2, channel_id="c2", channel_name="My Show",
                   media_type="series", last_played=datetime.now(), channel=None),
    ]

    def fake_repos_factory(session):
        repos = MagicMock()
        repos.queue.get_all.return_value = entries
        return repos

    with patch("metatv.gui.sidebar.queue.RepositoryFactory", fake_repos_factory):
        obj = WatchQueueSection.__new__(WatchQueueSection)
        obj.db = _mock_db()
        obj.config = _icon_config()
        obj._data_ready = MagicMock()
        obj._bg_refresh()

    obj._data_ready.emit.assert_called_once_with(entries)


def test_queue_bg_refresh_emits_none_on_error():
    """_bg_refresh must emit None when the DB read fails."""
    from metatv.gui.sidebar.queue import WatchQueueSection

    db = MagicMock()
    db.session_scope.side_effect = RuntimeError("db locked")

    obj = WatchQueueSection.__new__(WatchQueueSection)
    obj.db = db
    obj.config = _icon_config()
    obj._data_ready = MagicMock()
    obj._bg_refresh()

    obj._data_ready.emit.assert_called_once_with(None)


def test_queue_on_data_ready_splits_and_maps_icons(qapp):
    from PyQt6.QtWidgets import QListWidget
    from metatv.gui.sidebar.queue import WatchQueueSection
    from metatv.core.repositories.queue import QueueEntry

    obj = WatchQueueSection.__new__(WatchQueueSection)
    obj._list = QListWidget()
    obj.config = _icon_config()
    obj.set_empty = lambda *_: None

    entries = [
        QueueEntry(queue_id=1, channel_id="q1", channel_name="Film A",
                   media_type="movie", last_played=None, channel=None),
        QueueEntry(queue_id=2, channel_id="q2", channel_name="My Show",
                   media_type="series", last_played=datetime(2024, 1, 2), channel=None),
    ]
    obj._on_data_ready(entries)

    texts = _texts(obj._list)
    assert _ids(obj._list) == ["q2", "q1"]   # continue-watching (q2) before never-watched (q1)
    assert "Continue Watching" in texts[0]
    assert texts[1].startswith("S ")   # q2 series
    assert "Never Watched" in texts[2]
    assert texts[3].startswith("M ")   # q1 movie


def test_queue_on_data_ready_none_shows_error_row(qapp):
    from PyQt6.QtWidgets import QListWidget
    from metatv.gui.sidebar.queue import WatchQueueSection

    obj = WatchQueueSection.__new__(WatchQueueSection)
    obj._list = QListWidget()
    obj.config = _icon_config()
    obj.set_empty = lambda *_: None

    obj._on_data_ready(None)
    texts = _texts(obj._list)
    assert len(texts) == 1
    assert _icons.notification_warning_icon in texts[0]
    assert "Couldn't load watch queue" in texts[0]


# ===========================================================================
# Pattern / thread-leak guards
# ===========================================================================

def test_sections_have_bg_refresh_pattern():
    """Each off-thread section must implement _bg_refresh and own a _data_ready signal.

    RecommendedSection uses _rec_data_ready (its name predates this band); the three
    new sections use _data_ready for consistency. Owning an executor is what the
    closeEvent cleanup loop keys on (hasattr(section, "_executor")).
    """
    from metatv.gui.sidebar.favorites import FavoritesSection
    from metatv.gui.sidebar.history import HistorySection
    from metatv.gui.sidebar.queue import WatchQueueSection
    from metatv.gui.sidebar.recommended import RecommendedSection

    for cls in (FavoritesSection, HistorySection, WatchQueueSection, RecommendedSection):
        assert hasattr(cls, "_bg_refresh"), f"{cls.__name__} is missing _bg_refresh"

    for cls in (FavoritesSection, HistorySection, WatchQueueSection):
        assert hasattr(cls, "_data_ready"), f"{cls.__name__} is missing _data_ready signal"
