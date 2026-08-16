"""A successful stream failover must stick to the played item (#306).

``validate_and_failover_stream_url`` (main_window_streaming.py) already finds
a working alternate host at play time — but it never wrote that URL back to
the channel row, so the next play of the same item re-started from the dead
host and re-paid the failover stall on every play, forever.

The fix: ``_bg_validate_and_play`` (the failover function's single call site)
writes the new URL back onto the played item's own row, via the new
``ChannelRepository.update_stream_url``, whenever the returned URL differs
from the one it was given. Only when unchanged (the primary worked) is the
write skipped.

All DB tests use file-backed SQLite (tmp_path), per CLAUDE.md rule — never
``:memory:``, and the isolated-user-config fixture (autouse, conftest.py)
keeps this away from any real ``~/.config/metatv``.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

from loguru import logger as _loguru_logger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(tmp_path: Path):
    from metatv.core.database import Database
    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.create_tables()
    return d


def _insert_provider(session, provider_id: str, name: str, url: str, urls=None):
    from metatv.core.database import ProviderDB
    p = ProviderDB(
        id=provider_id,
        name=name,
        type="xtream",
        url=url,
        urls=urls or [],
        is_active=True,
    )
    session.add(p)
    session.flush()
    return p


def _insert_channel(session, channel_id: str, provider_id: str, name: str, stream_url: str):
    from metatv.core.database import ChannelDB
    ch = ChannelDB(
        id=channel_id,
        source_id=str(uuid.uuid4()),
        provider_id=provider_id,
        name=name,
        stream_url=stream_url,
        media_type="live",
    )
    session.add(ch)
    session.flush()
    return ch


def _make_mixin(db):
    """A bare ``_StreamingMixin`` instance wired with a real Database.

    Mirrors ``tests/test_streaming_offthread.py``'s ``_make_mixin`` — this
    slice adds the DB write-back, so ``obj.db`` must be a real
    file-backed ``Database``, not a MagicMock, for these tests.
    """
    from tests.conftest import wire_shutdown_flag
    from metatv.gui.main_window_streaming import _StreamingMixin
    obj = wire_shutdown_flag(_StreamingMixin.__new__(_StreamingMixin))
    obj.loading_channels = set()
    obj.db = db
    obj.executor = MagicMock()
    obj.player_manager = MagicMock()
    obj.notification_manager = MagicMock()
    obj.notification_manager.show.return_value = "notif-123"
    obj.status_bar = MagicMock()
    obj._stream_ready = MagicMock()
    return obj


def _read_stream_url(db, channel_id: str) -> str:
    """Re-read a channel's stored stream_url from a FRESH session."""
    from metatv.core.database import ChannelDB
    with db.session_scope(commit=False) as session:
        row = session.get(ChannelDB, channel_id)
        return row.stream_url


# ---------------------------------------------------------------------------
# 1. A failover that returns a different host persists to the channel row.
# ---------------------------------------------------------------------------

def test_failover_persists_new_url_on_change(tmp_path):
    db = _make_db(tmp_path)
    channel_id = str(uuid.uuid4())
    provider_id = str(uuid.uuid4())
    original_url = "http://deadhost.example:8080/live/testuser/testpass/11111.ts"
    new_url = "http://goodhost.example:9090/live/testuser/testpass/11111.ts"

    with db.session_scope() as session:
        _insert_provider(session, provider_id, "TestProv1", original_url)
        _insert_channel(session, channel_id, provider_id, "Test Channel 1", original_url)

    obj = _make_mixin(db)
    with patch.object(obj, "validate_and_failover_stream_url", return_value=(new_url, None)):
        obj._bg_validate_and_play(
            channel_id, "Test Channel 1", original_url, provider_id, "notif-1"
        )

    # Re-read from the DB in a brand-new session — not the in-memory object.
    assert _read_stream_url(db, channel_id) == new_url


# ---------------------------------------------------------------------------
# 2. When the primary validates fine (URL unchanged), nothing is written.
# ---------------------------------------------------------------------------

