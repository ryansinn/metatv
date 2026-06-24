"""Behavioral tests for the dev-only QA Testing Checklist.

Coverage:
- ``dev_mode_enabled()`` honors METATV_DEV across truthy and falsy values.
- ``QAChecklistWindow`` renders exactly one checkbox per step for in-scope
  entries (excludes no-steps entries and entries with id <= qa_verified_id).
- Toggling a checkbox mutates ``config.qa_checked_steps`` correctly and
  calls ``config.save()``.
- All-complete detection and the Purge action advance ``qa_verified_id`` to
  the max entry id so the open-items set becomes empty.
- Regression guard: every real ``WHATS_NEW`` entry loads with
  ``test_steps`` defaulting to ``()``.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

# ── headless Qt setup ─────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


# ── fake entry factory ────────────────────────────────────────────────────────

def _entry(id: int, steps: tuple[str, ...] = ()) -> SimpleNamespace:
    """Return a lightweight WhatsNewEntry-shaped object for tests."""
    return SimpleNamespace(
        id=id,
        version="0.9.0",
        date="2026-06-23",
        title=f"Entry {id}",
        items=("bullet",),
        test_steps=steps,
    )


# ── fake config ───────────────────────────────────────────────────────────────

class _FakeConfig:
    """Minimal Config stand-in for QAChecklistWindow tests."""

    def __init__(self, qa_verified_id: int = 0, qa_checked_steps: dict | None = None) -> None:
        self.qa_verified_id = qa_verified_id
        self.qa_checked_steps: dict = qa_checked_steps or {}
        self.save_calls: int = 0

    def save(self) -> None:
        self.save_calls += 1


# ── helper: build window without auto-show ────────────────────────────────────

def _build_window(qapp, config: _FakeConfig, entries: list) -> object:
    """Construct a QAChecklistWindow; returns the window instance."""
    from metatv.gui.qa_checklist_window import QAChecklistWindow
    win = QAChecklistWindow(config, entries)  # type: ignore[arg-type]
    return win


# ═══════════════════════════════════════════════════════════════════════════════
# 1. dev_mode_enabled() gate
# ═══════════════════════════════════════════════════════════════════════════════

def test_dev_mode_enabled_when_set_to_1(monkeypatch):
    monkeypatch.setenv("METATV_DEV", "1")
    from metatv.core.config import dev_mode_enabled
    assert dev_mode_enabled() is True


def test_dev_mode_enabled_when_set_to_true(monkeypatch):
    monkeypatch.setenv("METATV_DEV", "true")
    from metatv.core.config import dev_mode_enabled
    assert dev_mode_enabled() is True


def test_dev_mode_enabled_when_set_to_yes(monkeypatch):
    monkeypatch.setenv("METATV_DEV", "yes")
    from metatv.core.config import dev_mode_enabled
    assert dev_mode_enabled() is True


def test_dev_mode_disabled_when_absent(monkeypatch):
    monkeypatch.delenv("METATV_DEV", raising=False)
    from metatv.core.config import dev_mode_enabled
    assert dev_mode_enabled() is False


def test_dev_mode_disabled_when_empty(monkeypatch):
    monkeypatch.setenv("METATV_DEV", "")
    from metatv.core.config import dev_mode_enabled
    assert dev_mode_enabled() is False


def test_dev_mode_disabled_when_zero(monkeypatch):
    monkeypatch.setenv("METATV_DEV", "0")
    from metatv.core.config import dev_mode_enabled
    assert dev_mode_enabled() is False


def test_dev_mode_disabled_when_false_string(monkeypatch):
    monkeypatch.setenv("METATV_DEV", "false")
    from metatv.core.config import dev_mode_enabled
    assert dev_mode_enabled() is False


def test_dev_mode_disabled_when_no(monkeypatch):
    monkeypatch.setenv("METATV_DEV", "no")
    from metatv.core.config import dev_mode_enabled
    assert dev_mode_enabled() is False


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Window renders only in-scope entries
# ═══════════════════════════════════════════════════════════════════════════════

def test_window_skips_no_steps_entry(qapp):
    """An entry with no test_steps must produce zero checkboxes."""
    entries = [
        _entry(10, steps=()),          # no steps — must be excluded
        _entry(11, steps=("step A",)), # has steps — must be included
    ]
    config = _FakeConfig(qa_verified_id=0)
    win = _build_window(qapp, config, entries)

    # Entry 10 has no steps → excluded; entry 11 has 1 step → 1 checkbox
    assert 11 in win._checkboxes
    assert len(win._checkboxes[11]) == 1
    assert 10 not in win._checkboxes


def test_window_skips_verified_entry(qapp):
    """Entries with id <= qa_verified_id must be excluded."""
    entries = [
        _entry(10, steps=("step A",)),  # id <= verified (10) → excluded
        _entry(11, steps=("step B",)),  # id > verified → included
    ]
    config = _FakeConfig(qa_verified_id=10)
    win = _build_window(qapp, config, entries)

    assert 10 not in win._checkboxes
    assert 11 in win._checkboxes
    assert len(win._checkboxes[11]) == 1


def test_window_renders_correct_checkbox_count_per_entry(qapp):
    """Each entry gets exactly one QCheckBox per test_step."""
    entries = [
        _entry(20, steps=("step 1", "step 2", "step 3")),
        _entry(21, steps=("only step",)),
    ]
    config = _FakeConfig(qa_verified_id=0)
    win = _build_window(qapp, config, entries)

    assert len(win._checkboxes[20]) == 3
    assert len(win._checkboxes[21]) == 1


def test_window_restores_checked_state_from_config(qapp):
    """Checkboxes for pre-checked steps must start checked."""
    entries = [_entry(30, steps=("A", "B", "C"))]
    config = _FakeConfig(qa_verified_id=0, qa_checked_steps={"30": [0, 2]})
    win = _build_window(qapp, config, entries)

    cbs = win._checkboxes[30]
    assert cbs[0].isChecked() is True   # index 0 checked
    assert cbs[1].isChecked() is False  # index 1 not checked
    assert cbs[2].isChecked() is True   # index 2 checked


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Checkbox toggle mutates config correctly and calls save()
# ═══════════════════════════════════════════════════════════════════════════════

def test_checking_step_adds_index_to_config(qapp):
    """Checking an unchecked step adds its index to qa_checked_steps and saves."""
    entries = [_entry(40, steps=("step 1", "step 2"))]
    config = _FakeConfig(qa_verified_id=0)
    win = _build_window(qapp, config, entries)

    win._checkboxes[40][1].setChecked(True)  # check step index 1

    assert 1 in config.qa_checked_steps.get("40", [])
    assert config.save_calls >= 1


def test_unchecking_step_removes_index_from_config(qapp):
    """Unchecking a checked step removes its index from qa_checked_steps and saves."""
    entries = [_entry(41, steps=("step A",))]
    config = _FakeConfig(qa_verified_id=0, qa_checked_steps={"41": [0]})
    win = _build_window(qapp, config, entries)

    win._checkboxes[41][0].setChecked(False)  # uncheck step index 0

    assert 0 not in config.qa_checked_steps.get("41", [])
    assert config.save_calls >= 1


def test_checking_does_not_add_duplicate_index(qapp):
    """Checking an already-checked step must not create duplicate indices."""
    entries = [_entry(42, steps=("step",))]
    config = _FakeConfig(qa_verified_id=0, qa_checked_steps={"42": [0]})
    win = _build_window(qapp, config, entries)

    # The checkbox is already checked; toggle programmatically to trigger signal
    win._on_step_toggled(42, 0, True)

    assert config.qa_checked_steps["42"].count(0) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 4. All-complete detection + Purge action
# ═══════════════════════════════════════════════════════════════════════════════

def test_purge_button_disabled_when_not_all_complete(qapp):
    """Purge button must be disabled until ALL steps are checked."""
    entries = [_entry(50, steps=("step 1", "step 2"))]
    config = _FakeConfig(qa_verified_id=0, qa_checked_steps={"50": [0]})
    win = _build_window(qapp, config, entries)

    # Only step 0 is checked; step 1 is not
    assert win._purge_btn.isEnabled() is False


def test_purge_button_enabled_when_all_complete(qapp):
    """Purge button must be enabled when every step of every open entry is checked."""
    entries = [_entry(51, steps=("step A", "step B"))]
    config = _FakeConfig(qa_verified_id=0, qa_checked_steps={"51": [0, 1]})
    win = _build_window(qapp, config, entries)

    assert win._purge_btn.isEnabled() is True


def test_purge_advances_qa_verified_id_to_max_entry(qapp):
    """Purge sets qa_verified_id to the max entry id in the open list."""
    entries = [
        _entry(60, steps=("s1",)),
        _entry(61, steps=("s2",)),
    ]
    config = _FakeConfig(
        qa_verified_id=0,
        qa_checked_steps={"60": [0], "61": [0]},
    )
    win = _build_window(qapp, config, entries)

    win._on_purge()

    assert config.qa_verified_id == 61


def test_purge_results_in_empty_open_items(qapp):
    """After purge, _open_entries() must return an empty list."""
    entries = [_entry(70, steps=("s1",))]
    config = _FakeConfig(qa_verified_id=0, qa_checked_steps={"70": [0]})
    win = _build_window(qapp, config, entries)

    win._on_purge()

    assert win._open_entries() == []


def test_purge_saves_config(qapp):
    """Purge must call config.save()."""
    entries = [_entry(80, steps=("s1",))]
    config = _FakeConfig(qa_verified_id=0, qa_checked_steps={"80": [0]})
    win = _build_window(qapp, config, entries)
    prior_saves = config.save_calls

    win._on_purge()

    assert config.save_calls > prior_saves


def test_all_complete_false_for_empty_open_entries(qapp):
    """_all_complete() must return False (not crash) when there are no open entries."""
    entries = []
    config = _FakeConfig()
    win = _build_window(qapp, config, entries)

    assert win._all_complete([]) is False


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Regression guard: real WHATS_NEW entries load with test_steps == ()
# ═══════════════════════════════════════════════════════════════════════════════

def test_all_existing_entries_have_test_steps_as_tuple():
    """Every real WhatsNewEntry must load without error and have test_steps as a tuple."""
    from metatv.whats_new import WHATS_NEW, WhatsNewEntry

    assert len(WHATS_NEW) > 0, "WHATS_NEW must not be empty"
    for entry in WHATS_NEW:
        assert isinstance(entry, WhatsNewEntry), f"entry {entry.id} is not a WhatsNewEntry"
        assert isinstance(entry.test_steps, tuple), (
            f"entry {entry.id} test_steps must be tuple, got {type(entry.test_steps)}"
        )


def test_entries_without_steps_default_to_empty_tuple():
    """Entries that don't declare test_steps must have an empty tuple (not None)."""
    from metatv.whats_new import WHATS_NEW

    for entry in WHATS_NEW:
        # All entries must have test_steps; those without explicit steps get ()
        assert entry.test_steps is not None, f"entry {entry.id} test_steps is None"
        assert isinstance(entry.test_steps, tuple)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Config fields persist via Config class
# ═══════════════════════════════════════════════════════════════════════════════

def test_config_qa_fields_round_trip(tmp_path):
    """qa_checked_steps and qa_verified_id round-trip through Config.save()/load()."""
    import yaml
    from metatv.core.config import Config

    config = Config(config_dir=tmp_path, data_dir=tmp_path, cache_dir=tmp_path)
    config.qa_checked_steps = {"10": [0, 2], "11": [1]}
    config.qa_verified_id = 10
    config.save()

    # Read back the YAML directly (config_dir/data_dir/cache_dir are already in the
    # saved data as Path strings — don't pass them again or Pydantic raises duplicate-key).
    with open(tmp_path / "config.yaml") as f:
        data = yaml.safe_load(f)
    loaded = Config(**data)

    assert loaded.qa_verified_id == 10
    assert loaded.qa_checked_steps == {"10": [0, 2], "11": [1]}
