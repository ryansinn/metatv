"""Behavioral tests for "Remember last search" feature.

What regresses without these tests
-----------------------------------
- Config fields missing → AttributeError on first save/load
- _save_search_state writes wrong keys → restore picks up garbage
- remember_search=False → state still gets saved or restored
- restore_search_state with empty/trivial state → spurious load_channels call
- restore_search_state returns True/False correctly (startup fallback depends on this)
- Query text is set without triggering the debounce signal
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch


# ---------------------------------------------------------------------------
# Config field defaults
# ---------------------------------------------------------------------------

def test_config_remember_search_defaults_true():
    """Config.remember_search must default to True (feature is on by default)."""
    from metatv.core.config import Config
    cfg = Config()
    assert cfg.remember_search is True


def test_config_last_search_state_defaults_empty():
    """Config.last_search_state must default to an empty dict."""
    from metatv.core.config import Config
    cfg = Config()
    assert cfg.last_search_state == {}


def test_config_search_state_round_trip():
    """Saving and reloading config preserves last_search_state.

    Path.home() is redirected to a tmp dir by the autouse _isolate_user_config fixture,
    so Config() / Config.load() stay isolated from the real user config.
    """
    from metatv.core.config import Config

    cfg = Config()
    cfg.remember_search = True
    cfg.last_search_state = {
        "query": "action",
        "provider_id": "prov-1",
        "hidden_mode": False,
        "genre_filter": None,
        "person_filter": None,
    }
    cfg.save()

    cfg2, _ = Config.load()
    assert cfg2.remember_search is True
    assert cfg2.last_search_state["query"] == "action"
    assert cfg2.last_search_state["provider_id"] == "prov-1"


def test_config_remember_off_round_trip():
    """remember_search=False is persisted and loaded correctly."""
    from metatv.core.config import Config

    cfg = Config()
    cfg.remember_search = False
    cfg.save()

    cfg2, _ = Config.load()
    assert cfg2.remember_search is False


# ---------------------------------------------------------------------------
# _save_search_state
# ---------------------------------------------------------------------------

def _make_window_for_save(
    remember_search: bool = True,
    query: str = "",
    provider_id=None,
    hidden_mode: bool = False,
    genre_filter=None,
    person_filter=None,
):
    """Return a SimpleNamespace quacking like the relevant slice of MainWindow."""
    config = MagicMock()
    config.remember_search = remember_search

    search_input = MagicMock()
    search_input.text.return_value = query

    me = SimpleNamespace(
        config=config,
        search_input=search_input,
        selected_provider_id=provider_id,
        _hidden_mode=hidden_mode,
        _details_genre_filter=genre_filter,
        _details_person_filter=person_filter,
    )
    return me


def test_save_search_state_writes_all_keys():
    """_save_search_state writes query, provider_id, hidden_mode, genre, person to config."""
    from metatv.gui.main_window_channels import _ChannelListMixin

    me = _make_window_for_save(
        query="sci-fi",
        provider_id="prov-xyz",
        hidden_mode=True,
        genre_filter="Action",
    )
    _ChannelListMixin._save_search_state(me)

    saved = me.config.last_search_state
    assert saved["query"] == "sci-fi"
    assert saved["provider_id"] == "prov-xyz"
    assert saved["hidden_mode"] is True
    assert saved["genre_filter"] == "Action"
    assert saved["person_filter"] is None
    me.config.save.assert_called_once()


def test_save_search_state_noop_when_feature_off():
    """_save_search_state must not write anything if remember_search is False."""
    from metatv.gui.main_window_channels import _ChannelListMixin

    me = _make_window_for_save(remember_search=False, query="thriller")
    _ChannelListMixin._save_search_state(me)

    # Neither save() nor last_search_state assignment should happen
    me.config.save.assert_not_called()


# ---------------------------------------------------------------------------
# restore_search_state
# ---------------------------------------------------------------------------

def _make_window_for_restore(state: dict, remember_search: bool = True):
    """Return a minimal SimpleNamespace for restore_search_state tests."""
    config = MagicMock()
    config.remember_search = remember_search
    config.last_search_state = state

    search_input = MagicMock()
    load_channels = MagicMock()

    me = SimpleNamespace(
        config=config,
        search_input=search_input,
        selected_provider_id=None,
        _hidden_mode=False,
        _details_genre_filter=None,
        _details_person_filter=None,
        # No _tab_*_btn / _context_filter_* — hasattr guards handle absence
        sidebar_sections={},
        load_channels=load_channels,
    )
    return me, load_channels


def test_restore_returns_false_when_feature_off():
    """restore_search_state returns False when remember_search is off."""
    from metatv.gui.main_window_channels import _ChannelListMixin

    me, load_channels = _make_window_for_restore(
        state={"query": "drama", "provider_id": None, "hidden_mode": False,
               "genre_filter": None, "person_filter": None},
        remember_search=False,
    )
    result = _ChannelListMixin.restore_search_state(me)

    assert result is False
    load_channels.assert_not_called()


def test_restore_returns_false_when_state_empty():
    """restore_search_state returns False when last_search_state is {}."""
    from metatv.gui.main_window_channels import _ChannelListMixin

    me, load_channels = _make_window_for_restore(state={})
    result = _ChannelListMixin.restore_search_state(me)

    assert result is False
    load_channels.assert_not_called()


def test_restore_returns_false_when_state_trivial():
    """restore_search_state returns False when state has only default/empty values."""
    from metatv.gui.main_window_channels import _ChannelListMixin

    trivial = {"query": "", "provider_id": None, "hidden_mode": False,
               "genre_filter": None, "person_filter": None}
    me, load_channels = _make_window_for_restore(state=trivial)
    result = _ChannelListMixin.restore_search_state(me)

    assert result is False
    load_channels.assert_not_called()


def test_restore_applies_query_and_calls_load():
    """restore_search_state sets the search box text and calls load_channels."""
    from metatv.gui.main_window_channels import _ChannelListMixin

    state = {"query": "adventure", "provider_id": None, "hidden_mode": False,
             "genre_filter": None, "person_filter": None}
    me, load_channels = _make_window_for_restore(state=state)

    result = _ChannelListMixin.restore_search_state(me)

    assert result is True
    me.search_input.setText.assert_called_once_with("adventure")
    # Signals were blocked during setText
    me.search_input.blockSignals.assert_any_call(True)
    me.search_input.blockSignals.assert_any_call(False)
    load_channels.assert_called_once_with(None)


def test_restore_applies_provider_filter():
    """restore_search_state restores selected_provider_id and calls load_channels(provider_id)."""
    from metatv.gui.main_window_channels import _ChannelListMixin

    state = {"query": "", "provider_id": "prov-abc", "hidden_mode": False,
             "genre_filter": None, "person_filter": None}
    me, load_channels = _make_window_for_restore(state=state)

    result = _ChannelListMixin.restore_search_state(me)

    assert result is True
    assert me.selected_provider_id == "prov-abc"
    load_channels.assert_called_once_with("prov-abc")


def test_restore_applies_genre_chip():
    """restore_search_state restores the genre context chip state."""
    from metatv.gui.main_window_channels import _ChannelListMixin

    state = {"query": "", "provider_id": None, "hidden_mode": False,
             "genre_filter": "Comedy", "person_filter": None}
    me, load_channels = _make_window_for_restore(state=state)

    result = _ChannelListMixin.restore_search_state(me)

    assert result is True
    assert me._details_genre_filter == "Comedy"
    assert me._details_person_filter is None
    load_channels.assert_called_once()


def test_restore_applies_person_chip():
    """restore_search_state restores the person context chip state."""
    from metatv.gui.main_window_channels import _ChannelListMixin

    state = {"query": "", "provider_id": None, "hidden_mode": False,
             "genre_filter": None, "person_filter": "Tom Hanks"}
    me, load_channels = _make_window_for_restore(state=state)

    result = _ChannelListMixin.restore_search_state(me)

    assert result is True
    assert me._details_person_filter == "Tom Hanks"
    assert me._details_genre_filter is None
    load_channels.assert_called_once()


def test_restore_hidden_mode_sets_flag():
    """restore_search_state sets _hidden_mode=True when hidden_mode was saved."""
    from metatv.gui.main_window_channels import _ChannelListMixin

    state = {"query": "", "provider_id": None, "hidden_mode": True,
             "genre_filter": None, "person_filter": None}
    me, load_channels = _make_window_for_restore(state=state)

    result = _ChannelListMixin.restore_search_state(me)

    assert result is True
    assert me._hidden_mode is True
    load_channels.assert_called_once()


# ---------------------------------------------------------------------------
# What's New entry sanity
# ---------------------------------------------------------------------------

def test_whats_new_entry_id_is_30():
    """The remember-search What's New entry must use id=30 exactly."""
    import importlib
    # Filename starts with a digit so dotted import doesn't work;
    # use importlib with the full dotted name that pkgutil resolves.
    mod = importlib.import_module("metatv.whats_new.entries.0030_remember_search")
    assert mod.ENTRY.id == 30


def test_whats_new_entry_appears_in_catalogue():
    """Entry 30 must appear in the global WHATS_NEW catalogue."""
    from metatv.whats_new import WHATS_NEW
    ids = [e.id for e in WHATS_NEW]
    assert 30 in ids, f"Entry 30 not found in WHATS_NEW; found: {ids}"
