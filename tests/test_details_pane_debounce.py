"""One gesture must render the details pane once, not twice.

Owner's log (2026-09-02 15:44:02): one selection produced TWO complete
render+fetch cycles for the same channel 185ms apart — two
``update_details_pane_for_channel`` calls, two ``fetch_metadata`` threads,
two pane renders. PR #680 fixed the LIST's own click/selection double
(``_show_details_for_clicked_row``, covered by
``test_details_pane_rendered_once.py``), but ``show_channel_details_by_id``
— the entry every sidebar section, ``version_selected``, and programmatic
path uses — has no dedupe of its own, so a gesture that reaches the pane
through two surfaces at once renders it twice.

The fix lives at ``update_details_pane_for_channel``, the ONE chokepoint
every path funnels through: suppress a re-render of the SAME channel that
starts within ``_RERENDER_DEBOUNCE_S`` of the last one. Gated on TIME, not
on the channel id alone — #680's record is that id-gating breaks
click-again-to-refresh, the deliberate escape hatch a stale pane relies on.

UI-11 (owner's log 2026-09-05 06:39-06:41): the SAME channel id re-rendered
twelve times in 100s, with pairs landing 350-500ms apart (two surfaces
firing for one gesture) — past the original 300ms window. Two changes:

1. A same-title NO-OP: once metadata for the shown id has landed
   (``_details_shown = (id, True)``), a repeat request for that id renders
   nothing and fetches nothing — no timer needed, since the title is
   settled. ``force=True`` bypasses this (and the debounce below) outright.
2. While metadata for the shown id is STILL LOADING, the time debounce
   widens from 0.3s to 2.0s (``_RERENDER_DEBOUNCE_S``) to absorb the
   350-500ms pairs the owner measured — this window is only reachable
   pre-metadata now, since (1) already catches the settled case.

Also covered here: the provider-URL failover lookup (previously a
synchronous ``session_scope()`` + ``get_by_id()`` on the calling thread
inside ``update_details_pane_for_channel``) now runs off-thread through the
``_run_query`` seam.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from metatv.core.models import MediaType


CHANNEL_A = "prov1_chA"
CHANNEL_B = "prov1_chB"


class _FakeFuture:
    def add_done_callback(self, cb):
        pass


class _RecordingExecutor:
    """Stands in for MainWindow.executor — records submissions without
    actually running the submitted work (no event loop / metadata_manager /
    real _run_query worker needed to prove the debounce and no-op gates,
    which fire before any of that is reached)."""

    def __init__(self):
        self.submit_calls = 0

    def submit(self, fn, *args, **kwargs):
        self.submit_calls += 1
        return _FakeFuture()


class _FakeSignal:
    """Stand-in for pyqtSignal(object) — records emit() calls without a Qt
    event loop, same shape as tests/test_async_query_seam.py's double."""

    def __init__(self):
        self.emitted: list = []

    def emit(self, value):
        self.emitted.append(value)


class _DetailsPaneDouble:
    def __init__(self):
        self.shown: list[str] = []
        self.current_channel = None

    def set_provider_urls(self, urls):
        pass

    def show_channel(self, channel, metadata=None):
        self.current_channel = channel
        self.shown.append(channel.id)


@pytest.fixture()
def db(tmp_path: Path):
    from metatv.core.database import Database

    d = Database(f"sqlite:///{tmp_path / 'details_pane_debounce.db'}")
    d.create_tables()
    yield d
    d.close()


def _make_host(db_obj):
    """A plain host with the real update_details_pane_for_channel (and
    friends) bound — per CLAUDE.md's test-double rule, wired from the mixin
    itself rather than hand-copied, and using a real Database (session_scope
    work) on tmp_path. The executor is faked out (see _RecordingExecutor) so
    _run_query's worker body never actually runs — this lets the tests below
    count submissions without needing a Qt event loop or a metadata_manager.
    """
    from metatv.gui.main_window_async import _AsyncMixin
    from metatv.gui.main_window_metadata import _MetadataMixin

    host = SimpleNamespace()
    host.db = db_obj
    host.config = SimpleNamespace(metadata_auto_fetch=True)
    host.details_pane = _DetailsPaneDouble()
    host.executor = _RecordingExecutor()
    host._details_channel_token = [0]
    host._details_urls_token = [0]
    # _run_query is bound but never actually driven — _RecordingExecutor.submit
    # only counts the submission, it never invokes the worker body, so no
    # _query_result signal double is needed here (see _make_seam_host below
    # for the test that DOES drive the seam for real).
    host._run_query = _AsyncMixin._run_query.__get__(host)
    host.update_details_pane_for_channel = (
        _MetadataMixin.update_details_pane_for_channel.__get__(host)
    )
    host._update_details_with_metadata = (
        _MetadataMixin._update_details_with_metadata.__get__(host)
    )
    return host


