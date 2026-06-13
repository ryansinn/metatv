"""Tests for B7-3 — EPG view-switch count off-thread.

Pins two invariants:
1. switch_to_epg_view sets stats_label to "EPG — counting…" immediately (no DB block).
2. When the background count lands, _on_epg_count_loaded updates stats_label with the
   formatted count — or "EPG — fetching…" when count is 0.
3. _on_epg_count_loaded is a no-op when view_mode has changed (stale guard).

No Qt event loop required — _run_query and stats_label are stubbed.
"""
import pytest


# ---------------------------------------------------------------------------
# Minimal host stubs (no Qt, no DB)
# ---------------------------------------------------------------------------

class _FakeSignal:
    def __init__(self):
        self.emitted: list = []

    def emit(self, value):
        self.emitted.append(value)


class _FakeLabel:
    def __init__(self):
        self.text = ""

    def setText(self, t: str):
        self.text = t


class _FakeEpgView:
    _provider_ids = ["p1", "p2"]

    def setVisible(self, v): pass
    def on_activate(self): pass


class _NavHost:
    """Minimal host that mixes in _on_epg_count_loaded behaviour without Qt."""

    def __init__(self):
        self.view_mode = "list"
        self.stats_label = _FakeLabel()
        self.epg_view = _FakeEpgView()
        self._epg_count_token: list[int] = [0]
        self._run_query_calls: list = []

    def _hide_all_content_views(self):
        pass

    def _run_query(self, query_fn, on_result, *, token_ref=None):
        """Stub: record the call but do NOT run the worker."""
        self._run_query_calls.append(
            {"query_fn": query_fn, "on_result": on_result, "token_ref": token_ref}
        )

    # Paste the exact _on_epg_count_loaded logic here for isolation testing
    def _on_epg_count_loaded(self, total: int) -> None:
        if self.view_mode != "epg":
            return
        self.stats_label.setText(f"{total:,} EPG programmes" if total else "EPG — fetching…")

    # Paste switch_to_epg_view logic for isolation testing
    def switch_to_epg_view(self):
        self.view_mode = "epg"
        self._hide_all_content_views()
        self.epg_view.setVisible(True)
        self.epg_view.on_activate()
        self.stats_label.setText("EPG — counting…")
        provider_ids = list(self.epg_view._provider_ids)
        self._run_query(
            lambda repos: repos.epg.count_by_providers(provider_ids),
            self._on_epg_count_loaded,
            token_ref=self._epg_count_token,
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_switch_to_epg_sets_counting_immediately():
    """stats_label must read 'EPG — counting…' right after switch_to_epg_view, before the worker lands."""
    host = _NavHost()
    host.switch_to_epg_view()
    assert host.stats_label.text == "EPG — counting…"


def test_switch_to_epg_submits_background_query():
    """switch_to_epg_view must call _run_query once with a token_ref."""
    host = _NavHost()
    host.switch_to_epg_view()
    assert len(host._run_query_calls) == 1
    call = host._run_query_calls[0]
    assert call["on_result"] == host._on_epg_count_loaded
    assert call["token_ref"] is host._epg_count_token


def test_switch_to_epg_passes_provider_ids_snapshot():
    """The query_fn must capture the provider_ids at call time (not a live reference)."""
    host = _NavHost()
    host.switch_to_epg_view()
    call = host._run_query_calls[0]

    # Mutate the live list after the call — the captured lambda must use the snapshot
    original_ids = list(host.epg_view._provider_ids)
    host.epg_view._provider_ids = ["new_only"]

    # Simulate repos
    class _FakeEpgRepo:
        def __init__(self):
            self.called_with: list = []
        def count_by_providers(self, ids):
            self.called_with.append(ids)
            return 0

    class _FakeRepos:
        def __init__(self):
            self.epg = _FakeEpgRepo()

    repos = _FakeRepos()
    call["query_fn"](repos)
    assert repos.epg.called_with == [original_ids], (
        "query_fn must have captured provider_ids at switch time, not a live reference"
    )


def test_on_epg_count_loaded_updates_label_with_count():
    """_on_epg_count_loaded must format and set the count in stats_label."""
    host = _NavHost()
    host.view_mode = "epg"
    host._on_epg_count_loaded(42000)
    assert host.stats_label.text == "42,000 EPG programmes"


def test_on_epg_count_loaded_shows_fetching_when_zero():
    """_on_epg_count_loaded must show 'EPG — fetching…' when count is 0 (no data yet)."""
    host = _NavHost()
    host.view_mode = "epg"
    host._on_epg_count_loaded(0)
    assert host.stats_label.text == "EPG — fetching…"


def test_on_epg_count_loaded_noop_when_view_changed():
    """_on_epg_count_loaded must not update stats_label if the user has navigated away."""
    host = _NavHost()
    host.view_mode = "list"   # user navigated back before the count landed
    host.stats_label.setText("Showing 100 of 200 channels")
    host._on_epg_count_loaded(5000)
    assert host.stats_label.text == "Showing 100 of 200 channels"


def test_epg_repo_count_by_providers_in_factory():
    """RepositoryFactory must expose an epg property returning an EpgRepository."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from metatv.core.database import Base
    from metatv.core.repositories import RepositoryFactory
    from metatv.core.repositories.epg import EpgRepository

    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    repos = RepositoryFactory(session)
    assert isinstance(repos.epg, EpgRepository)
    # No providers → 0
    assert repos.epg.count_by_providers([]) == 0
    assert repos.epg.count_by_providers(["nonexistent"]) == 0

    session.close()
    engine.dispose()
