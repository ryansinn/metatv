"""Characterization tests for P1-2: favorite toggle deduplication.

T1-2 from REFACTOR_PLAN. Pins that both toggle_favorite() and
toggle_favorite_by_id() flip is_favorite, persist it, and post the
right status message. Guards the _apply_favorite_toggle() extraction.
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from metatv.core.database import Base, ChannelDB
from metatv.core.repositories.channel import ChannelRepository


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def engine():
    e = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(e)
    yield e
    e.dispose()


@pytest.fixture()
def db_session(engine):
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


@pytest.fixture()
def channel(db_session):
    ch = ChannelDB(
        id=str(uuid.uuid4()),
        source_id="999",
        provider_id="prov1",
        name="Test Channel",
        media_type="movie",
        is_favorite=False,
    )
    db_session.add(ch)
    db_session.commit()
    return ch


# ---------------------------------------------------------------------------
# Repository-level pin: toggle_favorite flips the DB flag
# ---------------------------------------------------------------------------

def test_toggle_favorite_repo_flips_to_true(db_session, channel):
    repo = ChannelRepository(db_session)
    new_status = repo.toggle_favorite(channel.id)
    assert new_status is True
    refreshed = db_session.query(ChannelDB).filter_by(id=channel.id).one()
    assert refreshed.is_favorite is True


def test_toggle_favorite_repo_flips_back_to_false(db_session, channel):
    repo = ChannelRepository(db_session)
    repo.toggle_favorite(channel.id)   # True
    new_status = repo.toggle_favorite(channel.id)  # False
    assert new_status is False
    refreshed = db_session.query(ChannelDB).filter_by(id=channel.id).one()
    assert refreshed.is_favorite is False


# ---------------------------------------------------------------------------
# MainWindow-level pins: status message content is correct for both methods
# ---------------------------------------------------------------------------

def _build_mock_window(engine):
    """Thin MainWindow shell with a real DB backed by the test engine."""
    from metatv.core.database import Database
    from metatv.gui import main_window as mw_module

    db = MagicMock(spec=Database)

    # Let get_session() return a real session from the test engine
    Session = sessionmaker(bind=engine)

    def _get_session():
        return Session()

    db.get_session = _get_session

    with patch.object(mw_module.MainWindow, "__init__", lambda self: None):
        win = mw_module.MainWindow.__new__(mw_module.MainWindow)

    win.db = db
    win.status_bar = MagicMock()
    win.channels_list = MagicMock()
    win.channel_model = MagicMock()   # virtualized model — update_favorite called by toggle
    win.all_channels = []
    win.favorite_icon = "★"
    win.unfavorite_icon = "☆"
    win.load_favorites = MagicMock()
    win._lightbox = MagicMock()
    win._lightbox.isVisible.return_value = False
    win.update_details_pane_for_channel = MagicMock()

    # get_media_type_icon not exercised here
    win.get_media_type_icon = MagicMock(return_value="")

    return win


def test_toggle_favorite_posts_added_status(engine, channel):
    win = _build_mock_window(engine)
    item = MagicMock()
    from PyQt6.QtCore import Qt
    item.data.return_value = channel.id
    item.text.return_value = f"☆ {channel.name}"

    win.toggle_favorite(item)

    call_args = win.status_bar.showMessage.call_args[0][0]
    assert "added to" in call_args
    assert channel.name in call_args


def test_toggle_favorite_posts_removed_status(engine, channel):
    win = _build_mock_window(engine)

    # Toggle twice: added → removed
    item = MagicMock()
    from PyQt6.QtCore import Qt
    item.data.return_value = channel.id
    item.text.return_value = f"☆ {channel.name}"
    win.toggle_favorite(item)
    item.text.return_value = f"★ {channel.name}"
    win.toggle_favorite(item)

    last_msg = win.status_bar.showMessage.call_args[0][0]
    assert "removed from" in last_msg


def test_toggle_favorite_by_id_posts_added_status(engine, channel):
    win = _build_mock_window(engine)
    win.toggle_favorite_by_id(channel.id)
    call_args = win.status_bar.showMessage.call_args[0][0]
    assert "added to" in call_args
    assert channel.name in call_args


def test_toggle_favorite_by_id_updates_details_pane(engine, channel):
    win = _build_mock_window(engine)
    win.toggle_favorite_by_id(channel.id)
    win.update_details_pane_for_channel.assert_called_once()


def test_toggle_favorite_sidebar_refreshed(engine, channel):
    win = _build_mock_window(engine)
    item = MagicMock()
    from PyQt6.QtCore import Qt
    item.data.return_value = channel.id
    item.text.return_value = f"☆ {channel.name}"
    win.toggle_favorite(item)
    win.load_favorites.assert_called_once()


def test_toggle_favorite_by_id_sidebar_refreshed(engine, channel):
    win = _build_mock_window(engine)
    win.toggle_favorite_by_id(channel.id)
    win.load_favorites.assert_called_once()
