"""Releasing a slot is not the same as the provider freeing it.

Owner, 2026-09-01 03:58, after #634 shipped: *"playback still isnt fixed"*.

#634 was necessary and it was not sufficient. It stops OUR background work the
moment playback evicts it — but the accountant frees a slot when our HTTP call
returns, and an Xtream panel keeps counting that closed connection against
``active_cons`` until its own reaper expires the record, tens of seconds later.
"We released it" and "you may open one" are different statements.

Measured on the owner's account (``max_connections = 1``):

* ``series_monitor`` made six back-to-back ``get_series_info`` calls to
  ``operator1.barfik.org`` at 03:58:06-09.
* Plays at 03:58:12, 03:58:20 and 03:58:26 each got
  ``HTTP 500 {"error":{"code":2,"message":"failed to redirect to stream origin"}}``.
* The identical ``.mkv`` URL, fetched with the app shut, returned **HTTP 206**,
  ``video/x-matroska``, with real EBML magic bytes. The stream was never broken
  and the account was ``status=Active, active_cons=0``.

So the source has to be claimed for the WHOLE attempt — including the ~1.5s
preflight probe, which is a real connection the accountant cannot see — and it
has to stay claimed across a failure, because the retry is what the user does
next.

The clock is injected; nothing here sleeps.
"""
from __future__ import annotations

from metatv.core.connection_accountant import ConnectionAccountant
from metatv.core.download_manager import DOWNLOAD_PREEMPTS
from metatv.core.player_manager import PLAYBACK_PREEMPTS
from metatv.core.series_monitor import MONITOR_KIND, MONITOR_PREEMPTS


def _acct(now):
    return ConnectionAccountant(capacity_resolver=lambda _p: 1, clock=lambda: now[0])


def _poll(acct, holder="sm-1"):
    return acct.acquire("p1", MONITOR_KIND, holder,
                        preempt_kinds=MONITOR_PREEMPTS).granted


def _play(acct, holder="__shared__"):
    return acct.acquire("p1", "playback", holder,
                        preempt_kinds=PLAYBACK_PREEMPTS).granted


# ---------------------------------------------------------------------------
# The reported sequence
# ---------------------------------------------------------------------------


def test_the_poller_is_locked_out_for_the_whole_probe_window():
    """The 03:58 failure: the probe is invisible, so the poller took its slot.

    ``validate_stream_url`` runs for ~1.5s holding a real provider connection
    that the accountant never sees. Pre-fix the source read as idle for that
    entire window.
    """
    now = [1000.0]
    acct = _acct(now)
    assert _poll(acct), "nothing is happening yet; the poller must be free to run"
    acct.release("p1", "sm-1")

    acct.note_foreground_use("p1")          # the user pressed play
    now[0] += 1.5                           # the probe is still running
    assert not _poll(acct, "sm-2"), (
        "the poller took the one slot while the preflight probe was open — "
        "this is the 03:58:06-09 burst that made the 03:58:12 play return 500")


def test_a_failed_play_keeps_the_source_claimed_for_the_retry():
    """The loop the user is actually in: press play, fail, press play again.

    Arming on release instead of on claim would free the source the instant
    mpv died, and the poller would be back on it before the retry.
    """
    now = [1000.0]
    acct = _acct(now)
    acct.note_foreground_use("p1")
    assert _play(acct)
    acct.release("p1", "__shared__")        # mpv failed and exited

    now[0] += 8                             # the user presses play again
    assert not _poll(acct, "sm-2"), "the poller reclaimed the source between retries"
    assert _play(acct), "the retry itself must never be held back"


def test_the_cooldown_expires_so_background_work_resumes():
    """Non-degeneracy: this must not permanently stop enrichment or monitoring."""
    now = [1000.0]
    acct = _acct(now)
    acct.note_foreground_use("p1")
    assert not _poll(acct, "sm-1")
    now[0] += ConnectionAccountant.PROVIDER_COOLDOWN_S + 1
    assert _poll(acct, "sm-2"), "background work never came back — that is a dead app"


def test_an_untouched_provider_is_never_held_back():
    """Non-degeneracy: a cooldown on one source must not gate another."""
    now = [1000.0]
    acct = _acct(now)
    acct.note_foreground_use("p1")
    assert acct.acquire("p2", MONITOR_KIND, "sm-1",
                        preempt_kinds=MONITOR_PREEMPTS).granted


def test_playing_arms_the_cooldown_even_without_the_explicit_claim():
    """A play that reaches the player directly still protects its own retry."""
    now = [1000.0]
    acct = _acct(now)
    assert _play(acct)
    assert not _poll(acct, "sm-1")


def test_recording_is_foreground_too_and_downloads_are_not():
    """The axis is 'someone is waiting', which is the recoverability rule.

    A recording cannot be re-run later, so it is never held back. A download
    can: its scheduler simply does not pick the row this tick and tries again.
    """
    now = [1000.0]
    acct = _acct(now)
    acct.note_foreground_use("p1")
    assert acct.acquire("p1", "recording", "rec-1").granted, (
        "a recording was held back — the live moment does not come round again")

    now = [1000.0]
    acct2 = _acct(now)
    acct2.note_foreground_use("p1")
    assert not acct2.acquire("p1", "download", "dl-1",
                             preempt_kinds=DOWNLOAD_PREEMPTS).granted


