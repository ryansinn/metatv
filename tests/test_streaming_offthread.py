"""Characterization tests for B6-7: stream validation runs off the UI thread.

These tests verify:
  1. validate_and_failover_stream_url: failover ordering and per-attempt stat updates.
  2. play_media returns immediately (no blocking) and delegates to _bg_validate_and_play.
  3. _bg_validate_and_play emits _stream_ready with the correct shape.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch, call
import pytest

from metatv.gui.main_window_streaming import _StreamingMixin


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_mixin() -> _StreamingMixin:
    """Return a bare _StreamingMixin instance with enough state for unit tests."""
    obj = _StreamingMixin.__new__(_StreamingMixin)
    obj.loading_channels = set()
    obj.db = MagicMock()
    obj.executor = MagicMock()
    obj.player_manager = MagicMock()
    obj.notification_manager = MagicMock()
    obj.notification_manager.show.return_value = "notif-123"
    obj.status_bar = MagicMock()
    obj._stream_ready = MagicMock()
    return obj


# ── validate_and_failover_stream_url: failover ordering ──────────────────────

def _make_session_scope(session: MagicMock):
    """Return a session_scope contextmanager that yields the given mock session."""
    @contextmanager
    def _scope():
        yield session
    return _scope


def test_failover_uses_alternate_url_on_primary_fail():
    """If primary URL fails (no text error), alternate is tried in order."""
    obj = _make_mixin()

    primary = "http://primary.example.com/live/u/p/1234.ts"
    alt1 = "http://alt1.example.com"
    alt1_url = "http://alt1.example.com/live/u/p/1234.ts"

    # Provider DB mock
    provider_db = MagicMock()
    provider_db.name = "TestProvider"
    provider_db.urls = []
    provider_model = MagicMock()
    provider_model.ordered_urls.return_value = [alt1]

    repos = MagicMock()
    repos.providers.get_by_id.return_value = provider_db
    repos.providers.to_model.return_value = provider_model

    session = MagicMock()
    obj.db.session_scope = _make_session_scope(session)

    with patch("metatv.gui.main_window_streaming.RepositoryFactory", return_value=repos), \
         patch("metatv.gui.main_window_streaming.parse_provider_urls", return_value=[{"url": alt1}]), \
         patch.object(obj, "reconstruct_stream_url", return_value=alt1_url), \
         patch.object(obj, "validate_stream_url", side_effect=[
             (False, None),   # primary fails, no text error
             (True, None),    # alt1 succeeds
         ]):
        result_url, err = obj.validate_and_failover_stream_url(
            primary, "prov-1"
        )

    assert result_url == alt1_url
    assert err is None



def test_failover_stops_on_text_error():
    """If primary URL returns a text error, alternate URLs are NOT tried."""
    obj = _make_mixin()

    primary = "http://primary.example.com/live/u/p/1234.ts"

    with patch.object(obj, "validate_stream_url", return_value=(False, "not available")):
        result_url, err = obj.validate_and_failover_stream_url(
            primary, "prov-1"
        )

    assert result_url == ""
    assert err == "not available"


def test_failover_success_stat_commit():
    """On alternate URL success, the URL entry gets a success_count increment and a commit."""
    obj = _make_mixin()

    primary = "http://primary.example.com/live/u/p/1234.ts"
    alt_base = "http://alt.example.com"
    alt_url = "http://alt.example.com/live/u/p/1234.ts"
    raw_urls = [{"url": alt_base, "success_count": 0}]

    provider_db = MagicMock()
    provider_db.name = "TestProvider"
    provider_model = MagicMock()
    provider_model.ordered_urls.return_value = [alt_base]

    repos = MagicMock()
    repos.providers.get_by_id.return_value = provider_db
    repos.providers.to_model.return_value = provider_model

    session = MagicMock()
    obj.db.session_scope = _make_session_scope(session)

    with patch("metatv.gui.main_window_streaming.RepositoryFactory", return_value=repos), \
         patch("metatv.gui.main_window_streaming.parse_provider_urls", return_value=raw_urls), \
         patch.object(obj, "reconstruct_stream_url", return_value=alt_url), \
         patch.object(obj, "validate_stream_url", side_effect=[
             (False, None),   # primary fails
             (True, None),    # alt succeeds
         ]):
        obj.validate_and_failover_stream_url(primary, "prov-1")

    # success_count should be 1
    assert raw_urls[0].get("success_count") == 1
    # commit should have been called (per-attempt explicit commit)
    session.commit.assert_called()


def test_failover_failure_stat_commit():
    """On alternate URL failure, failure_count is incremented and committed."""
    obj = _make_mixin()

    primary = "http://primary.example.com/live/u/p/1234.ts"
    alt_base = "http://alt.example.com"
    alt_url = "http://alt.example.com/live/u/p/1234.ts"
    raw_urls = [{"url": alt_base, "failure_count": 0}]

    provider_db = MagicMock()
    provider_db.name = "TestProvider"
    provider_model = MagicMock()
    provider_model.ordered_urls.return_value = [alt_base]

    repos = MagicMock()
    repos.providers.get_by_id.return_value = provider_db
    repos.providers.to_model.return_value = provider_model

    session = MagicMock()
    obj.db.session_scope = _make_session_scope(session)

    with patch("metatv.gui.main_window_streaming.RepositoryFactory", return_value=repos), \
         patch("metatv.gui.main_window_streaming.parse_provider_urls", return_value=raw_urls), \
         patch.object(obj, "reconstruct_stream_url", return_value=alt_url), \
         patch.object(obj, "validate_stream_url", side_effect=[
             (False, None),   # primary fails
             (False, None),   # alt fails
         ]):
        result_url, _ = obj.validate_and_failover_stream_url(primary, "prov-1")

    assert result_url == ""
    assert raw_urls[0].get("failure_count") == 1
    session.commit.assert_called()


# ── play_media returns immediately (non-blocking) ─────────────────────────────

def test_play_media_returns_immediately_without_blocking():
    """play_media must submit work to executor and return, not block on network."""
    obj = _make_mixin()

    channel = MagicMock()
    channel.id = "ch-1"
    channel.name = "Test Channel"
    channel.stream_url = "http://primary.example.com/live/u/p/1234.ts"
    channel.media_type = "live"
    channel.provider_id = "prov-1"
    channel.source_id = "src-1"

    submit_calls = []
    obj.executor.submit = lambda fn, *a, **kw: submit_calls.append((fn, a, kw)) or MagicMock()

    obj.play_media(channel)

    # Must have submitted a background task
    assert len(submit_calls) == 1
    fn, args, kwargs = submit_calls[0]
    assert fn == obj._bg_validate_and_play
    assert args[0] == "ch-1"  # channel_id


def test_play_media_double_click_guard():
    """play_media with the same channel_id twice only submits once."""
    obj = _make_mixin()
    obj.loading_channels.add("ch-1")

    channel = MagicMock()
    channel.id = "ch-1"
    channel.stream_url = "http://example.com/stream.ts"

    obj.play_media(channel)

    # executor.submit must NOT have been called — channel was already loading
    obj.executor.submit.assert_not_called()


def test_play_media_no_stream_url():
    """play_media with no stream_url discards the channel_id and returns."""
    obj = _make_mixin()

    channel = MagicMock()
    channel.id = "ch-1"
    channel.name = "Bad Channel"
    channel.stream_url = ""  # no URL

    obj.play_media(channel)

    obj.executor.submit.assert_not_called()
    assert "ch-1" not in obj.loading_channels


# ── _bg_validate_and_play emits _stream_ready ────────────────────────────────

def test_bg_validate_success_emits_ok():
    """_bg_validate_and_play emits ok=True with final_url on success."""
    obj = _make_mixin()

    with patch.object(
        obj,
        "validate_and_failover_stream_url",
        return_value=("http://final.example.com/stream.ts", None),
    ):
        obj._bg_validate_and_play(
            "ch-1", "Chan", "http://primary.example.com/stream.ts",
            "prov-1", "notif-1"
        )

    obj._stream_ready.emit.assert_called_once()
    payload = obj._stream_ready.emit.call_args[0][0]
    assert payload["ok"] is True
    assert payload["final_url"] == "http://final.example.com/stream.ts"
    assert payload["channel_id"] == "ch-1"
    assert payload["notif_id"] == "notif-1"


def test_bg_validate_failure_emits_not_ok():
    """_bg_validate_and_play emits ok=False with stream_err on all-URL failure."""
    obj = _make_mixin()

    with patch.object(
        obj,
        "validate_and_failover_stream_url",
        return_value=("", "not available"),
    ):
        obj._bg_validate_and_play(
            "ch-1", "Chan", "http://primary.example.com/stream.ts",
            "prov-1", "notif-1"
        )

    payload = obj._stream_ready.emit.call_args[0][0]
    assert payload["ok"] is False
    assert payload["stream_err"] == "not available"