def _make_seam_host(db_obj):
    """Host wired with the REAL _AsyncMixin (_run_query/_on_query_result) so
    the provider-URL lookup's worker body actually executes — driven
    synchronously the way tests/test_async_query_seam.py does: a real
    ThreadPoolExecutor, ``executor.shutdown(wait=True)`` to let the worker
    finish, then hand-dispatch the queued signal emissions to
    ``_on_query_result`` (no Qt event loop needed)."""
    from metatv.gui.main_window_async import _AsyncMixin
    from metatv.gui.main_window_metadata import _MetadataMixin

    host = SimpleNamespace()
    host.db = db_obj
    host.config = SimpleNamespace(metadata_auto_fetch=False)  # isolate the url fetch
    host.details_pane = _DetailsPaneDouble()
    host.executor = ThreadPoolExecutor(max_workers=2)
    host._query_result = _FakeSignal()
    host._details_channel_token = [0]
    host._details_urls_token = [0]
    host._run_query = _AsyncMixin._run_query.__get__(host)
    host._on_query_result = _AsyncMixin._on_query_result.__get__(host)
    host.update_details_pane_for_channel = (
        _MetadataMixin.update_details_pane_for_channel.__get__(host)
    )
    return host


def _drain(host):
    """Block until every submitted worker has finished, then hand its
    queued result to the main-thread slot — the synchronous stand-in for a
    Qt event loop dispatching _query_result."""
    host.executor.shutdown(wait=True)
    for queued in host._query_result.emitted:
        host._on_query_result(queued)


def _channel(channel_id: str):
    return SimpleNamespace(
        id=channel_id, name=channel_id, provider_id="prov1",
        media_type=MediaType.MOVIE,
    )


def _metadata():
    return SimpleNamespace(plot="a plot", cast=[])


# ---------------------------------------------------------------------------
# Time debounce (widened window, reachable only pre-metadata)
# ---------------------------------------------------------------------------

def test_duplicate_render_within_window_is_suppressed(db):
    """Two calls with the same channel back-to-back: the second is
    suppressed — no second render, no second fetch. Each full render submits
    two executor jobs (the provider-url _run_query + the metadata fetch), so
    one render == 2 submissions."""
    host = _make_host(db)
    ch = _channel(CHANNEL_A)

    host.update_details_pane_for_channel(ch)
    host.update_details_pane_for_channel(ch)

    assert host.details_pane.shown == [CHANNEL_A]
    assert host.executor.submit_calls == 2


def test_same_id_widened_window_while_metadata_pending(monkeypatch, db):
    """UI-11: while metadata for the id has not landed, a repeat request at
    0.5s is still suppressed (past the old 300ms window, inside the new
    2.0s one); one past 2.0s renders again — the click-again-to-refresh
    escape hatch, just at a wider interval."""
    import metatv.gui.main_window_metadata as mod

    clock = [100.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: clock[0])

    host = _make_host(db)
    ch = _channel(CHANNEL_A)

    host.update_details_pane_for_channel(ch)
    first_submits = host.executor.submit_calls

    clock[0] += 0.5  # past the OLD 300ms window, inside the new 2.0s one
    host.update_details_pane_for_channel(ch)
    assert host.details_pane.shown == [CHANNEL_A]
    assert host.executor.submit_calls == first_submits

    clock[0] += 2.0  # total 2.5s elapsed — past the widened window
    host.update_details_pane_for_channel(ch)
    assert host.details_pane.shown == [CHANNEL_A, CHANNEL_A]
    assert host.executor.submit_calls == first_submits * 2


