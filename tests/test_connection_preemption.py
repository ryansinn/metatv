"""Playback may displace a download, and must never displace a recording.

The priority axis is **recoverability, not foreground**. A download yields
because the VOD is still there in an hour; a scheduled recording does not,
because the moment is gone forever. So a recording that cannot get its slot is
a decision the user has to make with their eyes open, not a silent death while
they start something else.

This matters concretely rather than theoretically: every one of the owner's
three providers reports ``max_connections = 1``, so a download and a playback
on the same source are *always* in contention — there is no slack to hide in.

Arbitration lives in the accountant rather than in ``PlayerManager``, so the
player never has to know what a download is. The consumer learns it was evicted
through an injected callback, the same shape as the existing
``capacity_resolver`` injection.
"""

from __future__ import annotations


from metatv.core.connection_accountant import ConnectionAccountant
from metatv.core.player_manager import PLAYBACK_PREEMPTS


def _one_slot(_provider_id: str) -> int:
    """The owner's real configuration: every provider allows exactly one."""
    return 1


# ── what playback declares ──────────────────────────────────────────────────

def test_playback_preempts_downloads_and_only_downloads():
    assert "download" in PLAYBACK_PREEMPTS
    assert "recording" not in PLAYBACK_PREEMPTS, (
        "a scheduled recording must not be killed to start a playback — the "
        "moment is gone, the VOD is not"
    )


# ── the accountant ──────────────────────────────────────────────────────────

def test_a_caller_that_asks_for_nothing_evicts_nothing():
    """The default must leave every existing caller behaving exactly as before."""
    a = ConnectionAccountant(_one_slot)
    a.acquire("p", "download", "dl1")
    result = a.acquire("p", "playback", "pb1")
    assert result.granted is False
    assert result.preempted == ()
    assert [h.holder_id for h in a.holders("p")] == ["dl1"]


def test_playback_takes_the_slot_from_a_download():
    a = ConnectionAccountant(_one_slot)
    a.acquire("p", "download", "dl1")

    result = a.acquire("p", "playback", "pb1", preempt_kinds=("download",))

    assert result.granted is True
    assert result.preempted == ("dl1",)
    assert [(h.holder_id, h.kind) for h in a.holders("p")] == [("pb1", "playback")]


def test_a_recording_keeps_its_slot_against_playback():
    """The whole point of the recoverability axis."""
    a = ConnectionAccountant(_one_slot)
    a.acquire("p", "recording", "rec1")

    result = a.acquire("p", "playback", "pb1", preempt_kinds=PLAYBACK_PREEMPTS)

    assert result.granted is False
    assert [h.holder_id for h in a.holders("p")] == ["rec1"]


def test_only_as_many_holders_are_evicted_as_are_needed():
    """A second download must not be cancelled to admit one playback."""
    a = ConnectionAccountant(lambda _p: 2)
    a.acquire("p", "download", "dl1")
    a.acquire("p", "download", "dl2")

    result = a.acquire("p", "playback", "pb1", preempt_kinds=("download",))

    assert result.granted is True
    assert len(result.preempted) == 1, "evicting both would be gratuitous"
    assert result.preempted == ("dl1",), "the least recently registered goes first"
    assert {h.holder_id for h in a.holders("p")} == {"dl2", "pb1"}


def test_a_partial_eviction_that_still_cannot_grant_is_rolled_back():
    """Killing a download for a play that then fails anyway is the worst outcome.

    Reaching this needs capacity to SHRINK below the holders already registered —
    which happens for real when a provider's ``max_connections`` is edited down,
    or when the resolver starts answering differently. Three holders, capacity
    drops to one, and only ONE of them may be evicted: not enough, so the
    download that was already taken has to go back.
    """
    capacity = {"value": 3}
    a = ConnectionAccountant(lambda _p: capacity["value"])
    a.acquire("p", "download", "dl1")
    a.acquire("p", "recording", "rec1")
    a.acquire("p", "recording", "rec2")
    before = {(h.holder_id, h.kind) for h in a.holders("p")}

    capacity["value"] = 1          # the provider's limit is edited down

    result = a.acquire("p", "playback", "pb1", preempt_kinds=("download",))

    assert result.granted is False, "one eviction cannot free three slots"
    assert {(h.holder_id, h.kind) for h in a.holders("p")} == before, (
        "the download must be put back — it was cancelled for a grant that "
        "never happened"
    )


def test_re_acquiring_the_same_holder_still_never_double_counts():
    """The reused-window case, unchanged by preemption."""
    a = ConnectionAccountant(_one_slot)
    a.acquire("p", "playback", "pb1")
    assert a.acquire("p", "playback", "pb1", preempt_kinds=("download",)).granted is True
    assert a.in_use("p") == 1


def test_unlimited_capacity_never_preempts():
    a = ConnectionAccountant(lambda _p: 0)
    a.acquire("p", "download", "dl1")
    result = a.acquire("p", "playback", "pb1", preempt_kinds=("download",))
    assert result.granted is True
    assert result.preempted == (), "there was room; nobody had to be evicted"


# ── the consumer is told ────────────────────────────────────────────────────

def test_the_evicted_consumer_is_notified_with_enough_to_act_on():
    told: list[tuple[str, str, str]] = []
    a = ConnectionAccountant(_one_slot, on_preempt=lambda p, h, k: told.append((p, h, k)))
    a.acquire("p", "download", "dl1")

    a.acquire("p", "playback", "pb1", preempt_kinds=("download",))

    assert told == [("p", "dl1", "download")], (
        "a download manager needs the provider AND its own holder id to pause "
        "the right transfer"
    )


def test_nobody_is_notified_when_there_was_simply_room():
    told = []
    a = ConnectionAccountant(lambda _p: 2, on_preempt=lambda *args: told.append(args))
    a.acquire("p", "download", "dl1")
    a.acquire("p", "playback", "pb1", preempt_kinds=("download",))
    assert told == [], "silence when nothing was taken — the user hears nothing"


def test_a_failing_callback_cannot_break_the_grant():
    """The consumer is caller-supplied; a bug in it must not cost the playback."""
    def boom(*_args):
        raise RuntimeError("consumer exploded")

    a = ConnectionAccountant(_one_slot, on_preempt=boom)
    a.acquire("p", "download", "dl1")

    result = a.acquire("p", "playback", "pb1", preempt_kinds=("download",))

    assert result.granted is True
    assert [h.holder_id for h in a.holders("p")] == ["pb1"]


def test_preemption_is_per_provider():
    """Downloads on source B keep running while you watch source A."""
    a = ConnectionAccountant(_one_slot)
    a.acquire("A", "download", "dlA")
    a.acquire("B", "download", "dlB")

    a.acquire("A", "playback", "pb", preempt_kinds=("download",))

    assert [h.holder_id for h in a.holders("B")] == ["dlB"], (
        "a play on A must not touch B's download"
    )
