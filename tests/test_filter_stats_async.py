"""Tests for perf/startup-filter-stats-async — filter stats moved off the UI thread.

Pins these invariants on the REAL ``MainWindow`` methods (bound via ``__new__``
— no Qt, no DB), so a regression in the shipped code breaks the test:

1. initialize_filter_stats does NOT open a DB session on the calling thread
   (i.e. it calls _run_query rather than self.db.get_session directly).
2. initialize_filter_stats passes a token_ref so stale results are dropped.
3. initialize_filter_stats passes on_error so failures are logged rather than
   swallowed silently.
4. _on_filter_stats_loaded sets _filter_unmapped_prefixes from the stats dict.
5. _on_filter_stats_loaded calls filter_panel.update_data with the full stats
   dict when filter_panel is present.

Note: The "filter_panel absent" branch (``hasattr(self, 'filter_panel')`` returning
False) cannot be tested via ``__new__`` on an uninit'd Qt object — PyQt6 raises
``RuntimeError`` on attribute lookup for missing attributes on uninitialized QWidget
subclasses. The production code guards with ``hasattr`` and always sets
``self.filter_panel`` in ``setup_ui`` before ``initialize_filter_stats`` is called,
so this gap is a testing artifact, not a production risk.
"""
from __future__ import annotations

import pytest

from metatv.gui.main_window import MainWindow


# ---------------------------------------------------------------------------
# Minimal collaborators (no Qt, no DB)
# ---------------------------------------------------------------------------

class _FakeFilterPanel:
    """Records update_data calls."""

    def __init__(self):
        self.update_data_calls: list[dict] = []

    def update_data(self, stats: dict) -> None:
        self.update_data_calls.append(stats)


def _make_host() -> MainWindow:
    """Real MainWindow instance via __new__ — no __init__, no Qt, no DB.

    Only the attributes touched by ``initialize_filter_stats`` and
    ``_on_filter_stats_loaded`` are populated. ``filter_panel`` is always set
    because PyQt6 raises RuntimeError on hasattr() for missing attrs on
    uninit'd QWidget subclasses (see module docstring for details).
    """
    host = MainWindow.__new__(MainWindow)

    # Minimal config with the four group dicts + excluded categories
    class _FakeConfig:
        filter_language_groups: dict = {"EN": ["EN"]}
        filter_quality_groups: dict = {"HD": ["HD"]}
        filter_platform_groups: dict = {}
        filter_regional_groups: dict = {}
        global_filter_excluded_user_categories: list = []

    host.config = _FakeConfig()

    # Token list (normally created in __init__ at line ~289)
    host._filter_stats_token = [0]

    # _filter_unmapped_prefixes is initialized in setup_ui (line ~776); seed it here
    host._filter_unmapped_prefixes = []

    # filter_panel must be set — see module docstring for why
    host.filter_panel = _FakeFilterPanel()

    # Record _run_query calls without executing them
    host._run_query_calls: list[dict] = []

    def _fake_run_query(query_fn, on_result, *, token_ref=None, on_error=None):
        host._run_query_calls.append(
            {"query_fn": query_fn, "on_result": on_result,
             "token_ref": token_ref, "on_error": on_error}
        )

    host._run_query = _fake_run_query

    # Ensure db is NOT set — any access to host.db.get_session() would AttributeError,
    # proving the synchronous session path is gone.
    # (We deliberately leave host.db unset rather than setting it to a mock,
    # so an accidental get_session() call is an AttributeError, not a silent pass.)

    return host


# ---------------------------------------------------------------------------
# initialize_filter_stats — dispatcher shape
# ---------------------------------------------------------------------------

def test_initialize_filter_stats_does_not_open_session():
    """initialize_filter_stats must not call db.get_session() on the calling thread.

    The method is async: it must only call _run_query and return.
    If the old synchronous path were restored, accessing host.db would raise
    AttributeError (db is intentionally absent), catching the regression.
    """
    host = _make_host()
    # Must not raise (db is absent; any get_session() call would AttributeError)
    host.initialize_filter_stats()


def test_initialize_filter_stats_calls_run_query_once():
    """initialize_filter_stats must delegate to _run_query exactly once."""
    host = _make_host()
    host.initialize_filter_stats()
    assert len(host._run_query_calls) == 1


