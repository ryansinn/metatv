"""The signal-check scheduler: lowest priority, and evidence discipline.

Two things carry the design and both are easy to get wrong in a way no
smoke test would notice.

**Priority.** A probe is speculative work on the connection the user may want
at any instant. It evicts nobody and everybody evicts it. Getting that backwards
means a Play press waits on a probe.

**Evidence.** Only a verdict ABOUT THE PICTURE may move the dead streak. A
refused connection, an unreachable host, a missing ffmpeg and — above all — a
probe cancelled to give the stream back to a Play press all say the probe never
saw the picture. Counting any of them would let ordinary viewing accumulate a
dead streak against a working channel, and ``hide_dead_events`` would then hide
it. That is a bug which would look exactly like the provider being bad.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from metatv.core.connection_accountant import ConnectionAccountant
from metatv.core.database import ChannelDB, Database
from metatv.core.epg_utils import now_utc
from metatv.core.signal_check_manager import (PROBE_PREEMPTS,
                                              SignalCheckManager)
from metatv.core.stream_probe import (BLACK, CANCELLED, DEAD, GONE, LIVE,
                                      REFUSED, UNKNOWN, ProbeResult)


@pytest.fixture
def db(tmp_path):
    """A real Database on a real file — :memory: is forbidden for session work."""
    database = Database(f"sqlite:///{tmp_path / 'sig.db'}")
    database.create_tables()
    return database


@pytest.fixture
def config():
    return SimpleNamespace(
        signal_sample_seconds=4, signal_black_fraction=0.5,
        signal_black_pixel_threshold=0.1, signal_freeze_seconds=2)


@pytest.fixture
def accountant():
    return ConnectionAccountant(capacity_resolver=lambda _pid: 1)


@pytest.fixture
def manager(db, config, accountant):
    return SignalCheckManager(db, config, accountant)


def _add(db, cid, *, minutes_ago=30, streak=0, checked=None):
    with db.session_scope() as session:
        session.add(ChannelDB(
            id=cid, source_id=cid.split("_")[-1], provider_id="p1",
            name=f"Event {cid}", stream_url=f"http://x/{cid}.ts",
            event_start_time=now_utc() - timedelta(minutes=minutes_ago),
            signal_dead_streak=streak, signal_checked_at=checked))


# ── priority ────────────────────────────────────────────────────────────────

def test_a_probe_evicts_nobody(accountant):
    """Stated as a constant so the asymmetry is greppable, and asserted here."""
    assert PROBE_PREEMPTS == ()

    accountant.acquire("p1", "download", "dl-1")
    result = accountant.acquire("p1", "probe", "probe:1",
                                preempt_kinds=PROBE_PREEMPTS)

    assert not result.granted, "a probe displaced a download"


def test_playback_takes_the_connection_from_a_probe(accountant):
    """A Play press must never wait on speculative work."""
    from metatv.core.player_manager import PLAYBACK_PREEMPTS

    assert accountant.acquire("p1", "probe", "probe:1").granted

    result = accountant.acquire("p1", "playback", "play",
                                preempt_kinds=PLAYBACK_PREEMPTS)

    assert result.granted
    assert result.preempted == ("probe:1",)
    assert "probe" in PLAYBACK_PREEMPTS


def test_a_probe_does_not_run_while_something_is_playing(manager, accountant, db):
    _add(db, "p1_1")
    accountant.acquire("p1", "playback", "watching")

    assert manager._probe(manager._next_candidate()) is False


def test_being_preempted_cancels_the_running_probe(manager):
    """Killing ffmpeg is what makes a probe acceptable on one connection.

    Without it the Play press waits for the sample plus the timeout margin —
    about eighteen seconds.
    """
    manager.on_preempted("p1", "probe:p1_1", "probe")
    assert manager._cancel.is_set()


def test_a_preempt_for_someone_elses_holder_is_ignored(manager):
    """The accountant reports every eviction; only ours is ours to cancel."""
    manager.on_preempted("p1", "download:abc", "download")
    assert not manager._cancel.is_set()


# ── what counts as evidence ─────────────────────────────────────────────────

@pytest.mark.parametrize("verdict", [DEAD, BLACK])
def test_a_picture_verdict_increments_the_streak(manager, db, verdict):
    _add(db, "p1_1", streak=1)
    manager._record({"id": "p1_1", "name": "x"}, ProbeResult(verdict=verdict))
    with db.session_scope() as session:
        row = session.get(ChannelDB, "p1_1")
        assert row.signal_dead_streak == 2
        assert row.signal_verdict == verdict


@pytest.mark.parametrize("verdict", [CANCELLED, REFUSED, GONE, UNKNOWN])
def test_an_inconclusive_verdict_never_moves_the_streak(manager, db, verdict):
    """The bug this prevents would look exactly like a bad provider.

    Every Play press cancels the probe in flight. If that counted, a channel
    would earn a dead streak *because the user keeps watching things*, and
    hide_dead_events would hide it.
    """
    _add(db, "p1_1", streak=1)

    manager._record({"id": "p1_1", "name": "x"}, ProbeResult(verdict=verdict))

    with db.session_scope() as session:
        row = session.get(ChannelDB, "p1_1")
        assert row.signal_dead_streak == 1, (
            f"{verdict!r} was counted as evidence about the picture")
        assert row.signal_verdict == verdict, "the verdict is still recorded"


def test_a_live_verdict_clears_the_streak(manager, db):
    """A channel that comes good must stop being treated as dead."""
    _add(db, "p1_1", streak=5)
    manager._record({"id": "p1_1", "name": "x"}, ProbeResult(verdict=LIVE))
    with db.session_scope() as session:
        assert session.get(ChannelDB, "p1_1").signal_dead_streak == 0


def test_every_verdict_stamps_the_check_time(manager, db):
    """Including the inconclusive ones.

    Otherwise a channel whose provider keeps refusing is retried every twenty
    seconds forever, spending the connection on a question it cannot answer.
    """
    _add(db, "p1_1")
    manager._record({"id": "p1_1", "name": "x"}, ProbeResult(verdict=REFUSED))
    with db.session_scope() as session:
        assert session.get(ChannelDB, "p1_1").signal_checked_at is not None


# ── what is worth probing ───────────────────────────────────────────────────

def test_only_events_that_are_on_now_are_probed(manager, db):
    """A fixture six hours out has nothing behind it yet."""
    with db.session_scope() as session:
        session.add(ChannelDB(id="p1_future", source_id="9", provider_id="p1",
                              name="Tomorrow", stream_url="http://x/f.ts",
                              event_start_time=now_utc() + timedelta(hours=6)))
        session.add(ChannelDB(id="p1_old", source_id="8", provider_id="p1",
                              name="Last week", stream_url="http://x/o.ts",
                              event_start_time=now_utc() - timedelta(days=7)))
    assert manager._next_candidate() is None

    _add(db, "p1_now", minutes_ago=30)
    assert manager._next_candidate()["id"] == "p1_now"


def test_a_channel_with_no_start_time_is_never_probed(manager, db):
    """A 24/7 rack is a different question from "is this event streaming"."""
    with db.session_scope() as session:
        session.add(ChannelDB(id="p1_rack", source_id="7", provider_id="p1",
                              name="SKY SPORTS 1", stream_url="http://x/r.ts"))
    assert manager._next_candidate() is None


def test_a_recent_check_is_not_repeated(manager, db):
    _add(db, "p1_1", checked=now_utc())
    assert manager._next_candidate() is None


def test_the_stalest_check_goes_first(manager, db):
    """Never-checked before long-ago, and long-ago before recent."""
    _add(db, "p1_old", checked=now_utc() - timedelta(hours=5))
    _add(db, "p1_never", checked=None)

    assert manager._next_candidate()["id"] == "p1_never"


def test_start_is_a_no_op_without_ffmpeg(manager, monkeypatch):
    """No ffmpeg is not a failure state — it is a feature that cannot run."""
    import metatv.core.signal_check_manager as module

    monkeypatch.setattr(module, "ffmpeg_available", lambda: False)
    manager.start()
    assert manager._thread is None


# ── the wiring: one callback slot, three consumers ──────────────────────────

def test_the_preempt_callback_fans_out_to_every_manager():
    """`accountant._on_preempt` is ONE attribute and three managers want it.

    Assigning it twice silently replaces the first listener, and the loser just
    stops being told its slot was taken — a download never resumes, a probe
    keeps ffmpeg running against a stream the user is trying to watch. Nothing
    raises. It quietly stops working, which is why this is a test and not a
    comment.
    """
    import inspect

    from metatv.gui import main_window_downloads

    src = inspect.getsource(main_window_downloads._DownloadsMixin._setup_downloads)

    assert src.count("_on_preempt =") == 1, (
        "the accountant's single callback slot is assigned more than once — "
        "the earlier listener is silently discarded")
    assert "_preempt_listeners.append" in src
    assert src.count("_preempt_listeners.append") >= 2, (
        "fewer listeners registered than managers that need preempt notice")


def test_a_dispatched_preempt_reaches_each_listener_and_survives_a_raise():
    """One bad listener must not stop the others being told."""
    calls = []

    listeners = [
        lambda p, h, k: calls.append(("first", h)),
        lambda p, h, k: (_ for _ in ()).throw(RuntimeError("boom")),
        lambda p, h, k: calls.append(("third", h)),
    ]

    def dispatch(provider_id, holder_id, kind):
        for listener in listeners:
            try:
                listener(provider_id, holder_id, kind)
            except Exception:
                pass

    dispatch("p1", "download:7", "download")

    assert calls == [("first", "download:7"), ("third", "download:7")], (
        "a raising listener stopped the ones after it")


# ── hide_dead_events reaches the query ─────────────────────────────────────

def test_hiding_dead_events_never_hides_an_unchecked_one(db):
    """NULL is "never looked at", not "known dead".

    An event nobody has probed must stay visible, or turning the setting on
    would hide most of the catalogue on day one — before a single check ran.
    """
    from metatv.core.channel_visibility import VisibilityScope
    from metatv.core.repositories import RepositoryFactory

    with db.session_scope() as session:
        for cid, streak in (("p1_never", None), ("p1_ok", 0),
                            ("p1_one", 1), ("p1_dead", 3)):
            session.add(ChannelDB(
                id=cid, source_id=cid, provider_id="p1", name=f"Event {cid}",
                stream_url="http://x/e.ts", special_view="live_event",
                signal_dead_streak=streak))

    with db.session_scope() as session:
        repos = RepositoryFactory(session)
        scope = VisibilityScope()

        shown_off = {r.id for r in repos.channels.get_events_channels(
            scope, "live_event")}
        shown_on = {r.id for r in repos.channels.get_events_channels(
            scope, "live_event", hide_dead_streak=2)}

    assert shown_off == {"p1_never", "p1_ok", "p1_one", "p1_dead"}, (
        "the default must hide nothing")
    assert "p1_never" in shown_on, "an unchecked event was hidden"
    assert "p1_one" in shown_on, "one bad check is a bad moment, not a fact"
    assert "p1_dead" not in shown_on, "a 3-check dead streak was not hidden"