def test_failover_no_write_when_url_unchanged(tmp_path):
    from metatv.core.repositories.channel import ChannelRepository

    db = _make_db(tmp_path)
    channel_id = str(uuid.uuid4())
    provider_id = str(uuid.uuid4())
    original_url = "http://workinghost.example:8080/live/testuser/testpass/22222.ts"

    with db.session_scope() as session:
        _insert_provider(session, provider_id, "TestProv2", original_url)
        _insert_channel(session, channel_id, provider_id, "Test Channel 2", original_url)

    obj = _make_mixin(db)
    with patch.object(
        obj, "validate_and_failover_stream_url", return_value=(original_url, None)
    ), patch.object(ChannelRepository, "update_stream_url") as mock_update:
        obj._bg_validate_and_play(
            channel_id, "Test Channel 2", original_url, provider_id, "notif-2"
        )

    mock_update.assert_not_called()
    # Byte-identical to the original stored value.
    assert _read_stream_url(db, channel_id) == original_url


# ---------------------------------------------------------------------------
# 3. update_stream_url on an unknown channel_id is a no-op, never raises.
# ---------------------------------------------------------------------------

def test_update_stream_url_unknown_channel_is_noop(tmp_path):
    from metatv.core.database import ChannelDB
    from metatv.core.repositories.channel import ChannelRepository

    db = _make_db(tmp_path)

    with db.session_scope() as session:
        repo = ChannelRepository(session)
        repo.update_stream_url("does-not-exist", "http://example.com/new.ts")  # must not raise

    with db.session_scope(commit=False) as session:
        assert session.query(ChannelDB).count() == 0


# ---------------------------------------------------------------------------
# 4. Credentials never reach the log during a rewrite.
# ---------------------------------------------------------------------------

def test_credentials_never_reach_log(tmp_path):
    db = _make_db(tmp_path)
    channel_id = str(uuid.uuid4())
    provider_id = str(uuid.uuid4())
    username = "secretuser"
    password = "secretpass"
    original_url = f"http://deadhost.example:8080/live/{username}/{password}/33333.ts"
    new_url = f"http://goodhost.example:9090/live/{username}/{password}/33333.ts"

    with db.session_scope() as session:
        _insert_provider(session, provider_id, "TestProv3", original_url)
        _insert_channel(session, channel_id, provider_id, "Test Channel 3", original_url)

    obj = _make_mixin(db)

    captured: list[str] = []
    sink_id = _loguru_logger.add(lambda msg: captured.append(msg.record["message"]), level="DEBUG")
    try:
        with patch.object(obj, "validate_and_failover_stream_url", return_value=(new_url, None)):
            obj._bg_validate_and_play(
                channel_id, "Test Channel 3", original_url, provider_id, "notif-3"
            )
    finally:
        _loguru_logger.remove(sink_id)

    combined = "\n".join(captured)
    assert username not in combined
    assert password not in combined


# ---------------------------------------------------------------------------
# 5. The persisted URL keeps the original path/query exactly; only the host
#    changes — exercised through the REAL validate_and_failover_stream_url +
#    reconstruct_stream_url pipeline (only the network layer is mocked), so a
#    wrong reconstruct_stream_url result cannot slip through undetected.
# ---------------------------------------------------------------------------

def test_persisted_url_preserves_path_and_only_host_changes(tmp_path):
    db = _make_db(tmp_path)
    channel_id = str(uuid.uuid4())
    provider_id = str(uuid.uuid4())
    primary_base = "http://deadhost.example:8080"
    alt_base = "http://goodhost.example:9090"
    path_and_query = "/live/testuser/testpass/44444.ts?token=abc123"
    original_url = primary_base + path_and_query
    expected_new_url = alt_base + path_and_query

    with db.session_scope() as session:
        _insert_provider(
            session, provider_id, "TestProv4", primary_base,
            urls=[{"url": alt_base, "priority": 0, "is_active": True}],
        )
        _insert_channel(session, channel_id, provider_id, "Test Channel 4", original_url)

    obj = _make_mixin(db)
    # Only the network layer is mocked: primary fails, the alternate succeeds.
    # validate_and_failover_stream_url, reconstruct_stream_url, UrlCycler, and
    # the write-back all run for real.
    with patch.object(obj, "validate_stream_url", side_effect=[
        (False, None),   # primary fails, no text error
        (True, None),    # alternate succeeds
    ]):
        obj._bg_validate_and_play(
            channel_id, "Test Channel 4", original_url, provider_id, "notif-4"
        )

    persisted = _read_stream_url(db, channel_id)
    assert persisted == expected_new_url
    # The path/query segment is preserved exactly — only the host changed.
    assert persisted.endswith(path_and_query)
    assert persisted.startswith(alt_base)