def test_different_channel_renders_immediately(db):
    """Channel A then channel B immediately: both render — the debounce is
    keyed on the channel id, not a blanket cooldown."""
    host = _make_host(db)

    host.update_details_pane_for_channel(_channel(CHANNEL_A))
    host.update_details_pane_for_channel(_channel(CHANNEL_B))

    assert host.details_pane.shown == [CHANNEL_A, CHANNEL_B]
    assert host.executor.submit_calls == 4


# ---------------------------------------------------------------------------
# Same-title no-op (metadata already applied)
# ---------------------------------------------------------------------------

def test_same_id_after_metadata_applied_is_noop_until_force(db):
    """Once metadata has landed for the shown id, a repeat request for that
    SAME id renders nothing and fetches nothing — proven by driving the real
    metadata-applied path (_update_details_with_metadata) rather than poking
    internal state directly. force=True bypasses the no-op."""
    host = _make_host(db)
    ch = _channel(CHANNEL_A)

    host.update_details_pane_for_channel(ch)          # basic-info render: shown=[A]
    host._update_details_with_metadata(ch, _metadata())  # metadata render: shown=[A, A]
    assert host.details_pane.shown == [CHANNEL_A, CHANNEL_A]
    submits_after_first_render = host.executor.submit_calls

    # Same id, metadata already applied: no-op — shown list unchanged.
    host.update_details_pane_for_channel(ch)
    assert host.details_pane.shown == [CHANNEL_A, CHANNEL_A]
    assert host.executor.submit_calls == submits_after_first_render

    # force=True bypasses the no-op: renders (and fetches) again.
    host.update_details_pane_for_channel(ch, force=True)
    assert host.details_pane.shown == [CHANNEL_A, CHANNEL_A, CHANNEL_A]
    assert host.executor.submit_calls > submits_after_first_render


def test_different_id_always_renders_even_with_metadata_applied(db):
    """The same-title no-op is keyed on the id — a DIFFERENT id renders even
    while the previous id's metadata is fully applied."""
    host = _make_host(db)
    ch_a = _channel(CHANNEL_A)

    host.update_details_pane_for_channel(ch_a)
    host._update_details_with_metadata(ch_a, _metadata())

    host.update_details_pane_for_channel(_channel(CHANNEL_B))

    assert host.details_pane.shown == [CHANNEL_A, CHANNEL_A, CHANNEL_B]


# ---------------------------------------------------------------------------
# Off-main-thread provider-URL lookup (UI-11)
# ---------------------------------------------------------------------------

def test_provider_url_lookup_does_not_enter_session_scope_on_calling_thread(
    monkeypatch, db
):
    """The provider-URL failover lookup must not call session_scope() on the
    thread that called update_details_pane_for_channel — it must run on the
    _run_query executor. Proven by spying on Database.session_scope and
    recording which thread entered it, then draining the real seam the way
    tests/test_async_query_seam.py does."""
    from metatv.core.database import Database

    calling_thread = threading.current_thread()
    session_scope_threads: list[threading.Thread] = []
    real_session_scope = Database.session_scope

    def _spy_session_scope(self, *args, **kwargs):
        session_scope_threads.append(threading.current_thread())
        return real_session_scope(self, *args, **kwargs)

    monkeypatch.setattr(Database, "session_scope", _spy_session_scope)

    host = _make_seam_host(db)
    ch = _channel(CHANNEL_A)

    host.update_details_pane_for_channel(ch)  # kicks off the async url query
    _drain(host)

    assert session_scope_threads, "session_scope was never entered"
    assert calling_thread not in session_scope_threads, (
        "session_scope ran on the calling thread — the provider-url lookup "
        "must run on the _run_query executor"
    )


def test_provider_url_lookup_applies_result_to_the_pane(db):
    """The async result lands on set_provider_urls via the main-thread slot
    once the worker (and the manual drain) completes."""
    host = _make_seam_host(db)
    ch = _channel(CHANNEL_A)

    applied: list = []
    host.details_pane.set_provider_urls = lambda urls: applied.append(urls)

    host.update_details_pane_for_channel(ch)
    _drain(host)

    # No provider row exists for "prov1" in this empty db, so the query
    # resolves to an empty list — proving the round trip landed, not a stall.
    assert applied == [[]]
