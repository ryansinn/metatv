"""Tests for the startup provider-connectivity read moved off the main thread.

Watchdog stack sample (2026-09-02 15:42): ``MainWindow.__init__`` (main_window.py:624)
-> ``test_all_providers`` -> ``ProviderRepository.get_all`` -> a new SQLAlchemy pool
connection opened while startup workers already had the DB busy -> 2.3s frozen.

Pins these invariants on the REAL ``MainWindow`` methods (bound via ``__new__`` —
no Qt, no DB), the same harness as ``tests/test_filter_stats_async.py``:

1. ``test_all_providers`` does NOT open a DB session on the calling thread — it
   only calls ``_run_query`` and returns (``host.db`` is deliberately absent, so
   any ``get_session()`` call would raise ``AttributeError``).
2. The ``query_fn`` passed to ``_run_query`` reads ``get_all(active_only=True)``
   and converts every row via ``to_model`` (never returns ORM objects).
3. ``on_result`` is ``_on_test_all_providers_loaded``; ``on_error`` is provided
   (so a failed read is logged, not silently swallowed).
4. ``_on_test_all_providers_loaded`` starts a connection test for every provider
   in the loaded list — the main-thread half of the seam, unchanged behavior.
"""
from __future__ import annotations

from metatv.core.models import Provider
from metatv.gui.main_window import MainWindow


# ---------------------------------------------------------------------------
# Minimal host (no Qt, no DB) — mirrors tests/test_filter_stats_async.py
# ---------------------------------------------------------------------------

def _make_host() -> MainWindow:
    host = MainWindow.__new__(MainWindow)

    host._run_query_calls: list[dict] = []

    def _fake_run_query(query_fn, on_result, *, token_ref=None, on_error=None):
        host._run_query_calls.append(
            {"query_fn": query_fn, "on_result": on_result,
             "token_ref": token_ref, "on_error": on_error}
        )

    host._run_query = _fake_run_query

    # db is deliberately absent — a regression to the synchronous get_session()
    # path would raise AttributeError instead of silently passing.

    return host


# ---------------------------------------------------------------------------
# test_all_providers — dispatcher shape
# ---------------------------------------------------------------------------

def test_test_all_providers_does_not_open_session():
    """test_all_providers must not call db.get_session() on the calling thread."""
    host = _make_host()
    host.test_all_providers()  # must not raise (host.db is intentionally absent)


def test_test_all_providers_calls_run_query_once():
    host = _make_host()
    host.test_all_providers()
    assert len(host._run_query_calls) == 1


def test_test_all_providers_on_result_is_handler():
    host = _make_host()
    host.test_all_providers()
    call = host._run_query_calls[0]
    assert call["on_result"] == host._on_test_all_providers_loaded


def test_test_all_providers_passes_on_error():
    """Without on_error a failed read is dropped silently — must be wired."""
    host = _make_host()
    host.test_all_providers()
    call = host._run_query_calls[0]
    assert call["on_error"] is not None


def test_test_all_providers_query_fn_uses_get_all_and_to_model():
    """query_fn must call get_all(active_only=True) and convert every row via
    to_model — plain Provider domain objects, never ORM, cross the boundary."""
    host = _make_host()
    host.test_all_providers()
    query_fn = host._run_query_calls[0]["query_fn"]

    received_kwargs: list[dict] = []
    db_rows = ["db-row-1", "db-row-2"]
    converted = [
        Provider(id="p1", name="P1", type="xtream", url="http://a"),
        Provider(id="p2", name="P2", type="xtream", url="http://b"),
    ]

    class _FakeProviderRepo:
        def get_all(self, **kwargs):
            received_kwargs.append(kwargs)
            return db_rows

        def to_model(self, db_row):
            return converted[db_rows.index(db_row)]

    class _FakeRepos:
        providers = _FakeProviderRepo()

    result = query_fn(_FakeRepos())

    assert received_kwargs == [{"active_only": True}]
    assert result == converted
    assert all(isinstance(p, Provider) for p in result), (
        "query_fn must return plain Provider domain objects, never ORM rows"
    )


# ---------------------------------------------------------------------------
# _on_test_all_providers_loaded — main-thread handler
# ---------------------------------------------------------------------------

def test_on_test_all_providers_loaded_starts_a_test_per_provider():
    host = _make_host()
    status_calls: list[tuple[str, str]] = []
    test_calls: list[str] = []
    host.update_provider_status = lambda pid, status: status_calls.append((pid, status))
    host.test_provider_connection = lambda pid: test_calls.append(pid)

    providers = [
        Provider(id="p1", name="P1", type="xtream", url="http://a"),
        Provider(id="p2", name="P2", type="xtream", url="http://b"),
    ]
    host._on_test_all_providers_loaded(providers)

    assert status_calls == [("p1", "testing"), ("p2", "testing")]
    assert test_calls == ["p1", "p2"]


def test_on_test_all_providers_loaded_empty_list_is_a_noop():
    host = _make_host()
    host.update_provider_status = lambda pid, status: (_ for _ in ()).throw(
        AssertionError("must not be called for an empty provider list")
    )
    host.test_provider_connection = lambda pid: (_ for _ in ()).throw(
        AssertionError("must not be called for an empty provider list")
    )
    host._on_test_all_providers_loaded([])  # must not raise
