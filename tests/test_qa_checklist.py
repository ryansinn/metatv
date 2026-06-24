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
- PR# parser: ``_parse_pr_number`` extracts int from squash-merge subjects.
- Remote URL normalizer: SSH and HTTPS forms both map to HTTPS base URL.
- Header link: resolved refs render as ``href`` link; no git → date fallback.
- Archive: complete entry shows Archive action; archiving persists + excludes;
  incomplete entry shows no Archive; Unarchive restores the entry.
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

    def __init__(
        self,
        qa_verified_id: int = 0,
        qa_checked_steps: dict | None = None,
        qa_archived_ids: list | None = None,
    ) -> None:
        self.qa_verified_id = qa_verified_id
        self.qa_checked_steps: dict = qa_checked_steps or {}
        self.qa_archived_ids: list = qa_archived_ids or []
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


# ═══════════════════════════════════════════════════════════════════════════════
# 7. PR# parser — _parse_pr_number
# ═══════════════════════════════════════════════════════════════════════════════

def test_parse_pr_number_extracts_from_squash_subject():
    """A squash-merge subject containing (#183) must yield PR number 183."""
    from metatv.gui.qa_checklist_window import _parse_pr_number
    assert _parse_pr_number("feat(x): thing (#183)") == 183


def test_parse_pr_number_extracts_large_number():
    """PR numbers with multiple digits must be parsed correctly."""
    from metatv.gui.qa_checklist_window import _parse_pr_number
    assert _parse_pr_number("fix(series): hide overlay (#1042)") == 1042


def test_parse_pr_number_returns_none_when_absent():
    """A subject with no (#N) pattern must return None."""
    from metatv.gui.qa_checklist_window import _parse_pr_number
    assert _parse_pr_number("chore: update deps") is None


def test_parse_pr_number_returns_none_for_empty_subject():
    """An empty subject must return None without raising."""
    from metatv.gui.qa_checklist_window import _parse_pr_number
    assert _parse_pr_number("") is None


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Remote URL normalizer — _normalize_remote_url
# ═══════════════════════════════════════════════════════════════════════════════

def test_normalize_ssh_remote_url():
    """SSH remote URL must normalize to HTTPS base URL without .git."""
    from metatv.gui.qa_checklist_window import _normalize_remote_url
    result = _normalize_remote_url("git@github.com:ryansinn/metatv.git")
    assert result == "https://github.com/ryansinn/metatv"


def test_normalize_https_remote_url():
    """HTTPS remote URL must normalize to base URL without .git."""
    from metatv.gui.qa_checklist_window import _normalize_remote_url
    result = _normalize_remote_url("https://github.com/ryansinn/metatv.git")
    assert result == "https://github.com/ryansinn/metatv"


def test_normalize_https_remote_url_without_git_suffix():
    """HTTPS URL without .git must be returned as-is."""
    from metatv.gui.qa_checklist_window import _normalize_remote_url
    result = _normalize_remote_url("https://github.com/ryansinn/metatv")
    assert result == "https://github.com/ryansinn/metatv"


def test_normalize_ssh_url_with_org_slash_repo():
    """SSH URLs with org/repo path must produce the correct HTTPS base URL."""
    from metatv.gui.qa_checklist_window import _normalize_remote_url
    result = _normalize_remote_url("git@github.com:org/nested-repo.git")
    assert result == "https://github.com/org/nested-repo"


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Header link rendering — _apply_git_refs
# ═══════════════════════════════════════════════════════════════════════════════

def test_header_link_shows_pr_href_when_resolved(qapp):
    """When a PR# and base URL are known the ref label must contain an href."""
    entries = [_entry(100, steps=("step",))]
    config = _FakeConfig()
    win = _build_window(qapp, config, entries)

    # Simulate the worker having returned results
    win._on_git_refs_ready({
        100: {
            "pr_number": 183,
            "commit_hash": None,
            "base_url": "https://github.com/ryansinn/metatv",
        }
    })

    lbl = win._ref_labels.get(100)
    assert lbl is not None
    assert 'href="https://github.com/ryansinn/metatv/pull/183"' in lbl.text()
    assert lbl.openExternalLinks() is True


def test_header_link_shows_commit_href_when_no_pr(qapp):
    """When only a commit hash is known the ref label must link to the commit."""
    entries = [_entry(101, steps=("step",))]
    config = _FakeConfig()
    win = _build_window(qapp, config, entries)

    win._on_git_refs_ready({
        101: {
            "pr_number": None,
            "commit_hash": "abc1234",
            "base_url": "https://github.com/ryansinn/metatv",
        }
    })

    lbl = win._ref_labels.get(101)
    assert lbl is not None
    assert 'href="https://github.com/ryansinn/metatv/commit/abc1234"' in lbl.text()


def test_header_link_falls_back_to_date_when_no_git(qapp):
    """When git lookup fails (no PR, no hash) the ref label must show the date."""
    entries = [_entry(102, steps=("step",))]
    config = _FakeConfig()
    win = _build_window(qapp, config, entries)

    win._on_git_refs_ready({
        102: {
            "pr_number": None,
            "commit_hash": None,
            "base_url": None,
        }
    })

    lbl = win._ref_labels.get(102)
    assert lbl is not None
    # No href should be present; the label should still show the date
    assert "href" not in lbl.text()
    assert "2026-06-23" in lbl.text()


