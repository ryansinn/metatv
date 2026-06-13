"""Tests for B7-3 — EPG view-switch count off-thread.

Pins these invariants on the REAL ``_NavMixin`` methods (bound via
``_NavMixin.__new__`` — no Qt, no DB), so a regression in the shipped code
breaks the test:

1. switch_to_epg_view sets stats_label to "EPG — counting…" immediately (no DB block).
2. switch_to_epg_view dispatches the count via _run_query with a token + on_error.
3. The query_fn captures provider_ids at call time (snapshot, not a live reference).
4. _on_epg_count_loaded formats the count, or shows "EPG — fetching…" when zero.
5. _on_epg_count_loaded / _on_epg_count_failed are no-ops once the user navigates away.
6. _on_epg_count_failed clears the "counting…" placeholder on failure.
7. EpgRepository.count_by_providers counts correctly over populated data.
"""
import pytest

from metatv.gui.main_window_nav import _NavMixin


# ---------------------------------------------------------------------------
# Minimal collaborators (no Qt, no DB)
# ---------------------------------------------------------------------------

class _FakeLabel:
    def __init__(self):
        self.text = ""

    def setText(self, t: str):
        self.text = t


class _FakeEpgView:
    _provider_ids = ["p1", "p2"]

    def setVisible(self, v): pass
    def on_activate(self): pass


def _make_host(view_mode: str = "list") -> _NavMixin:
    """Real _NavMixin instance with collaborators stubbed as instance attributes.

    ``switch_to_epg_view`` / ``_on_epg_count_loaded`` / ``_on_epg_count_failed``
    are NOT shadowed, so they resolve to the real class methods under test.
    ``_run_query`` (from _AsyncMixin) and ``_hide_all_content_views`` are stubbed.
    """
    host = _NavMixin.__new__(_NavMixin)
    host.view_mode = view_mode
    host.stats_label = _FakeLabel()
    host.epg_view = _FakeEpgView()
    host._epg_count_token = [0]
    host._run_query_calls = []

    def _fake_run_query(query_fn, on_result, *, token_ref=None, on_error=None):
        host._run_query_calls.append(
            {"query_fn": query_fn, "on_result": on_result,
             "token_ref": token_ref, "on_error": on_error}
        )

    host._run_query = _fake_run_query
    host._hide_all_content_views = lambda: None
    return host


# ---------------------------------------------------------------------------
# switch_to_epg_view (real method)
# ---------------------------------------------------------------------------

def test_switch_to_epg_sets_counting_immediately():
    """stats_label must read 'EPG — counting…' right after switch_to_epg_view."""
    host = _make_host()
    host.switch_to_epg_view()
    assert host.stats_label.text == "EPG — counting…"


def test_switch_to_epg_submits_background_query_with_error_handler():
    """switch_to_epg_view must call _run_query once with token_ref AND on_error."""
    host = _make_host()
    host.switch_to_epg_view()
    assert len(host._run_query_calls) == 1
    call = host._run_query_calls[0]
    assert call["on_result"] == host._on_epg_count_loaded
    assert call["token_ref"] is host._epg_count_token
    # Lesson 1: a loading placeholder is set, so on_error MUST be wired.
    assert call["on_error"] == host._on_epg_count_failed


def test_switch_to_epg_passes_provider_ids_snapshot():
    """The query_fn must capture provider_ids at call time (not a live reference)."""
    host = _make_host()
    host.switch_to_epg_view()
    call = host._run_query_calls[0]

    original_ids = list(host.epg_view._provider_ids)
    host.epg_view._provider_ids = ["new_only"]   # mutate after the call

    class _FakeEpgRepo:
        def __init__(self):
            self.called_with = []
        def count_by_providers(self, ids):
            self.called_with.append(ids)
            return 0

    class _FakeRepos:
        def __init__(self):
            self.epg = _FakeEpgRepo()

    repos = _FakeRepos()
    call["query_fn"](repos)
    assert repos.epg.called_with == [original_ids], (
        "query_fn must capture provider_ids at switch time, not a live reference"
    )


# ---------------------------------------------------------------------------
# _on_epg_count_loaded (real method)
# ---------------------------------------------------------------------------

def test_on_epg_count_loaded_updates_label_with_count():
    host = _make_host(view_mode="epg")
    host._on_epg_count_loaded(42000)
    assert host.stats_label.text == "42,000 EPG programmes"


def test_on_epg_count_loaded_shows_fetching_when_zero():
    host = _make_host(view_mode="epg")
    host._on_epg_count_loaded(0)
    assert host.stats_label.text == "EPG — fetching…"


def test_on_epg_count_loaded_noop_when_view_changed():
    host = _make_host(view_mode="list")   # navigated away before the count landed
    host.stats_label.setText("Showing 100 of 200 channels")
    host._on_epg_count_loaded(5000)
    assert host.stats_label.text == "Showing 100 of 200 channels"


# ---------------------------------------------------------------------------
# _on_epg_count_failed (real method — Lesson 1)
# ---------------------------------------------------------------------------

def test_on_epg_count_failed_clears_placeholder():
    """On failure the 'counting…' placeholder must not hang — it must be replaced."""
    host = _make_host(view_mode="epg")
    host.stats_label.setText("EPG — counting…")
    host._on_epg_count_failed(RuntimeError("database is locked"))
    assert host.stats_label.text == "EPG — count unavailable"


def test_on_epg_count_failed_noop_when_view_changed():
    """A late failure must not stomp the label after the user navigated away."""
    host = _make_host(view_mode="list")
    host.stats_label.setText("Showing 100 of 200 channels")
    host._on_epg_count_failed(RuntimeError("boom"))
    assert host.stats_label.text == "Showing 100 of 200 channels"


# ---------------------------------------------------------------------------
# EpgRepository.count_by_providers (real query over populated data — Lesson 4)
# ---------------------------------------------------------------------------

def test_count_by_providers_counts_populated_rows():
    """count_by_providers must return the exact count for the requested providers,
    excluding rows from other providers."""
    from datetime import datetime, timedelta
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from metatv.core.database import Base, EpgProgramDB
    from metatv.core.repositories import RepositoryFactory
    from metatv.core.repositories.epg import EpgRepository

    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    base = datetime(2024, 6, 1, 0, 0, 0)

    def _prog(i: int, provider_id: str) -> EpgProgramDB:
        return EpgProgramDB(
            channel_epg_id=f"ch_{provider_id}_{i}",
            provider_id=provider_id,
            title=f"Programme {i}",
            start_time=base + timedelta(hours=i),
            stop_time=base + timedelta(hours=i + 1),
        )

    # 3 rows for p1, 2 for p2, 5 decoy rows for p3 (must NOT be counted)
    for i in range(3):
        session.add(_prog(i, "p1"))
    for i in range(2):
        session.add(_prog(i, "p2"))
    for i in range(5):
        session.add(_prog(i, "p3"))
    session.commit()

    repos = RepositoryFactory(session)
    assert isinstance(repos.epg, EpgRepository)
    assert repos.epg.count_by_providers(["p1", "p2"]) == 5   # 3 + 2, p3 excluded
    assert repos.epg.count_by_providers(["p1"]) == 3
    assert repos.epg.count_by_providers(["p3"]) == 5
    assert repos.epg.count_by_providers([]) == 0
    assert repos.epg.count_by_providers(["nonexistent"]) == 0

    session.close()
    engine.dispose()