def test_initialize_filter_stats_passes_token_ref():
    """The _run_query call must carry the _filter_stats_token so stale results drop."""
    host = _make_host()
    host.initialize_filter_stats()
    call = host._run_query_calls[0]
    assert call["token_ref"] is host._filter_stats_token, (
        "token_ref must be the _filter_stats_token list — stale-drop requires it"
    )


def test_initialize_filter_stats_passes_on_error():
    """Failures must be routed to on_error (not silently dropped)."""
    host = _make_host()
    host.initialize_filter_stats()
    call = host._run_query_calls[0]
    assert call["on_error"] is not None, (
        "on_error must be wired so failures are logged rather than silently swallowed"
    )


def test_initialize_filter_stats_on_result_is_handler():
    """The on_result callback must be _on_filter_stats_loaded."""
    host = _make_host()
    host.initialize_filter_stats()
    call = host._run_query_calls[0]
    assert call["on_result"] == host._on_filter_stats_loaded


def test_initialize_filter_stats_query_fn_captures_config_values():
    """query_fn must forward all five config-derived args to get_prefix_stats.

    We run the lambda against a fake repos to confirm the right keyword args are
    passed — this catches a regression where a config group is accidentally dropped.
    """
    host = _make_host()
    host.initialize_filter_stats()
    call = host._run_query_calls[0]
    query_fn = call["query_fn"]

    received_kwargs: list[dict] = []

    class _FakeChannelRepo:
        def get_prefix_stats(self, **kwargs) -> dict:
            received_kwargs.append(kwargs)
            return {"channels_with_prefix": 0, "unmapped_prefixes": [], "prefix_counts": {}}

    class _FakeRepos:
        channels = _FakeChannelRepo()

    query_fn(_FakeRepos())

    assert len(received_kwargs) == 1
    kw = received_kwargs[0]
    assert kw.get("provider_id") is None
    assert "language_groups" in kw
    assert "quality_groups" in kw
    assert "platform_groups" in kw
    assert "regional_groups" in kw
    assert "excluded_user_categories" in kw


# ---------------------------------------------------------------------------
# _on_filter_stats_loaded — main-thread handler (the half that regresses)
# ---------------------------------------------------------------------------

_SAMPLE_STATS = {
    "channels_with_prefix": 12345,
    "unmapped_prefixes": ["FOO", "BAR"],
    "prefix_counts": {"EN": 100, "DE": 50},
    "language_groups": {"English": 1000},
    "region_groups": {},
    "quality_groups": {},
}


def test_on_filter_stats_loaded_sets_unmapped_prefixes():
    """_on_filter_stats_loaded must set _filter_unmapped_prefixes from the stats dict."""
    host = _make_host()
    host._on_filter_stats_loaded(_SAMPLE_STATS)
    assert host._filter_unmapped_prefixes == ["FOO", "BAR"]


def test_on_filter_stats_loaded_unmapped_prefixes_default_empty():
    """When 'unmapped_prefixes' key is absent, _filter_unmapped_prefixes must be []."""
    host = _make_host()
    host._on_filter_stats_loaded({"channels_with_prefix": 0})
    assert host._filter_unmapped_prefixes == []


def test_on_filter_stats_loaded_calls_filter_panel_update_data():
    """_on_filter_stats_loaded must call filter_panel.update_data with the full dict."""
    host = _make_host()
    host._on_filter_stats_loaded(_SAMPLE_STATS)
    assert host.filter_panel.update_data_calls == [_SAMPLE_STATS]


def test_on_filter_stats_loaded_updates_unmapped_when_no_panel_key_in_stats():
    """_on_filter_stats_loaded must still set _filter_unmapped_prefixes from a
    stats dict that lacks 'unmapped_prefixes', defaulting to [].

    (The 'filter_panel absent' branch cannot be exercised via __new__ on a Qt
    object — see module docstring. This test covers a different edge: empty dict.)
    """
    host = _make_host()
    host._on_filter_stats_loaded({"channels_with_prefix": 0})
    assert host._filter_unmapped_prefixes == []
    # filter_panel.update_data must still be called with the dict
    assert host.filter_panel.update_data_calls == [{"channels_with_prefix": 0}]
