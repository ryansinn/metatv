"""The preempt hook is a fan-out, and every evicted consumer hears it.

Owner, 2026-09-01 03:13-03:16: "streams no longer play — notification
buffering message, mpv opens, then after a few seconds, closes."

``ConnectionAccountant`` held ONE ``_on_preempt`` callback, assigned directly
by ``main_window_downloads`` — so ``DownloadManager`` owned the hook outright.
Two other consumers are preemptible by exactly the same rule: the TMDb
enrichment backfill and the series-monitor poll, both registered with
``kind="monitor"``, both listed in ``PLAYBACK_PREEMPTS``. Playback evicted them
from the registry and nothing told them, so eviction was bookkeeping only and
their in-flight HTTP calls kept the provider's single connection. mpv was
refused, and quit a few seconds after opening.

The owner's log shows it plainly: an enrichment batch of forty detail calls
running 03:15:09.9 → 03:15:17.9, straight through a play at 03:15:11.8, and
every stream probe from 03:15:26 onward returning HTTP 500.

A hand-assigned callback is an enumeration of size one — the same failure this
codebase keeps paying for. These tests pin the fan-out, the abandonment it
enables, and a drift guard so the next consumer cannot quietly take the hook.
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
from types import SimpleNamespace

from metatv.core.connection_accountant import ConnectionAccountant
from metatv.core.player_manager import PLAYBACK_PREEMPTS
from metatv.core.tmdb_enrichment_manager import TmdbEnrichmentManager

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# 1. The accountant tells EVERY listener, not the last one registered
# ---------------------------------------------------------------------------


def test_every_listener_hears_one_eviction():
    """Two consumers, one eviction, two notifications.

    Pre-fix the second registration overwrote the first, so whichever manager
    wired itself last was the only one ever told.
    """
    heard: list[tuple[str, str, str]] = []
    acct = ConnectionAccountant(capacity_resolver=lambda _p: 1)
    acct.add_preempt_listener(lambda p, h, k: heard.append(("downloads", h, k)))
    acct.add_preempt_listener(lambda p, h, k: heard.append(("enrichment", h, k)))

    acct.acquire("p1", "monitor", "tmdb_enrich:p1")
    granted = acct.acquire("p1", "playback", "__shared__",
                           preempt_kinds=PLAYBACK_PREEMPTS)

    assert granted.granted and granted.preempted == ("tmdb_enrich:p1",)
    assert [who for who, _, _ in heard] == ["downloads", "enrichment"], (
        "both listeners must be told — a single slot is what left enrichment "
        "running on the provider's one connection")
    assert all(h == "tmdb_enrich:p1" and k == "monitor" for _, h, k in heard)


def test_constructor_callback_still_works_and_composes():
    """The ``on_preempt=`` argument keeps working, as the first listener."""
    heard: list[str] = []
    acct = ConnectionAccountant(capacity_resolver=lambda _p: 1,
                                on_preempt=lambda p, h, k: heard.append("ctor"))
    acct.add_preempt_listener(lambda p, h, k: heard.append("added"))
    acct.acquire("p1", "monitor", "poll-1")
    acct.acquire("p1", "playback", "play-1", preempt_kinds=PLAYBACK_PREEMPTS)
    assert heard == ["ctor", "added"]


def test_one_broken_listener_does_not_silence_the_rest():
    """A raising listener must not stop the others being told.

    A consumer left believing it still holds the slot is the exact bug the
    fan-out exists to prevent, so a bad neighbour cannot be allowed to cause it.
    """
    heard: list[str] = []

    def _boom(p, h, k):
        raise RuntimeError("listener blew up")

    acct = ConnectionAccountant(capacity_resolver=lambda _p: 1)
    acct.add_preempt_listener(_boom)
    acct.add_preempt_listener(lambda p, h, k: heard.append("survivor"))
    acct.acquire("p1", "monitor", "poll-1")
    acct.acquire("p1", "playback", "play-1", preempt_kinds=PLAYBACK_PREEMPTS)
    assert heard == ["survivor"]


def test_registering_the_same_listener_twice_notifies_once():
    """Idempotent — a re-wire on reload must not double-notify."""
    heard: list[str] = []
    acct = ConnectionAccountant(capacity_resolver=lambda _p: 1)
    cb = lambda p, h, k: heard.append("x")   # noqa: E731 — identity is the point
    acct.add_preempt_listener(cb)
    acct.add_preempt_listener(cb)
    acct.acquire("p1", "monitor", "poll-1")
    acct.acquire("p1", "playback", "play-1", preempt_kinds=PLAYBACK_PREEMPTS)
    assert heard == ["x"]


# ---------------------------------------------------------------------------
# 2. Enrichment actually STOPS — being told is only useful if it acts
# ---------------------------------------------------------------------------


class _CountingApi:
    """Fake Xtream API that trips the eviction partway through the batch."""

    def __init__(self, mgr: TmdbEnrichmentManager, provider_id: str, trip_after: int):
        self.calls: list[str] = []
        self._mgr = mgr
        self._pid = provider_id
        self._trip = trip_after

    async def get_vod_info(self, source_id: str) -> dict:
        self.calls.append(source_id)
        if len(self.calls) == self._trip:
            # Exactly what the accountant does when the user presses Play.
            self._mgr.on_preempted(
                self._pid, self._mgr._holder_id(self._pid), "playback")
        return {"info": {}}

    async def get_series_info(self, source_id: str) -> dict:   # pragma: no cover
        return {"info": {}}


def _rows(n: int) -> list[dict]:
    return [{"id": f"c{i}", "source_id": str(i), "media_type": "movie"}
            for i in range(n)]


def test_enrichment_abandons_its_batch_when_playback_takes_the_slot():
    """The forty calls stop at the eviction instead of running to completion.

    This is the defect the owner saw: the batch kept going, so mpv could not
    get the provider's connection and quit a few seconds after opening.
    Pre-fix ``_run_calls`` had no eviction gate and all ten rows were fetched.
    """
    mgr = TmdbEnrichmentManager(SimpleNamespace(), SimpleNamespace())
    api = _CountingApi(mgr, "p1", trip_after=3)
    try:
        hits, misses, meta, errors, deferred = asyncio.run(
            mgr._run_calls(api, _rows(10), 1, 0.0, "p1"))
    finally:
        mgr.shutdown()

    assert len(api.calls) == 3, (
        f"kept calling the provider after losing the slot ({len(api.calls)}/10) "
        "— this is what refused mpv its connection")
    assert deferred is False, "the batch DID run; it was abandoned, not deferred"
    assert errors == 0, "abandonment is not an error — those rows retry later"


def test_an_unpreempted_batch_still_fetches_every_row():
    """Non-degeneracy: the gate must not abandon a batch nobody evicted."""
    mgr = TmdbEnrichmentManager(SimpleNamespace(), SimpleNamespace())
    api = _CountingApi(mgr, "p1", trip_after=0)   # never trips
    try:
        asyncio.run(mgr._run_calls(api, _rows(10), 1, 0.0, "p1"))
    finally:
        mgr.shutdown()
    assert len(api.calls) == 10, "gate fired with no eviction — would stall enrichment"


def test_an_eviction_of_someone_else_is_ignored():
    """Every listener hears EVERY eviction, so screening on the holder matters."""
    mgr = TmdbEnrichmentManager(SimpleNamespace(), SimpleNamespace())
    try:
        mgr.on_preempted("p1", "download:some-other-job", "download")
        assert not mgr._was_preempted("p1"), (
            "abandoned the batch on a download's eviction — a listener that "
            "acts on foreign ids stops enrichment every time anything yields")
    finally:
        mgr.shutdown()


def test_a_new_batch_is_not_poisoned_by_the_previous_eviction():
    """The flag is armed at acquire, so it cannot leak into the next batch."""
    mgr = TmdbEnrichmentManager(SimpleNamespace(), SimpleNamespace())
    try:
        mgr.on_preempted("p1", mgr._holder_id("p1"), "playback")
        assert mgr._was_preempted("p1")
        # _fetch_provider clears on acquire; this is that step in isolation.
        with mgr._lock:
            mgr._preempted_providers.discard("p1")
        assert not mgr._was_preempted("p1"), "a stale flag would kill every later batch"
    finally:
        mgr.shutdown()


# ---------------------------------------------------------------------------
# 3. Drift guard — nobody may take the hook back
# ---------------------------------------------------------------------------


def test_no_module_assigns_the_private_preempt_hook():
    """``accountant._on_preempt = ...`` is the bug; the seam is add_preempt_listener.

    An AST walk, not a grep, so the check does not depend on how the target is
    spelled: any assignment whose target attribute is ``_on_preempt`` is drift,
    whatever the object expression looks like.
    """
    offenders: list[str] = []
    for path in sorted((_REPO_ROOT / "metatv").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute) and target.attr == "_on_preempt":
                    # The accountant's own __init__ is where the field lives.
                    if path.name == "connection_accountant.py":
                        continue
                    offenders.append(
                        f"{path.relative_to(_REPO_ROOT)}:{node.lineno}")

    assert not offenders, (
        "assign to accountant._on_preempt replaces every other listener; call "
        "accountant.add_preempt_listener(cb) instead. Offenders: "
        + ", ".join(offenders))


def test_the_accountant_no_longer_exposes_a_single_callback_slot():
    """The field is a list of listeners — a scalar slot is what caused the bug."""
    acct = ConnectionAccountant(capacity_resolver=lambda _p: 1)
    assert isinstance(acct._preempt_listeners, list)
    assert not hasattr(acct, "_on_preempt"), (
        "a surviving scalar slot invites the assignment the guard above forbids")
