"""Behavioral tests for the opt-out filter model (new/unseen facet values).

The "Includes" filter panel must be opt-OUT: a facet value that appears for the
first time is INCLUDED by default, never silently hidden because it was missing
from the user's saved selection (docs/FILTERING_DESIGN.md).  These tests drive the
real ``FilterPanel.update_data`` path and assert the outcome that would break if
the panel regressed to opt-IN.

The autouse ``_isolate_user_config`` fixture (tests/conftest.py) already patches
``Path.home`` to a tmp dir, so building a default ``Config()`` and calling
``save()`` here can never touch the developer's real config.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

from metatv.core.config import Config
from metatv.gui.filter_panel import FilterPanel
from metatv.gui.new_facet_values_dialog import NewFacetValuesDialog


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_new_value_defaults_included(qapp):
    """A value present in the data but absent from `known` is CHECKED (opt-out)."""
    cfg = Config()
    cfg.filter_known_languages = ["English", "French"]
    cfg.filter_included_languages = ["English"]        # French deliberately deselected

    panel = FilterPanel(cfg)
    # "German" is new (not in known); "French" is known-but-deselected.
    panel.update_data({"language": {"English": 5, "French": 3, "German": 2}})

    selected = set(panel._lang_sec.get_selected_keys())
    assert "German" in selected, "new value must default INCLUDED (opt-out)"
    assert "English" in selected, "saved selection must be preserved"
    assert "French" not in selected, "a deselected known value must stay excluded"


def test_deselected_value_stays_unchecked_across_refresh(qapp):
    """Known-but-unselected values remain excluded even when data is re-supplied."""
    cfg = Config()
    cfg.filter_known_regions = None  # force the first-run baseline

    panel = FilterPanel(cfg)
    # Region section renders ISO codes grouped by continent; use real codes so the
    # rows actually render (US/CA/MX all belong to a North America group).
    counts = {"region": {"US": 10, "CA": 4, "MX": 6}}
    panel.update_data(counts)  # baseline → all present included, known recorded

    # User deselects MX and saves.
    keep = set(panel._region_sec.get_selected_keys()) - {"MX"}
    panel._region_sec.restore_selection(keep)
    panel.save_state()
    assert "MX" not in set(panel._region_sec.get_selected_keys())

    # A second panel (fresh instance, e.g. next launch) restoring from the same
    # config must keep MX excluded — it is known + deselected, not new.
    panel2 = FilterPanel(cfg)
    panel2.update_data(counts)
    sel2 = set(panel2._region_sec.get_selected_keys())
    assert "MX" not in sel2, "deselection must survive a refresh, not be re-added"
    assert "US" in sel2 and "CA" in sel2


def test_first_run_baseline_unhides_everything(qapp):
    """known is None → INCLUDE every present value, overriding a stale saved subset."""
    cfg = Config()
    cfg.filter_known_languages = None
    cfg.filter_included_languages = ["English"]  # stale subset hiding French/German

    panel = FilterPanel(cfg)
    panel.update_data({"language": {"English": 5, "French": 3, "German": 2}})

    selected = set(panel._lang_sec.get_selected_keys())
    assert selected == {"English", "French", "German"}, (
        "first-run baseline must un-hide all present values"
    )
    # Baseline recorded so subsequent runs distinguish new from deselected.
    assert set(cfg.filter_known_languages) == {"English", "French", "German"}


def test_baseline_run_shows_no_popup(qapp, monkeypatch):
    """The first-run baseline un-hides silently — it must NOT show the popup."""
    cfg = Config()
    cfg.filter_known_languages = None

    panel = FilterPanel(cfg)
    calls: list = []
    monkeypatch.setattr(panel, "_show_new_values_popup", lambda nbf: calls.append(nbf))
    panel.update_data({"language": {"English": 5, "French": 3}})
    assert calls == [], "baseline/first-run must not trigger the new-values popup"


def test_refresh_new_value_triggers_popup_computation(qapp, monkeypatch):
    """A NEW value on a non-first call is offered via the popup and included."""
    cfg = Config()
    cfg.filter_known_languages = None

    panel = FilterPanel(cfg)
    captured: list = []
    monkeypatch.setattr(panel, "_show_new_values_popup", lambda nbf: captured.append(nbf))

    # Call 1: establishes the baseline (was_first=True) → no popup.
    panel.update_data({"language": {"English": 5}})
    assert captured == []

    # Call 2 (source refresh): "Spanish" is brand new → popup computation fires.
    panel.update_data({"language": {"English": 5, "Spanish": 4}})
    assert len(captured) == 1
    assert captured[0] == {"language": {"Spanish"}}
    # And the new value is CHECKED by default (opt-out), pending the user's choice.
    assert "Spanish" in set(panel._lang_sec.get_selected_keys())


def test_apply_new_value_exclusions_unchecks(qapp):
    """Excluding a new value via the popup result unchecks it, keeps the rest."""
    cfg = Config()
    cfg.filter_known_platforms = ["Netflix"]
    cfg.filter_included_platforms = ["Netflix"]

    panel = FilterPanel(cfg)
    panel.update_data({"platform": {"Netflix": 9, "Disney+": 3, "Prime": 2}})
    # Disney+ and Prime are new → included by default.
    sel = set(panel._platform_sec.get_selected_keys())
    assert {"Disney+", "Prime"} <= sel

    # User opts Disney+ out via the popup result.
    panel._apply_new_value_exclusions({"platform": {"Disney+"}})
    sel2 = set(panel._platform_sec.get_selected_keys())
    assert "Disney+" not in sel2
    assert "Prime" in sel2 and "Netflix" in sel2


def test_dialog_excluded_returns_unchecked(qapp):
    """NewFacetValuesDialog.excluded() reports only the unchecked (opted-out) values."""
    dlg = NewFacetValuesDialog(
        {"region": {"US", "GB"}, "language": {"Dutch"}},
        {"region": "Region", "language": "Language"},
        {"region": {"US": "United States", "GB": "United Kingdom"}},
    )
    # All start checked → nothing excluded.
    assert dlg.excluded() == {}
    # Uncheck one → it becomes an exclusion; still-checked values are not reported.
    dlg._checks["region"]["US"].setChecked(False)
    assert dlg.excluded() == {"region": {"US"}}


def test_known_set_persists_round_trip(qapp):
    """filter_known_* survives a real YAML save/reload (persistence round-trip)."""
    cfg = Config()
    cfg.filter_known_genres = None

    panel = FilterPanel(cfg)
    panel.update_data({"genre": {"Drama": 40, "Comedy": 30}})  # baseline records known
    panel.save_state()  # writes config (to the tmp home, per the autouse fixture)

    reloaded, _ = Config.load()
    assert reloaded.filter_known_genres is not None
    assert set(reloaded.filter_known_genres) == {"Drama", "Comedy"}