def test_an_already_registered_holder_is_never_evicted_by_the_cooldown():
    """A poll that is mid-call keeps its slot; the gate is on TAKING one.

    Re-acquiring an id it already holds must stay idempotent, or a consumer
    could lose a slot it believes it owns.
    """
    now = [1000.0]
    acct = _acct(now)
    assert _poll(acct, "sm-1")
    acct.note_foreground_use("p1")
    assert acct.acquire("p1", MONITOR_KIND, "sm-1",
                        preempt_kinds=MONITOR_PREEMPTS).granted


def test_cooldown_remaining_reports_the_wait():
    now = [1000.0]
    acct = _acct(now)
    assert acct.cooldown_remaining("p1") == 0.0
    acct.note_foreground_use("p1")
    assert acct.cooldown_remaining("p1") == ConnectionAccountant.PROVIDER_COOLDOWN_S
    now[0] += 20
    assert acct.cooldown_remaining("p1") == ConnectionAccountant.PROVIDER_COOLDOWN_S - 20


def test_the_injected_clock_is_the_only_clock():
    """Guard: a helper reaching for time.monotonic() underneath a supplied clock.

    That bug has been found three times in this codebase in one day, once
    silently deleting 29.75 days of data instead of 30.
    """
    now = [500.0]
    acct = _acct(now)
    acct.note_foreground_use("p1")
    # Real monotonic is nowhere near 500; if anything read it, the cooldown
    # would already look long expired.
    assert acct.cooldown_remaining("p1") == ConnectionAccountant.PROVIDER_COOLDOWN_S


# ---------------------------------------------------------------------------
# The play path actually calls it, before the probe
# ---------------------------------------------------------------------------


def test_play_media_claims_the_source_before_submitting_the_probe():
    """Ordering is the whole fix: claim, THEN probe."""
    import ast
    import pathlib

    src = pathlib.Path(__file__).resolve().parent.parent / "metatv/gui/main_window_streaming.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "play_media")

    claim_line = submit_line = None
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "claim_for_playback":
                claim_line = node.lineno
            elif node.func.attr == "submit" and submit_line is None:
                submit_line = node.lineno

    assert claim_line is not None, (
        "play_media no longer claims the source — the probe runs unprotected "
        "and the pollers take the slot out from under it")
    assert submit_line is not None
    assert claim_line < submit_line, (
        "the source is claimed AFTER the probe is dispatched, which leaves the "
        "~1.5s window this fix exists to close")


def test_player_manager_claim_is_a_no_op_without_a_provider():
    """Local files and provider-less plays must not blow up or gate anything."""
    from metatv.core.player_manager import PlayerManager
    pm = PlayerManager.__new__(PlayerManager)
    pm.connection_accountant = _acct([1000.0])
    pm.claim_for_playback(None)
    pm.claim_for_playback("")
    assert pm.connection_accountant.cooldown_remaining("p1") == 0.0


def test_a_multi_connection_provider_is_not_cooled():
    """Headroom means no cooldown — otherwise every play starves enrichment.

    The provider's lag only bites when there is no spare slot. With two or
    more, ordinary capacity arbitration and the #634 eviction listeners
    already cover it.
    """
    now = [1000.0]
    acct = ConnectionAccountant(capacity_resolver=lambda _p: 5, clock=lambda: now[0])
    acct.note_foreground_use("p1")
    assert acct.acquire("p1", MONITOR_KIND, "sm-1",
                        preempt_kinds=MONITOR_PREEMPTS).granted, (
        "held background work off a five-connection account — nothing was contended")


def test_an_unlimited_provider_is_not_cooled():
    now = [1000.0]
    acct = ConnectionAccountant(capacity_resolver=lambda _p: 0, clock=lambda: now[0])
    acct.note_foreground_use("p1")
    assert acct.acquire("p1", MONITOR_KIND, "sm-1",
                        preempt_kinds=MONITOR_PREEMPTS).granted


def test_mpv_retries_a_5xx_on_the_initial_open():
    """The three original reconnect options retry a DROP, not a failed open.

    On a one-connection account the common failure is a 5xx on the very first
    GET, while the provider still counts a background call it has not reaped.
    Without this mpv exits at once — the window opening and closing a few
    seconds later, which is exactly what the owner saw four times in a row.

    4xx is excluded on purpose: being told no must still fail fast.
    """
    from metatv.core.players.mpv import RECONNECT_FLAG

    assert "reconnect_on_http_error=5xx" in RECONNECT_FLAG
    assert "4xx" not in RECONNECT_FLAG, (
        "retrying a 401/403/404 for half a minute hides a real answer")
    # The originals must survive — they cover mid-stream drops, a different case.
    for opt in ("reconnect=1", "reconnect_streamed=1", "reconnect_delay_max=8"):
        assert opt in RECONNECT_FLAG, f"dropped {opt}"


def test_reconnect_delay_max_lowered_for_same_provider_switching():
    """PLAY-10: the per-attempt cap dropped 30 -> 8, so retries land inside the
    provider's own reaper window (#635 measured 14-26s) instead of past it.

    ffmpeg's backoff is uncapped 1,2,4,8,16s — with max=8 the schedule is
    +1,+3,+7,+15,+23s; the old max=30 let it reach +1,+3,+7,+15,+31s, one long
    wait past the reaper window instead of three extra tries inside it.
    """
    from metatv.core.players.mpv import RECONNECT_FLAG

    assert "reconnect_delay_max=30" not in RECONNECT_FLAG, (
        "reconnect_delay_max is back to 30 — same-provider switches will "
        "wait past the provider's reaper window again")
    assert "reconnect_delay_max=8" in RECONNECT_FLAG
