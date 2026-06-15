"""Tests for PR-4 — unavailable engaged content (Watch Queue + Favorites).

Behavioral tests only — no shape assertions.

Repo tests:
- get_all(hidden) and get_favorites_dto(hidden_provider_ids) annotate availability
  and populate search_title correctly.
- clear_unavailable / clear_unavailable_favorites remove exactly the hidden-source
  (and orphaned, for queue) entries and return the right count; available entries survive.

Widget tests (headless QApplication + real QListWidget):
- _populate_rows renders rows in the original order, dims unavailable items
  (correct foreground color + tooltip), stores item data, and sets has_unavailable.
- Double-click on an unavailable item emits searchRequested with the title.
- Double-click on an available item emits the play signal.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from metatv.core.database import Base, ChannelDB, WatchQueueDB, ProviderDB
from metatv.core.repositories.queue import WatchQueueRepository, QueueEntry
from metatv.core.repositories.channel import ChannelRepository
from metatv.core.repositories.dtos import FavoriteDTO


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    """Module-wide headless QApplication."""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def session():
    """Per-test in-memory SQLite session with all tables created."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()
    engine.dispose()


def _provider(session, pid: str, is_active: bool = True) -> ProviderDB:
    p = ProviderDB(id=pid, name=pid, type="xtream", url="http://x", is_active=is_active)
    session.add(p)
    session.flush()
    return p


def _channel(session, pid: str, name: str = "Chan", **kwargs) -> ChannelDB:
    ch = ChannelDB(
        id=str(uuid.uuid4()),
        source_id=str(uuid.uuid4()),
        provider_id=pid,
        name=name,
        media_type="movie",
        **kwargs,
    )
    session.add(ch)
    session.flush()
    return ch


def _queue_row(session, channel_id: str, channel_name: str, pos: int = 0,
               source_id: str = "") -> WatchQueueDB:
    row = WatchQueueDB(
        channel_id=channel_id,
        channel_name=channel_name,
        media_type="movie",
        source_id=source_id,
        position=pos,
    )
    session.add(row)
    session.flush()
    return row


