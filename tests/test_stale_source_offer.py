"""STALE-1: a failing stream offers to refresh its stale source — and only then.

The offer is one more action on the existing failure toast, scoped to the
failing channel's provider, never auto-fired, and absent when the source is
fresh or its freshness is unknown (a test double's MagicMock session).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

from metatv.gui.stale_source_offer import read_last_refresh, stale_source_offer

NOW = datetime(2026, 9, 7, 12, 0, 0)


def _name(pid: str) -> str:
    return {"p1": "Shark"}.get(pid, pid)


def test_a_stale_source_gets_a_hint_and_a_refresh_button():
    refreshed: list[str] = []
    hint, action = stale_source_offer(_name, refreshed.append, "p1", NOW - timedelta(days=2), NOW)
    assert hint == "Last refreshed 2 days ago — its stream links may have expired"
    label, fn = action
    assert label == "Refresh Shark"
    fn()
    assert refreshed == ["p1"], "the button refreshes that one source and nothing else"


def test_a_fresh_source_gets_no_offer():
    assert stale_source_offer(_name, MagicMock(), "p1", NOW - timedelta(hours=1), NOW) == (None, None)


def test_unknown_freshness_or_no_provider_gets_no_offer():
    assert stale_source_offer(_name, MagicMock(), "p1", "unknown", NOW) == (None, None)
    assert stale_source_offer(_name, MagicMock(), None, None, NOW) == (None, None)


def test_read_last_refresh_treats_a_double_as_unknown():
    """A MagicMock session yields a MagicMock 'datetime' — that is not evidence."""
    assert read_last_refresh(MagicMock(), "p1") == "unknown"
    assert read_last_refresh(MagicMock(), None) == "unknown"


def test_the_failure_toast_carries_the_refresh_action_only_when_stale():
    """End to end on the streaming mixin: the action row grows exactly one button."""
    from tests.conftest import wire_status_method
    from metatv.gui.main_window_streaming import _StreamingMixin

    def host():
        obj = _StreamingMixin.__new__(_StreamingMixin)
        obj.loading_channels = set()
        obj.db = MagicMock()
        obj.executor = MagicMock()
        obj.player_manager = MagicMock()
        obj.notification_manager = MagicMock()
        obj.notification_manager.show.return_value = "n1"
        obj.status_bar = MagicMock()
        wire_status_method(obj)
        obj._stream_ready = MagicMock()
        obj._provider_icons = {}
        obj.stream_retry_manager = MagicMock()
        obj._provider_display_name = _name
        obj.refresh_provider = MagicMock()
        return obj

    def payload(last_refresh):
        return {
            "ok": False, "channel_id": "c1", "channel_name": "Some Channel",
            "original_url": "http://x/1.ts", "final_url": "", "stream_err": "HTTP 404",
            "notif_id": "n1", "provider_id": "p1", "provider_last_refresh": last_refresh,
        }

    stale = host()
    stale._on_stream_ready(payload(NOW - timedelta(days=3)))
    labels = [a[0] for a in stale.notification_manager.show.call_args.kwargs["actions"]]
    assert "Refresh Shark" in labels, labels
    stale_action = dict(stale.notification_manager.show.call_args.kwargs["actions"])["Refresh Shark"]
    stale_action()
    stale.refresh_provider.assert_called_once_with("p1")

    fresh = host()
    fresh._on_stream_ready(payload(datetime.now() - timedelta(hours=1)))
    labels = [a[0] for a in fresh.notification_manager.show.call_args.kwargs["actions"]]
    assert not any(l.startswith("Refresh ") for l in labels), labels
