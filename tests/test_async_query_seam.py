"""Tests for _AsyncMixin / _run_query async-read seam (B7-1).

Pins two invariants:
1. query_fn runs in a thread other than the calling thread.
2. A result whose token no longer matches token_ref[0] is silently dropped.

No Qt event loop required — _query_result.emit is stubbed with a plain list.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from metatv.gui.main_window_async import _AsyncMixin, _QueryResult


# ---------------------------------------------------------------------------
# Minimal host class (no Qt)
# ---------------------------------------------------------------------------

class _FakeSignal:
    """Stand-in for pyqtSignal(object) — records emit() calls."""
    def __init__(self):
        self.emitted: list = []

    def emit(self, value):
        self.emitted.append(value)


def _make_subject() -> _AsyncMixin:
    """Create an _AsyncMixin instance with mocked db and executor."""
    subject = _AsyncMixin.__new__(_AsyncMixin)
    subject.executor = ThreadPoolExecutor(max_workers=2)
    subject._query_result = _FakeSignal()

    # Mock db.session_scope() as a no-op context manager
    mock_session = MagicMock()
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=mock_session)
    cm.__exit__ = MagicMock(return_value=False)
    db = MagicMock()
    db.session_scope.return_value = cm
    subject.db = db

    return subject


# ---------------------------------------------------------------------------
# B7-1a — off-thread dispatch
# ---------------------------------------------------------------------------

def test_run_query_runs_off_main_thread():
    """query_fn must execute in a thread other than the calling thread."""
    subject = _make_subject()
    main_thread_id = threading.get_ident()
    worker_thread_ids: list[int] = []

    def query_fn(repos):
        worker_thread_ids.append(threading.get_ident())
        return 42

    subject._run_query(query_fn, lambda d: None)
    subject.executor.shutdown(wait=True)

    assert worker_thread_ids, "query_fn was never called"
    assert all(tid != main_thread_id for tid in worker_thread_ids), (
        f"query_fn ran on the main thread: {worker_thread_ids}"
    )


def test_run_query_emits_result_to_signal():
    """Result from query_fn must be emitted via _query_result with the correct data."""
    subject = _make_subject()
    returned_data = {"answer": 42}

    def query_fn(repos):
        return returned_data

    subject._run_query(query_fn, lambda d: None)
    subject.executor.shutdown(wait=True)

    assert len(subject._query_result.emitted) == 1
    result = subject._query_result.emitted[0]
    assert isinstance(result, _QueryResult)
    assert result.data is returned_data


def test_run_query_delivers_result_to_on_result():
    """_on_query_result must call on_result(data) for a non-stale result."""
    subject = _make_subject()
    received: list = []

    def query_fn(repos):
        return "hello"

    def on_result(data):
        received.append(data)

    subject._run_query(query_fn, on_result)
    subject.executor.shutdown(wait=True)

    # Simulate Qt dispatching the signal to the slot
    for queued in subject._query_result.emitted:
        subject._on_query_result(queued)

    assert received == ["hello"]


# ---------------------------------------------------------------------------
# B7-1b — stale-token drop
# ---------------------------------------------------------------------------

def test_on_query_result_drops_stale_token():
    """_on_query_result must silently drop results whose token != token_ref[0]."""
    subject = _AsyncMixin.__new__(_AsyncMixin)
    token_ref = [2]   # current generation is 2
    received: list = []

    stale = _QueryResult(
        on_result=lambda data: received.append(data),
        data="stale",
        token=1,          # issued at generation 1 — now superseded
        token_ref=token_ref,
    )
    subject._on_query_result(stale)

    assert received == [], "stale result must be dropped"


def test_on_query_result_delivers_fresh_token():
    """_on_query_result must call on_result when token matches token_ref[0]."""
    subject = _AsyncMixin.__new__(_AsyncMixin)
    token_ref = [3]
    received: list = []

    fresh = _QueryResult(
        on_result=lambda data: received.append(data),
        data="fresh",
        token=3,          # matches current generation
        token_ref=token_ref,
    )
    subject._on_query_result(fresh)

    assert received == ["fresh"]


def test_on_query_result_delivers_when_no_token_ref():
    """Without a token_ref, _on_query_result always delivers (no staleness check)."""
    subject = _AsyncMixin.__new__(_AsyncMixin)
    received: list = []

    result = _QueryResult(
        on_result=lambda data: received.append(data),
        data="no-token",
        token=None,
        token_ref=None,
    )
    subject._on_query_result(result)

    assert received == ["no-token"]


def test_run_query_increments_token_ref_before_submit():
    """_run_query must increment token_ref[0] before submitting the worker."""
    subject = _make_subject()
    token_ref = [0]

    subject._run_query(lambda repos: None, lambda d: None, token_ref=token_ref)
    subject.executor.shutdown(wait=True)

    assert token_ref[0] == 1, f"Expected token_ref[0]=1, got {token_ref[0]}"


def test_worker_exception_does_not_raise_and_emits_error_envelope():
    """A raising query_fn must not crash the worker; it emits an error envelope."""
    subject = _make_subject()

    def boom(repos):
        raise ValueError("db exploded")

    subject._run_query(boom, lambda d: None)
    subject.executor.shutdown(wait=True)

    assert len(subject._query_result.emitted) == 1
    env = subject._query_result.emitted[0]
    assert isinstance(env.error, ValueError)
    assert env.data is None


def test_on_error_invoked_on_failure():
    """_on_query_result must route a failed result to on_error, not on_result."""
    subject = _make_subject()
    results: list = []
    errors: list = []

    def boom(repos):
        raise RuntimeError("nope")

    subject._run_query(
        boom,
        lambda d: results.append(d),
        on_error=lambda e: errors.append(e),
    )
    subject.executor.shutdown(wait=True)

    for queued in subject._query_result.emitted:
        subject._on_query_result(queued)

    assert results == [], "on_result must not fire on failure"
    assert len(errors) == 1 and isinstance(errors[0], RuntimeError)


def test_on_error_omitted_failure_is_silently_dropped():
    """Without on_error, a failed result is dropped (no on_result, no raise)."""
    subject = _make_subject()
    results: list = []

    subject._run_query(
        lambda repos: (_ for _ in ()).throw(KeyError("x")),
        lambda d: results.append(d),
    )
    subject.executor.shutdown(wait=True)

    for queued in subject._query_result.emitted:
        subject._on_query_result(queued)   # must not raise

    assert results == []


def test_stale_error_result_dropped():
    """A failed result is also subject to the stale-token drop."""
    subject = _AsyncMixin.__new__(_AsyncMixin)
    token_ref = [2]
    errors: list = []

    stale_err = _QueryResult(
        on_result=lambda d: None,
        data=None,
        token=1,            # superseded
        token_ref=token_ref,
        on_error=lambda e: errors.append(e),
        error=RuntimeError("stale failure"),
    )
    subject._on_query_result(stale_err)

    assert errors == [], "stale failure must be dropped before on_error fires"


def test_stale_result_dropped_when_superseded():
    """Result from a superseded call must be dropped after token_ref is advanced."""
    subject = _make_subject()
    token_ref = [0]
    received: list = []

    subject._run_query(lambda repos: "old", lambda d: received.append(d), token_ref=token_ref)
    subject.executor.shutdown(wait=True)

    # Advance the token to simulate a second query being submitted after the first
    token_ref[0] += 1

    # Now dispatch the emitted result — it is stale
    for queued in subject._query_result.emitted:
        subject._on_query_result(queued)

    assert received == [], "superseded result must be dropped"