def _icon_config():
    return SimpleNamespace(
        live_icon="L", movie_icon="M", series_icon="S", unknown_icon="?",
        filter_adult_mode="all",
        watched_icon="W", delete_icon="X", queue_icon="Q",
        favorite_icon="★", collapse_icon="v",
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


# ---------------------------------------------------------------------------
# Repository tests — WatchQueueRepository.get_all with hidden_provider_ids
# ---------------------------------------------------------------------------

def test_queue_get_all_marks_hidden_provider_unavailable(session):
    """Entries on a hidden provider get available=False."""
    _provider(session, "active_p")
    _provider(session, "hidden_p", is_active=False)
    ch_active = _channel(session, "active_p", name="Active Chan", detected_title="Active Title")
    ch_hidden = _channel(session, "hidden_p", name="Hidden Chan", detected_title="Hidden Title")
    _queue_row(session, ch_active.id, "Active Chan", pos=0)
    _queue_row(session, ch_hidden.id, "Hidden Chan", pos=1)
    session.commit()

    repo = WatchQueueRepository(session)
    entries = repo.get_all(hidden_provider_ids={"hidden_p"})

    active_entry = next(e for e in entries if e.channel_id == ch_active.id)
    hidden_entry = next(e for e in entries if e.channel_id == ch_hidden.id)

    assert active_entry.available is True
    assert active_entry.provider_id == "active_p"
    assert active_entry.search_title == "Active Title"

    assert hidden_entry.available is False
    assert hidden_entry.provider_id == "hidden_p"
    assert hidden_entry.search_title == "Hidden Title"


def test_queue_get_all_orphan_is_unavailable(session):
    """Orphaned entries (no matching ChannelDB) are always unavailable."""
    orphan_id = str(uuid.uuid4())
    _queue_row(session, orphan_id, "Gone Channel", pos=0)
    session.commit()

    repo = WatchQueueRepository(session)
    entries = repo.get_all(hidden_provider_ids=set())

    assert len(entries) == 1
    assert entries[0].available is False
    assert entries[0].provider_id is None
    assert entries[0].search_title == "Gone Channel"  # falls back to stored name


def test_queue_get_all_no_hidden_set_all_available(session):
    """When hidden_provider_ids is None, all non-orphaned entries are available."""
    _provider(session, "p1")
    ch = _channel(session, "p1", name="Good Chan")
    _queue_row(session, ch.id, "Good Chan")
    session.commit()

    repo = WatchQueueRepository(session)
    entries = repo.get_all()  # no hidden set

    assert entries[0].available is True


def test_queue_get_all_search_title_falls_back_to_name(session):
    """When detected_title is empty, search_title uses the channel name."""
    _provider(session, "p1")
    ch = _channel(session, "p1", name="Full Name", detected_title=None)
    _queue_row(session, ch.id, "Full Name")
    session.commit()

    repo = WatchQueueRepository(session)
    entries = repo.get_all(hidden_provider_ids=set())
    assert entries[0].search_title == "Full Name"


# ---------------------------------------------------------------------------
# Repository tests — WatchQueueRepository.clear_unavailable
# ---------------------------------------------------------------------------

def test_clear_unavailable_removes_hidden_and_orphans_keeps_active(session):
    """clear_unavailable removes hidden-provider + orphaned entries; keeps active."""
    _provider(session, "active_p")
    _provider(session, "hidden_p", is_active=False)
    ch_active = _channel(session, "active_p", name="Stay")
    ch_hidden = _channel(session, "hidden_p", name="Go")
    orphan_id = str(uuid.uuid4())

    _queue_row(session, ch_active.id, "Stay",       pos=0)
    _queue_row(session, ch_hidden.id, "Go",         pos=1)
    _queue_row(session, orphan_id,    "Ghost",      pos=2)
    session.commit()

    repo = WatchQueueRepository(session)
    count = repo.clear_unavailable({"hidden_p"})
    session.commit()

    assert count == 2  # hidden + orphan removed
    remaining = session.query(WatchQueueDB).all()
    assert len(remaining) == 1
    assert remaining[0].channel_id == ch_active.id


def test_clear_unavailable_returns_zero_when_nothing_to_remove(session):
    """Returns 0 when all entries are on active providers."""
    _provider(session, "p")
    ch = _channel(session, "p")
    _queue_row(session, ch.id, "Chan")
    session.commit()

    repo = WatchQueueRepository(session)
    count = repo.clear_unavailable({"other_hidden"})
    assert count == 0


# ---------------------------------------------------------------------------
# Repository tests — ChannelRepository.get_favorites_dto with hidden_provider_ids
# ---------------------------------------------------------------------------

def test_favorites_dto_marks_hidden_provider_unavailable(session):
    """FavoriteDTO.available is False for channels on a hidden provider."""
    _provider(session, "active_p")
    _provider(session, "hidden_p", is_active=False)
    _channel(session, "active_p", name="Active Fave", is_favorite=True,
             detected_title="Active Title")
    _channel(session, "hidden_p", name="Hidden Fave", is_favorite=True,
             detected_title="Hidden Title")
    session.commit()

    repo = ChannelRepository(session)
    dtos = repo.get_favorites_dto(hidden_provider_ids={"hidden_p"})

    active_dto = next(d for d in dtos if d.name == "Active Fave")
    hidden_dto = next(d for d in dtos if d.name == "Hidden Fave")

    assert active_dto.available is True
    assert active_dto.search_title == "Active Title"

    assert hidden_dto.available is False
    assert hidden_dto.search_title == "Hidden Title"


def test_favorites_dto_search_title_falls_back_to_name(session):
    """search_title uses channel name when detected_title is empty."""
    _provider(session, "p")
    _channel(session, "p", name="Full Name", is_favorite=True, detected_title=None)
    session.commit()

    repo = ChannelRepository(session)
    dtos = repo.get_favorites_dto(hidden_provider_ids=set())
    assert dtos[0].search_title == "Full Name"


def test_favorites_dto_no_hidden_set_all_available(session):
    """When hidden_provider_ids is None, all favorites are available."""
    _provider(session, "p")
    _channel(session, "p", name="Fave", is_favorite=True)
    session.commit()

    repo = ChannelRepository(session)
    dtos = repo.get_favorites_dto()  # no hidden set
    assert dtos[0].available is True


# ---------------------------------------------------------------------------
# Repository tests — ChannelRepository.clear_unavailable_favorites
# ---------------------------------------------------------------------------

def test_clear_unavailable_favorites_unfavorites_hidden_keeps_active(session):
    """clear_unavailable_favorites un-favorites hidden-provider channels."""
    _provider(session, "active_p")
    _provider(session, "hidden_p", is_active=False)
    ch_active = _channel(session, "active_p", name="Stay", is_favorite=True)
    ch_hidden = _channel(session, "hidden_p", name="Go",   is_favorite=True)
    session.commit()

    repo = ChannelRepository(session)
    count = repo.clear_unavailable_favorites({"hidden_p"})
    session.commit()

    assert count == 1
    session.refresh(ch_active)
    session.refresh(ch_hidden)
    assert ch_active.is_favorite is True
    assert ch_hidden.is_favorite is False


def test_clear_unavailable_favorites_returns_zero_when_none(session):
    """Returns 0 when no favorites are on hidden providers."""
    _provider(session, "p")
    _channel(session, "p", is_favorite=True)
    session.commit()

    repo = ChannelRepository(session)
    count = repo.clear_unavailable_favorites({"other"})
    assert count == 0


# ---------------------------------------------------------------------------
# Widget tests — WatchQueueSection._populate_rows
# ---------------------------------------------------------------------------

def test_queue_populate_rows_dims_unavailable_items(qapp):
    """Unavailable rows get the muted foreground color and the tooltip."""
    from PyQt6.QtWidgets import QListWidget
    from PyQt6.QtCore import Qt
    from metatv.gui import theme as _theme
    from metatv.gui.sidebar.queue import WatchQueueSection, _ROLE_AVAILABLE, _ROLE_SEARCH_TITLE

    obj = WatchQueueSection.__new__(WatchQueueSection)
    obj._list = QListWidget()
    obj.config = _icon_config()
    obj.set_empty = lambda *_: None
    obj._has_unavailable = False

    entries = [
        QueueEntry(queue_id=1, channel_id="c1", channel_name="Available",
                   media_type="movie", last_played=None, channel=None,
                   available=True, search_title="Available", provider_id="p1"),
        QueueEntry(queue_id=2, channel_id="c2", channel_name="Gone Chan",
                   media_type="movie", last_played=None, channel=None,
                   available=False, search_title="Gone Title", provider_id="p2"),
    ]
    obj._populate_rows(entries)

    # has_unavailable flag updated
    assert obj._has_unavailable is True

    # Order preserved: Available first, Gone Chan second (both in "Never Watched")
    ids = []
    for i in range(obj._list.count()):
        item = obj._list.item(i)
        d = item.data(Qt.ItemDataRole.UserRole)
        if d:
            ids.append(d)
    assert ids == ["c1", "c2"]

    # Find the unavailable item
    unavail_item = None
    for i in range(obj._list.count()):
        item = obj._list.item(i)
        if item.data(Qt.ItemDataRole.UserRole) == "c2":
            unavail_item = item
            break

    assert unavail_item is not None
    # Foreground is the muted color
    from PyQt6.QtGui import QColor
    assert unavail_item.foreground().color() == QColor(_theme.COLOR_MUTED)
    # Tooltip set
    assert "unavailable" in unavail_item.toolTip().lower()
    # Item data
    assert unavail_item.data(_ROLE_AVAILABLE) is False
    assert unavail_item.data(_ROLE_SEARCH_TITLE) == "Gone Title"

    # Available item is NOT dimmed — its foreground is not the muted color
    avail_item = None
    for i in range(obj._list.count()):
        item = obj._list.item(i)
        if item.data(Qt.ItemDataRole.UserRole) == "c1":
            avail_item = item
            break
    assert avail_item is not None
    assert avail_item.data(_ROLE_AVAILABLE) is True


def test_queue_populate_rows_has_unavailable_false_when_all_available(qapp):
    """_has_unavailable is False when all entries are available."""
    from PyQt6.QtWidgets import QListWidget
    from metatv.gui.sidebar.queue import WatchQueueSection

    obj = WatchQueueSection.__new__(WatchQueueSection)
    obj._list = QListWidget()
    obj.config = _icon_config()
    obj.set_empty = lambda *_: None
    obj._has_unavailable = False

    entries = [
        QueueEntry(queue_id=1, channel_id="c1", channel_name="Chan",
                   media_type="movie", last_played=None, channel=None,
                   available=True, search_title="Chan", provider_id="p"),
    ]
    obj._populate_rows(entries)
    assert obj._has_unavailable is False


def test_queue_double_click_unavailable_emits_search_requested(qapp):
    """Double-clicking an unavailable item emits searchRequested, not itemDoubleClicked."""
    from PyQt6.QtWidgets import QListWidget, QListWidgetItem
    from PyQt6.QtCore import Qt
    from metatv.gui.sidebar.queue import WatchQueueSection, _ROLE_AVAILABLE, _ROLE_SEARCH_TITLE

    obj = WatchQueueSection.__new__(WatchQueueSection)
    obj._list = QListWidget()
    obj.config = _icon_config()
    obj.set_empty = lambda *_: None
    obj._has_unavailable = False

    # Build the signals manually (they're class-level pyqtSignals — need real instance)
    # Use a fresh WatchQueueSection to get the pyqtSignal instances but bypass __init__
    from PyQt6.QtCore import pyqtSignal, QObject
    search_emitted = []
    play_emitted = []

    obj.searchRequested = MagicMock()
    obj.searchRequested.emit = lambda t: search_emitted.append(t)
    obj.itemDoubleClicked = MagicMock()
    obj.itemDoubleClicked.emit = lambda cid: play_emitted.append(cid)

    item = QListWidgetItem("M Gone Title")
    item.setData(Qt.ItemDataRole.UserRole, "c_unavail")
    item.setData(_ROLE_AVAILABLE, False)
    item.setData(_ROLE_SEARCH_TITLE, "Gone Title")

    obj._on_double_click(item)

    assert search_emitted == ["Gone Title"]
    assert play_emitted == []


def test_queue_double_click_available_emits_play(qapp):
    """Double-clicking an available item emits itemDoubleClicked, not searchRequested."""
    from PyQt6.QtWidgets import QListWidget, QListWidgetItem
    from PyQt6.QtCore import Qt
    from metatv.gui.sidebar.queue import WatchQueueSection, _ROLE_AVAILABLE, _ROLE_SEARCH_TITLE

    obj = WatchQueueSection.__new__(WatchQueueSection)
    obj._list = QListWidget()
    obj.config = _icon_config()
    obj.set_empty = lambda *_: None
    obj._has_unavailable = False

    search_emitted = []
    play_emitted = []

    obj.searchRequested = MagicMock()
    obj.searchRequested.emit = lambda t: search_emitted.append(t)
    obj.itemDoubleClicked = MagicMock()
    obj.itemDoubleClicked.emit = lambda cid: play_emitted.append(cid)

    item = QListWidgetItem("M Available Chan")
    item.setData(Qt.ItemDataRole.UserRole, "c_avail")
    item.setData(_ROLE_AVAILABLE, True)
    item.setData(_ROLE_SEARCH_TITLE, "Available")

    obj._on_double_click(item)

    assert play_emitted == ["c_avail"]
    assert search_emitted == []


# ---------------------------------------------------------------------------
# Widget tests — FavoritesSection._populate_rows
# ---------------------------------------------------------------------------

def test_favorites_populate_rows_dims_unavailable_items(qapp):
    """Unavailable favorites are dimmed and carry item data."""
    from PyQt6.QtWidgets import QListWidget
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QColor
    from metatv.gui import theme as _theme
    from metatv.gui.sidebar.favorites import FavoritesSection, _ROLE_AVAILABLE, _ROLE_SEARCH_TITLE

    obj = FavoritesSection.__new__(FavoritesSection)
    obj.favorites_list = QListWidget()
    obj.config = _icon_config()
    obj.set_empty = lambda *_: None
    obj._has_unavailable = False

    dtos = [
        FavoriteDTO(id="f1", name="Alpha", media_type="movie", last_played=None,
                    available=True, search_title="Alpha", provider_id="p1"),
        FavoriteDTO(id="f2", name="Beta",  media_type="movie", last_played=None,
                    available=False, search_title="Beta Title", provider_id="p2"),
    ]
    obj._populate_rows(dtos)

    assert obj._has_unavailable is True

    # Find unavailable item
    unavail_item = None
    for i in range(obj.favorites_list.count()):
        item = obj.favorites_list.item(i)
        if item.data(Qt.ItemDataRole.UserRole) == "f2":
            unavail_item = item
            break

    assert unavail_item is not None
    assert unavail_item.foreground().color() == QColor(_theme.COLOR_MUTED)
    assert "unavailable" in unavail_item.toolTip().lower()
    assert unavail_item.data(_ROLE_AVAILABLE) is False
    assert unavail_item.data(_ROLE_SEARCH_TITLE) == "Beta Title"


def test_favorites_populate_rows_order_preserved(qapp):
    """_populate_rows keeps continue-watching sorted desc by last_played, then never-watched alpha."""
    from PyQt6.QtWidgets import QListWidget
    from PyQt6.QtCore import Qt
    from metatv.gui.sidebar.favorites import FavoritesSection

    obj = FavoritesSection.__new__(FavoritesSection)
    obj.favorites_list = QListWidget()
    obj.config = _icon_config()
    obj.set_empty = lambda *_: None
    obj._has_unavailable = False

    ts1 = datetime(2024, 1, 1)
    ts2 = datetime(2024, 3, 1)
    dtos = [
        FavoriteDTO(id="f_c", name="Gamma", media_type="movie", last_played=None,
                    available=True, search_title="Gamma", provider_id="p"),
        FavoriteDTO(id="f_a", name="Alpha", media_type="movie", last_played=ts1,
                    available=True, search_title="Alpha", provider_id="p"),
        FavoriteDTO(id="f_b", name="Beta",  media_type="movie", last_played=ts2,
                    available=False, search_title="Beta", provider_id="p"),
    ]
    obj._populate_rows(dtos)

    ids = []
    for i in range(obj.favorites_list.count()):
        d = obj.favorites_list.item(i).data(Qt.ItemDataRole.UserRole)
        if d:
            ids.append(d)

    # Continue Watching: ts2 (f_b) before ts1 (f_a); Never Watched: f_c (alpha)
    assert ids == ["f_b", "f_a", "f_c"]


def test_favorites_double_click_unavailable_emits_search_requested(qapp):
    """Double-clicking an unavailable favorite emits searchRequested."""
    from PyQt6.QtWidgets import QListWidget, QListWidgetItem
    from PyQt6.QtCore import Qt
    from metatv.gui.sidebar.favorites import FavoritesSection, _ROLE_AVAILABLE, _ROLE_SEARCH_TITLE

    obj = FavoritesSection.__new__(FavoritesSection)
    obj.favorites_list = QListWidget()
    obj.config = _icon_config()
    obj.set_empty = lambda *_: None
    obj._has_unavailable = False

    search_emitted = []
    play_emitted = []

    obj.searchRequested = MagicMock()
    obj.searchRequested.emit = lambda t: search_emitted.append(t)
    obj.favoriteClicked = MagicMock()
    obj.favoriteClicked.emit = lambda cid: play_emitted.append(cid)

    item = QListWidgetItem("M Gone")
    item.setData(Qt.ItemDataRole.UserRole, "f_gone")
    item.setData(_ROLE_AVAILABLE, False)
    item.setData(_ROLE_SEARCH_TITLE, "Gone Title")

    obj.on_favorite_clicked(item)

    assert search_emitted == ["Gone Title"]
    assert play_emitted == []


def test_favorites_double_click_available_emits_favorite_clicked(qapp):
    """Double-clicking an available favorite emits favoriteClicked."""
    from PyQt6.QtWidgets import QListWidget, QListWidgetItem
    from PyQt6.QtCore import Qt
    from metatv.gui.sidebar.favorites import FavoritesSection, _ROLE_AVAILABLE, _ROLE_SEARCH_TITLE

    obj = FavoritesSection.__new__(FavoritesSection)
    obj.favorites_list = QListWidget()
    obj.config = _icon_config()
    obj.set_empty = lambda *_: None
    obj._has_unavailable = False

    search_emitted = []
    play_emitted = []

    obj.searchRequested = MagicMock()
    obj.searchRequested.emit = lambda t: search_emitted.append(t)
    obj.favoriteClicked = MagicMock()
    obj.favoriteClicked.emit = lambda cid: play_emitted.append(cid)

    item = QListWidgetItem("M Good Chan")
    item.setData(Qt.ItemDataRole.UserRole, "f_avail")
    item.setData(_ROLE_AVAILABLE, True)
    item.setData(_ROLE_SEARCH_TITLE, "Good Chan")

    obj.on_favorite_clicked(item)

    assert play_emitted == ["f_avail"]
    assert search_emitted == []
