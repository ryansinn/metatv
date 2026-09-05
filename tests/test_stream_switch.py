"""Same-provider stream switching (PLAY-10): no re-probe, prefer the live host.

Covers ``gui.stream_switch.switch_context``/``prefer_live_host`` and the
``PlayerManager.live_base_url`` accessor they're built on. See
``gui/stream_switch.py``'s module docstring for the bug this fixes.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from metatv.core.connection_accountant import ConnectionAccountant
from metatv.core.models import Provider, ProviderURL
from metatv.core.player_manager import PlayerManager
from metatv.core.url_cycle import UrlCycler
from metatv.gui.stream_switch import SwitchContext, prefer_live_host, switch_context
from tests.conftest import wire_player_manager_key_maps


# ── shared factory: a real PlayerManager, fake mpv (no real process) ────────

class _FakePlayer:
    """Stands in for MPVPlayer: tracks which keys are "running" and their URL."""

    def __init__(self) -> None:
        self._running: set[str] = set()

    def play(self, url, title, instance_key="__shared__", **kwargs) -> bool:
        self._running.add(instance_key)
        return True

    def is_running(self, key=None) -> bool:
        return key in self._running

    def active_keys(self) -> list[str]:
        return list(self._running)

    def stop(self, key=None) -> bool:
        self._running.discard(key)
        return True

    def is_available(self) -> bool:
        return True


def _make_manager(max_player_instances: int = -1) -> PlayerManager:
    """A real ``PlayerManager`` (real key-mapping/accounting logic, fake mpv)."""
    mgr = PlayerManager.__new__(PlayerManager)
    mgr.config = MagicMock(
        max_player_instances=max_player_instances, split_streams_by_source=False,
    )
    wire_player_manager_key_maps(mgr)
    mgr._init_connection_accounting()
    mgr.player = _FakePlayer()
    return mgr


# ── PlayerManager.live_base_url ──────────────────────────────────────────────

def test_live_base_url_after_a_successful_play():
    mgr = _make_manager()
    assert mgr.play("http://host1.example.com/live/u/p/1.ts", "Title",
                     provider_id="p1", provider_max_connections=1) is True
    assert mgr.live_base_url("__shared__") == "http://host1.example.com"


def test_live_base_url_is_none_after_stop():
    mgr = _make_manager()
    mgr.play("http://host1.example.com/live/u/p/1.ts", "Title",
              provider_id="p1", provider_max_connections=1)
    mgr.stop("__shared__")
    assert mgr.live_base_url("__shared__") is None


def test_live_base_url_is_none_for_a_key_never_played_into():
    mgr = _make_manager()
    assert mgr.live_base_url("__shared__") is None
    assert mgr.live_base_url(None) is None


# ── switch_context ────────────────────────────────────────────────────────

def test_switch_context_true_when_running_on_the_same_provider():
    mgr = _make_manager()
    mgr.play("http://host1.example.com/live/u/p/1.ts", "Title",
              provider_id="p1", provider_max_connections=1)
    ctx = switch_context(mgr, mgr.connection_accountant, "p1", "__shared__")
    assert ctx.same_provider is True
    assert ctx.live_base_url == "http://host1.example.com"


def test_switch_context_false_for_a_different_provider():
    mgr = _make_manager()
    mgr.play("http://host1.example.com/live/u/p/1.ts", "Title",
              provider_id="p1", provider_max_connections=1)
    ctx = switch_context(mgr, mgr.connection_accountant, "p2", "__shared__")
    assert ctx.same_provider is False


def test_switch_context_false_when_nothing_is_running():
    mgr = _make_manager()
    ctx = switch_context(mgr, mgr.connection_accountant, "p1", "__shared__")
    assert ctx.same_provider is False
    assert ctx.live_base_url is None


def test_switch_context_one_connection_false_without_an_accountant():
    mgr = _make_manager()
    mgr.play("http://host1.example.com/live/u/p/1.ts", "Title",
              provider_id="p1", provider_max_connections=1)
    ctx = switch_context(mgr, None, "p1", "__shared__")
    assert ctx.one_connection is False


def test_switch_context_one_connection_true_at_capacity_one():
    acct = ConnectionAccountant(capacity_resolver=lambda _p: 1)
    ctx = switch_context(_make_manager(), acct, "p1", "__shared__")
    assert ctx.one_connection is True


def test_switch_context_one_connection_false_above_capacity_one():
    acct = ConnectionAccountant(capacity_resolver=lambda _p: 3)
    ctx = switch_context(_make_manager(), acct, "p1", "__shared__")
    assert ctx.one_connection is False


# ── prefer_live_host ─────────────────────────────────────────────────────

def _provider(*bases: str) -> Provider:
    return Provider(
        id="p1", name="Test", type="xtream", url=bases[0],
        urls=[ProviderURL(url=b) for b in bases],
    )


def test_prefer_live_host_rewrites_onto_a_real_candidate():
    provider = _provider("http://primary.example.com", "http://alt.example.com")
    url = "http://primary.example.com/live/u/p/1.ts"
    result = prefer_live_host(url, "http://alt.example.com", provider)
    assert result == "http://alt.example.com/live/u/p/1.ts"


def test_prefer_live_host_unchanged_when_live_base_equals_the_urls_base():
    provider = _provider("http://primary.example.com", "http://alt.example.com")
    url = "http://primary.example.com/live/u/p/1.ts"
    assert prefer_live_host(url, "http://primary.example.com", provider) == url


def test_prefer_live_host_unchanged_when_live_base_is_not_a_candidate():
    """Never routes onto a host outside the provider's own configured list —
    however plausible it looks."""
    provider = _provider("http://primary.example.com", "http://alt.example.com")
    url = "http://primary.example.com/live/u/p/1.ts"
    result = prefer_live_host(url, "http://not-configured.example.com", provider)
    assert result == url


def test_prefer_live_host_unchanged_when_no_live_base_url():
    provider = _provider("http://primary.example.com")
    url = "http://primary.example.com/live/u/p/1.ts"
    assert prefer_live_host(url, None, provider) == url


def test_prefer_live_host_uses_the_same_candidate_list_as_ordinary_failover():
    """The candidate check must be UrlCycler's own list — a regression here
    would silently start trusting a host UrlCycler itself would never try."""
    provider = _provider("http://primary.example.com", "http://alt.example.com")
    candidates = {c.rstrip("/") for c in UrlCycler(provider, "resolve_playable_url").candidates()}
    assert "http://alt.example.com" in candidates
    url = "http://primary.example.com/live/u/p/1.ts"
    assert prefer_live_host(url, "http://alt.example.com", provider) != url


# ── SwitchContext is a plain frozen dataclass ────────────────────────────

def test_switch_context_dataclass_is_frozen():
    ctx = SwitchContext(same_provider=True, live_base_url="http://x", one_connection=True)
    with pytest.raises(AttributeError):
        ctx.same_provider = False