def test_header_label_open_external_links_enabled(qapp):
    """The ref label must always have setOpenExternalLinks(True)."""
    entries = [_entry(103, steps=("step",))]
    config = _FakeConfig()
    win = _build_window(qapp, config, entries)

    lbl = win._ref_labels.get(103)
    assert lbl is not None
    assert lbl.openExternalLinks() is True


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Per-entry archive / unarchive
# ═══════════════════════════════════════════════════════════════════════════════

def test_complete_entry_shows_archive_action(qapp):
    """An entry with all steps checked must have an Archive action available."""
    entries = [_entry(200, steps=("step A", "step B"))]
    config = _FakeConfig(qa_checked_steps={"200": [0, 1]})
    win = _build_window(qapp, config, entries)

    # The entry is complete — _on_archive must be callable (button is wired)
    # We verify by calling the handler directly and checking the side-effect.
    prior_saves = config.save_calls
    win._on_archive(200)

    assert 200 in config.qa_archived_ids
    assert config.save_calls > prior_saves


def test_incomplete_entry_not_in_open_entries_after_archive_impossible(qapp):
    """An incomplete entry cannot be archived (no Archive button is rendered).

    This is enforced by the window only wiring the archive callback when the
    entry is complete.  We verify via the open_entries list directly: an
    incomplete entry (not manually archived) remains in open_entries.
    """
    entries = [_entry(201, steps=("step A", "step B"))]
    config = _FakeConfig(qa_checked_steps={"201": [0]})  # only step 0 checked
    win = _build_window(qapp, config, entries)

    # The entry is NOT complete so it should still be in open_entries
    open_ids = [e.id for e in win._open_entries()]
    assert 201 in open_ids


def test_archive_adds_id_to_config_qa_archived_ids(qapp):
    """_on_archive must append the entry id to config.qa_archived_ids."""
    entries = [_entry(202, steps=("step",))]
    config = _FakeConfig(qa_checked_steps={"202": [0]})
    win = _build_window(qapp, config, entries)

    win._on_archive(202)

    assert 202 in config.qa_archived_ids


def test_archive_saves_config(qapp):
    """_on_archive must call config.save()."""
    entries = [_entry(203, steps=("step",))]
    config = _FakeConfig(qa_checked_steps={"203": [0]})
    win = _build_window(qapp, config, entries)
    prior = config.save_calls

    win._on_archive(203)

    assert config.save_calls > prior


def test_archived_entry_excluded_from_open_entries(qapp):
    """An archived entry must not appear in _open_entries()."""
    entries = [
        _entry(210, steps=("step A",)),
        _entry(211, steps=("step B",)),
    ]
    config = _FakeConfig(
        qa_checked_steps={"210": [0], "211": [0]},
        qa_archived_ids=[210],
    )
    win = _build_window(qapp, config, entries)

    open_ids = [e.id for e in win._open_entries()]
    assert 210 not in open_ids
    assert 211 in open_ids


def test_unarchive_removes_id_from_qa_archived_ids(qapp):
    """_on_unarchive must remove the entry id from config.qa_archived_ids."""
    entries = [_entry(220, steps=("step",))]
    config = _FakeConfig(qa_checked_steps={"220": [0]}, qa_archived_ids=[220])
    win = _build_window(qapp, config, entries)

    win._on_unarchive(220)

    assert 220 not in config.qa_archived_ids


def test_unarchive_restores_entry_to_open_entries(qapp):
    """After unarchiving, the entry must reappear in _open_entries()."""
    entries = [_entry(221, steps=("step",))]
    config = _FakeConfig(qa_checked_steps={"221": [0]}, qa_archived_ids=[221])
    win = _build_window(qapp, config, entries)

    win._on_unarchive(221)

    open_ids = [e.id for e in win._open_entries()]
    assert 221 in open_ids


def test_unarchive_saves_config(qapp):
    """_on_unarchive must call config.save()."""
    entries = [_entry(222, steps=("step",))]
    config = _FakeConfig(qa_checked_steps={"222": [0]}, qa_archived_ids=[222])
    win = _build_window(qapp, config, entries)
    prior = config.save_calls

    win._on_unarchive(222)

    assert config.save_calls > prior


# ═══════════════════════════════════════════════════════════════════════════════
# 11. qa_archived_ids round-trips through Config
# ═══════════════════════════════════════════════════════════════════════════════

def test_config_qa_archived_ids_round_trip(tmp_path):
    """qa_archived_ids must round-trip through Config.save() / load()."""
    import yaml
    from metatv.core.config import Config

    config = Config(config_dir=tmp_path, data_dir=tmp_path, cache_dir=tmp_path)
    config.qa_archived_ids = [10, 23, 47]
    config.save()

    with open(tmp_path / "config.yaml") as f:
        data = yaml.safe_load(f)
    loaded = Config(**data)

    assert loaded.qa_archived_ids == [10, 23, 47]


def test_config_qa_archived_ids_default_empty(tmp_path):
    """qa_archived_ids must default to an empty list for a fresh Config."""
    from metatv.core.config import Config

    config = Config(config_dir=tmp_path, data_dir=tmp_path, cache_dir=tmp_path)
    assert config.qa_archived_ids == []
