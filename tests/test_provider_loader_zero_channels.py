"""Test that 0-channel loads report failure, not success.

Regression for the Ninja timeout incident: fetch_channels returns []
but was reported as "Loaded 0 channels successfully", masking the
timeout error.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import tempfile
from pathlib import Path

import pytest

from metatv.core.database import Database, ChannelDB
from metatv.core.provider_loader import ProviderLoadThread
from metatv.core.models import Provider, Channel


@pytest.fixture
def tmp_db():
    """File-backed SQLite Database for testing (not :memory:).

    Using a temp file instead of :memory: ensures pooled connections each
    get a fresh, isolated DB state — matches production SQLite behavior.
    """
    tmpfile = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmpfile.close()
    db_path = tmpfile.name

    db = Database(f"sqlite:///{db_path}")
    db.create_tables()
    yield db
    db.close()

    # Clean up temp file
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def fake_provider():
    """Minimal Provider instance for testing."""
    p = Provider.__new__(Provider)
    p.id = "test_prov"
    p.name = "Test Provider"
    p.type = "xtream"
    p.url = "http://example.com"
    p.username = "testuser"
    p.password = "testpass"
    p.urls = []  # No URLs for this unit test
    return p


def test_zero_channels_reported_as_failure(tmp_db, fake_provider):
    """Stub provider returns [], finished signal must carry success=False."""
    signal_args = []

    def capture_finished(success, message):
        signal_args.append((success, message))

    thread = ProviderLoadThread(fake_provider, tmp_db)
    thread.finished.connect(lambda s, m: capture_finished(s, m))

    # Stub provider returns empty list
    stub_plugin = MagicMock()
    stub_plugin.fetch_channels = AsyncMock(return_value=[])
    stub_plugin.fetch_account_info = None  # No account info method

    with patch("metatv.core.provider_loader.get_provider", return_value=stub_plugin):
        asyncio.run(thread.load_provider())

    assert len(signal_args) == 1, "finished signal must be emitted exactly once"
    success, message = signal_args[0]
    assert success is False, "0-channel load must report success=False"
    assert "successfully" not in message.lower(), (
        "Message must not contain 'successfully' when load fails"
    )
    assert "0 channels" in message, (
        "Message must mention that 0 channels were received"
    )


def test_happy_path_unchanged(tmp_db, fake_provider):
    """Stub provider returns real channels, finished signal carries success=True."""
    signal_args = []

    def capture_finished(success, message):
        signal_args.append((success, message))

    thread = ProviderLoadThread(fake_provider, tmp_db)
    thread.finished.connect(lambda s, m: capture_finished(s, m))

    # Stub provider returns a couple of real channels
    stub_channel_1 = MagicMock(spec=Channel)
    stub_channel_1.id = "ch1"
    stub_channel_1.name = "Channel 1"
    stub_channel_1.source_id = "1"
    stub_channel_1.provider_id = fake_provider.id
    stub_channel_1.stream_url = "http://example.com/stream/1"
    stub_channel_1.category = "Live"
    stub_channel_1.category_id = "1"
    stub_channel_1.logo_url = ""
    stub_channel_1.media_type = "live"
    stub_channel_1.quality.value = "UNKNOWN"
    stub_channel_1.raw_data = {}

    stub_channel_2 = MagicMock(spec=Channel)
    stub_channel_2.id = "ch2"
    stub_channel_2.name = "Channel 2"
    stub_channel_2.source_id = "2"
    stub_channel_2.provider_id = fake_provider.id
    stub_channel_2.stream_url = "http://example.com/stream/2"
    stub_channel_2.category = "Movies"
    stub_channel_2.category_id = "2"
    stub_channel_2.logo_url = ""
    stub_channel_2.media_type = "movie"
    stub_channel_2.quality.value = "UNKNOWN"
    stub_channel_2.raw_data = {}

    stub_plugin = MagicMock()
    stub_plugin.fetch_channels = AsyncMock(return_value=[stub_channel_1, stub_channel_2])
    stub_plugin.fetch_account_info = None

    with patch("metatv.core.provider_loader.get_provider", return_value=stub_plugin):
        asyncio.run(thread.load_provider())

    assert len(signal_args) == 1
    success, message = signal_args[0]
    assert success is True, "Non-zero channel load must report success=True"
    assert "2 channels" in message, "Message must mention the loaded channel count"
    assert "successfully" in message.lower(), (
        "Happy path message must contain 'successfully'"
    )

    # Verify channels were actually stored
    session = tmp_db.get_session()
    try:
        stored = session.query(ChannelDB).filter_by(provider_id=fake_provider.id).all()
        assert len(stored) == 2, "Both channels must be stored in the database"
    finally:
        session.close()
