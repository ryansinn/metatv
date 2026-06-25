"""Behavioral tests for the dev-only QA Testing Checklist.

Coverage:
- ``dev_mode_enabled()`` honors METATV_DEV across truthy and falsy values.
- ``QAChecklistWindow`` renders a tri-state pass/fail pair per step for in-scope
  entries (excludes no-steps entries and entries with id <= qa_verified_id).
- Marking a step pass/fail mutates ``config.qa_step_results`` correctly and calls
  ``config.save()``; re-clicking the active state clears it back to untested.
- Migration: a legacy ``qa_checked_steps`` list shape becomes ``qa_step_results``
  pass records on Config load.
- Completion: an entry with a failed step is NOT complete/archivable and is
  flagged; all-pass IS complete; Purge advances ``qa_verified_id`` but keeps
  failed entries.
- Fail note + attachment persistence; build-sha stamp + re-test hint.
- AI failures digest: ``qa_failures.md`` is written with title/step/note; zero
  failures yields "No failures recorded."
- PR# parser / remote URL normalizer / header link rendering (unchanged infra).
- Archive / unarchive.
"""

from __future__ import annotations

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
    """Minimal Config stand-in for QAChecklistWindow tests.

    ``config_dir`` defaults to a tmp dir so digest / attachment writes land in
    isolation, never the real user config.
    """

    def __init__(
        self,
        qa_verified_id: int = 0,
        qa_step_results: dict | None = None,
        qa_archived_ids: list | None = None,
        qa_archived_collapsed: bool = True,
        config_dir: Path | None = None,
    ) -> None:
        self.qa_verified_id = qa_verified_id
        self.qa_step_results: dict = qa_step_results or {}
        self.qa_archived_ids: list = qa_archived_ids or []
        self.qa_archived_collapsed: bool = qa_archived_collapsed
        self.config_dir = config_dir or Path("/tmp")
        self.save_calls: int = 0

    def save(self) -> None:
        self.save_calls += 1


# ── helper: build window without auto-show ────────────────────────────────────

def _build_window(qapp, config: _FakeConfig, entries: list) -> object:
    """Construct a QAChecklistWindow; returns the window instance."""
    from metatv.gui.qa_checklist_window import QAChecklistWindow
    win = QAChecklistWindow(config, entries)  # type: ignore[arg-type]
    return win


def _pass_rec() -> dict:
    return {"state": "pass", "sha": "", "ts": ""}


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
# 2. Window renders only in-scope entries (tri-state pass/fail pair per step)
# ═══════════════════════════════════════════════════════════════════════════════

def test_window_skips_no_steps_entry(qapp, tmp_path):
    """An entry with no test_steps must produce zero step rows."""
    entries = [
        _entry(10, steps=()),          # no steps — must be excluded
        _entry(11, steps=("step A",)),  # has steps — must be included
    ]
    config = _FakeConfig(qa_verified_id=0, config_dir=tmp_path)
    win = _build_window(qapp, config, entries)

    assert 11 in win._step_buttons
    assert len(win._step_buttons[11]) == 1
    assert 10 not in win._step_buttons


def test_window_skips_verified_entry(qapp, tmp_path):
    """Entries with id <= qa_verified_id must be excluded."""
    entries = [
        _entry(10, steps=("step A",)),
        _entry(11, steps=("step B",)),
    ]
    config = _FakeConfig(qa_verified_id=10, config_dir=tmp_path)
    win = _build_window(qapp, config, entries)

    assert 10 not in win._step_buttons
    assert 11 in win._step_buttons


def test_window_renders_one_pass_fail_pair_per_step(qapp, tmp_path):
    """Each step gets exactly one (pass, fail) button pair."""
    entries = [
        _entry(20, steps=("step 1", "step 2", "step 3")),
        _entry(21, steps=("only step",)),
    ]
    config = _FakeConfig(qa_verified_id=0, config_dir=tmp_path)
    win = _build_window(qapp, config, entries)

    assert len(win._step_buttons[20]) == 3
    assert len(win._step_buttons[21]) == 1
    pass_btn, fail_btn = win._step_buttons[21][0]
    assert pass_btn.toolTip() == "Mark passed"
    assert fail_btn.toolTip() == "Mark failed"


def test_window_reflects_stored_state(qapp, tmp_path):
    """Stored pass/fail records are reflected by _step_state."""
    entries = [_entry(30, steps=("A", "B", "C"))]
    config = _FakeConfig(
        qa_verified_id=0,
        qa_step_results={"30": {"0": _pass_rec(), "2": {"state": "fail"}}},
        config_dir=tmp_path,
    )
    win = _build_window(qapp, config, entries)

    assert win._step_state(30, 0) == "pass"
    assert win._step_state(30, 1) is None
    assert win._step_state(30, 2) == "fail"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Mark pass/fail mutates config + saves; re-click clears
# ═══════════════════════════════════════════════════════════════════════════════

def test_marking_pass_sets_state_and_saves(qapp, tmp_path):
    """Clicking pass records state=pass and calls save()."""
    entries = [_entry(40, steps=("step 1", "step 2"))]
    config = _FakeConfig(qa_verified_id=0, config_dir=tmp_path)
    win = _build_window(qapp, config, entries)
    prior = config.save_calls

    win._step_buttons[40][1][0].click()  # pass button on step index 1

    assert config.qa_step_results["40"]["1"]["state"] == "pass"
    assert config.save_calls > prior


def test_marking_fail_sets_state_and_saves(qapp, tmp_path):
    """Clicking fail records state=fail and calls save()."""
    entries = [_entry(41, steps=("step A",))]
    config = _FakeConfig(qa_verified_id=0, config_dir=tmp_path)
    win = _build_window(qapp, config, entries)

    win._step_buttons[41][0][1].click()  # fail button on step 0

    assert config.qa_step_results["41"]["0"]["state"] == "fail"
    assert config.save_calls >= 1


def test_reclicking_active_state_clears_step(qapp, tmp_path):
    """Re-clicking the active pass state clears the step back to untested."""
    entries = [_entry(42, steps=("step",))]
    config = _FakeConfig(
        qa_verified_id=0,
        qa_step_results={"42": {"0": _pass_rec()}},
        config_dir=tmp_path,
    )
    win = _build_window(qapp, config, entries)

    win._on_mark(42, 0, "pass")  # active pass clicked again → clear

    assert win._step_state(42, 0) is None


def test_mark_records_timestamp(qapp, tmp_path):
    """Marking a step records an ISO timestamp on the record."""
    entries = [_entry(43, steps=("step",))]
    config = _FakeConfig(qa_verified_id=0, config_dir=tmp_path)
    win = _build_window(qapp, config, entries)

    win._on_mark(43, 0, "pass")

    rec = config.qa_step_results["43"]["0"]
    assert rec["ts"]  # non-empty ISO timestamp
    assert "T" in rec["ts"]


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Migration — legacy qa_checked_steps → qa_step_results pass records
# ═══════════════════════════════════════════════════════════════════════════════

def test_migration_list_shape_becomes_pass_records(tmp_path):
    """A legacy {eid:[idx,...]} qa_checked_steps migrates to pass records."""
    from metatv.core.config import Config

    config = Config(
        config_dir=tmp_path, data_dir=tmp_path, cache_dir=tmp_path,
        qa_checked_steps={"10": [0, 2], "11": [1]},
    )

    assert config.qa_step_results["10"]["0"]["state"] == "pass"
    assert config.qa_step_results["10"]["2"]["state"] == "pass"
    assert config.qa_step_results["11"]["1"]["state"] == "pass"
    # The new field round-trips through save()/load().
    config.save()
    import yaml
    with open(tmp_path / "config.yaml") as f:
        data = yaml.safe_load(f)
    loaded = Config(**data)
    assert loaded.qa_step_results["10"]["0"]["state"] == "pass"


def test_migration_no_op_when_new_field_present(tmp_path):
    """Migration must not clobber an existing qa_step_results."""
    from metatv.core.config import Config

    config = Config(
        config_dir=tmp_path, data_dir=tmp_path, cache_dir=tmp_path,
        qa_checked_steps={"10": [0]},
        qa_step_results={"99": {"0": {"state": "fail"}}},
    )

    assert config.qa_step_results == {"99": {"0": {"state": "fail"}}}


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Completion logic — all-pass complete; any-fail incomplete + flagged
# ═══════════════════════════════════════════════════════════════════════════════

def test_all_pass_entry_is_complete(qapp, tmp_path):
    """An entry whose every step passes is complete + Purge-enabled."""
    entries = [_entry(50, steps=("a", "b"))]
    config = _FakeConfig(
        qa_step_results={"50": {"0": _pass_rec(), "1": _pass_rec()}},
        config_dir=tmp_path,
    )
    win = _build_window(qapp, config, entries)

    assert win._is_entry_complete(entries[0]) is True
    assert win._purge_btn.isEnabled() is True


def test_failed_step_keeps_entry_incomplete_and_flags_it(qapp, tmp_path):
    """An entry with a failed step is not complete; entry flagged as failure."""
    entries = [_entry(51, steps=("a", "b"))]
    config = _FakeConfig(
        qa_step_results={"51": {"0": _pass_rec(), "1": {"state": "fail"}}},
        config_dir=tmp_path,
    )
    win = _build_window(qapp, config, entries)

    assert win._is_entry_complete(entries[0]) is False
    assert win._entry_has_failure(entries[0]) is True
    assert win._purge_btn.isEnabled() is False


def test_purge_keeps_failed_entries_visible(qapp, tmp_path):
    """Purge clears passing entries but never purges a failed one away."""
    entries = [
        _entry(60, steps=("s1",)),  # passes
        _entry(61, steps=("s2",)),  # fails
        _entry(62, steps=("s3",)),  # passes
    ]
    config = _FakeConfig(
        qa_step_results={
            "60": {"0": _pass_rec()},
            "61": {"0": {"state": "fail"}},
            "62": {"0": _pass_rec()},
        },
        config_dir=tmp_path,
    )
    win = _build_window(qapp, config, entries)

    win._on_purge()

    open_ids = [e.id for e in win._open_entries()]
    assert 61 in open_ids          # failed entry kept
    assert 60 not in open_ids      # passing entry below the fail cleared
    # cursor stops just below the lowest failing id (61) → 60
    assert config.qa_verified_id == 60


def test_purge_advances_past_all_when_all_pass(qapp, tmp_path):
    """When every open entry passes, purge advances past the max id."""
    entries = [_entry(70, steps=("s1",)), _entry(71, steps=("s2",))]
    config = _FakeConfig(
        qa_step_results={"70": {"0": _pass_rec()}, "71": {"0": _pass_rec()}},
        config_dir=tmp_path,
    )
    win = _build_window(qapp, config, entries)

    win._on_purge()

    assert config.qa_verified_id == 71
    assert win._open_entries() == []


def test_all_complete_false_for_empty_open_entries(qapp, tmp_path):
    """_all_complete() must return False (not crash) with no open entries."""
    config = _FakeConfig(config_dir=tmp_path)
    win = _build_window(qapp, config, [])
    assert win._all_complete([]) is False


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Fail note + attachment persistence
# ═══════════════════════════════════════════════════════════════════════════════

def test_note_saved_to_record(qapp, tmp_path):
    """Setting a failed step's note stores it on the record."""
    entries = [_entry(80, steps=("step",))]
    config = _FakeConfig(
        qa_step_results={"80": {"0": {"state": "fail", "note": "", "attachments": []}}},
        config_dir=tmp_path,
    )
    win = _build_window(qapp, config, entries)

    win._on_note_changed(80, 0, "the button did nothing")

    assert config.qa_step_results["80"]["0"]["note"] == "the button did nothing"


def test_attachment_appended_under_config_dir(qapp, tmp_path):
    """A simulated attach appends an abs path that lives under the config dir."""
    entries = [_entry(81, steps=("step",))]
    config = _FakeConfig(
        qa_step_results={"81": {"0": {"state": "fail", "note": "", "attachments": []}}},
        config_dir=tmp_path,
    )
    win = _build_window(qapp, config, entries)

    fake_png = tmp_path / "shot.png"
    fake_png.write_bytes(b"\x89PNG\r\n")
    dest = win._copy_into_attachments(81, 0, str(fake_png))
    win._append_attachment(81, 0, dest)

    atts = config.qa_step_results["81"]["0"]["attachments"]
    assert dest in atts
    assert str(tmp_path) in dest  # path under the (tmp) config dir


def test_image_save_writes_png_under_config_dir(qapp, tmp_path):
    """Saving a QImage writes a PNG under <config_dir>/qa_attachments/."""
    from PyQt6.QtGui import QImage

    entries = [_entry(82, steps=("step",))]
    config = _FakeConfig(
        qa_step_results={"82": {"0": {"state": "fail", "note": "", "attachments": []}}},
        config_dir=tmp_path,
    )
    win = _build_window(qapp, config, entries)

    img = QImage(4, 4, QImage.Format.Format_RGB32)
    img.fill(0)
    path = win._save_image(82, 0, img)

    assert path
    assert Path(path).exists()
    assert (tmp_path / "qa_attachments") in Path(path).parents


# ═══════════════════════════════════════════════════════════════════════════════
# 7. AI failures digest
# ═══════════════════════════════════════════════════════════════════════════════

def test_digest_written_with_failure_details(qapp, tmp_path):
    """Marking a fail with a note writes qa_failures.md with title/step/note."""
    entries = [_entry(90, steps=("Click the widget",))]
    config = _FakeConfig(config_dir=tmp_path)
    win = _build_window(qapp, config, entries)

    win._on_mark(90, 0, "fail")
    win._on_note_changed(90, 0, "crashed instantly")

    digest = tmp_path / "qa_failures.md"
    assert digest.exists()
    text = digest.read_text()
    assert "Entry 90" in text
    assert "Click the widget" in text
    assert "crashed instantly" in text


def test_digest_says_no_failures_when_clean(qapp, tmp_path):
    """With zero failures the digest says 'No failures recorded.' (not deleted)."""
    entries = [_entry(91, steps=("step",))]
    config = _FakeConfig(
        qa_step_results={"91": {"0": _pass_rec()}},
        config_dir=tmp_path,
    )
    win = _build_window(qapp, config, entries)
    win._write_digest()

    digest = tmp_path / "qa_failures.md"
    assert digest.exists()
    assert "No failures recorded." in digest.read_text()


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Build stamp + re-test nudge
# ═══════════════════════════════════════════════════════════════════════════════

def test_mark_stamps_current_sha(qapp, tmp_path):
    """A mark records the window's current HEAD sha onto the record."""
    entries = [_entry(95, steps=("step",))]
    config = _FakeConfig(config_dir=tmp_path)
    win = _build_window(qapp, config, entries)
    win._current_sha = "abc1234"

    win._on_mark(95, 0, "pass")

    assert config.qa_step_results["95"]["0"]["sha"] == "abc1234"


def test_stale_hint_rendered_when_sha_differs(qapp, tmp_path):
    """A stored sha != current HEAD surfaces a re-test hint label."""
    entries = [_entry(96, steps=("step",))]
    config = _FakeConfig(
        qa_step_results={"96": {"0": {"state": "pass", "sha": "oldsha1", "ts": ""}}},
        config_dir=tmp_path,
    )
    win = _build_window(qapp, config, entries)
    # Inject a differing current HEAD and redraw.
    win._on_sha_ready("newsha2")

    # Walk the body layout for a label carrying the stale hint style token.
    from metatv.gui import theme as _theme
    from PyQt6.QtWidgets import QLabel

    found = False
    for i in range(win._body_layout.count()):
        w = win._body_layout.itemAt(i).widget()
        if w is None:
            continue
        for lbl in w.findChildren(QLabel):
            if lbl.styleSheet() == _theme.QA_STALE_HINT:
                found = True
    assert found, "expected a stale re-test hint label when sha differs"


def test_digest_marks_stale_failure(qapp, tmp_path):
    """A failed step tested on an older sha is flagged STALE in the digest."""
    entries = [_entry(97, steps=("step",))]
    config = _FakeConfig(
        qa_step_results={
            "97": {"0": {"state": "fail", "sha": "oldsha1", "ts": "", "note": "boom"}}
        },
        config_dir=tmp_path,
    )
    win = _build_window(qapp, config, entries)
    win._current_sha = "newsha2"
    win._write_digest()

    text = (tmp_path / "qa_failures.md").read_text()
    assert "STALE" in text


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Regression guard: real WHATS_NEW entries load with test_steps == ()
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


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Config round-trips
# ═══════════════════════════════════════════════════════════════════════════════

def test_config_qa_step_results_round_trip(tmp_path):
    """qa_step_results round-trips through Config.save()/load()."""
    import yaml
    from metatv.core.config import Config

    config = Config(config_dir=tmp_path, data_dir=tmp_path, cache_dir=tmp_path)
    config.qa_step_results = {
        "10": {"0": {"state": "fail", "sha": "abc", "ts": "t", "note": "x",
                     "attachments": ["/p"], "log": "/l"}},
    }
    config.qa_verified_id = 10
    config.save()

    with open(tmp_path / "config.yaml") as f:
        data = yaml.safe_load(f)
    loaded = Config(**data)

    assert loaded.qa_verified_id == 10
    assert loaded.qa_step_results["10"]["0"]["state"] == "fail"
    assert loaded.qa_step_results["10"]["0"]["note"] == "x"


def test_config_qa_step_results_default_empty(tmp_path):
    """qa_step_results defaults to an empty dict for a fresh Config."""
    from metatv.core.config import Config

    config = Config(config_dir=tmp_path, data_dir=tmp_path, cache_dir=tmp_path)
    assert config.qa_step_results == {}


# ═══════════════════════════════════════════════════════════════════════════════
# 11. PR# parser — _parse_pr_number
# ═══════════════════════════════════════════════════════════════════════════════

def test_parse_pr_number_extracts_from_squash_subject():
    from metatv.gui.qa_checklist_window import _parse_pr_number
    assert _parse_pr_number("feat(x): thing (#183)") == 183


def test_parse_pr_number_extracts_large_number():
    from metatv.gui.qa_checklist_window import _parse_pr_number
    assert _parse_pr_number("fix(series): hide overlay (#1042)") == 1042


def test_parse_pr_number_returns_none_when_absent():
    from metatv.gui.qa_checklist_window import _parse_pr_number
    assert _parse_pr_number("chore: update deps") is None


def test_parse_pr_number_returns_none_for_empty_subject():
    from metatv.gui.qa_checklist_window import _parse_pr_number
    assert _parse_pr_number("") is None


# ═══════════════════════════════════════════════════════════════════════════════
# 12. Remote URL normalizer — _normalize_remote_url
# ═══════════════════════════════════════════════════════════════════════════════

def test_normalize_ssh_remote_url():
    from metatv.gui.qa_checklist_window import _normalize_remote_url
    assert _normalize_remote_url("git@github.com:ryansinn/metatv.git") == \
        "https://github.com/ryansinn/metatv"


def test_normalize_https_remote_url():
    from metatv.gui.qa_checklist_window import _normalize_remote_url
    assert _normalize_remote_url("https://github.com/ryansinn/metatv.git") == \
        "https://github.com/ryansinn/metatv"


def test_normalize_https_remote_url_without_git_suffix():
    from metatv.gui.qa_checklist_window import _normalize_remote_url
    assert _normalize_remote_url("https://github.com/ryansinn/metatv") == \
        "https://github.com/ryansinn/metatv"


def test_normalize_ssh_url_with_org_slash_repo():
    from metatv.gui.qa_checklist_window import _normalize_remote_url
    assert _normalize_remote_url("git@github.com:org/nested-repo.git") == \
        "https://github.com/org/nested-repo"


# ═══════════════════════════════════════════════════════════════════════════════
# 13. Header link rendering — _apply_git_refs
# ═══════════════════════════════════════════════════════════════════════════════

def test_header_link_shows_pr_href_when_resolved(qapp, tmp_path):
    entries = [_entry(100, steps=("step",))]
    config = _FakeConfig(config_dir=tmp_path)
    win = _build_window(qapp, config, entries)

    win._on_git_refs_ready({
        100: {"pr_number": 183, "commit_hash": None,
              "base_url": "https://github.com/ryansinn/metatv"}
    })

    lbl = win._ref_labels.get(100)
    assert lbl is not None
    assert 'href="https://github.com/ryansinn/metatv/pull/183"' in lbl.text()
    assert lbl.openExternalLinks() is True


def test_header_link_shows_commit_href_when_no_pr(qapp, tmp_path):
    entries = [_entry(101, steps=("step",))]
    config = _FakeConfig(config_dir=tmp_path)
    win = _build_window(qapp, config, entries)

    win._on_git_refs_ready({
        101: {"pr_number": None, "commit_hash": "abc1234",
              "base_url": "https://github.com/ryansinn/metatv"}
    })

    lbl = win._ref_labels.get(101)
    assert lbl is not None
    assert 'href="https://github.com/ryansinn/metatv/commit/abc1234"' in lbl.text()


def test_header_link_falls_back_to_date_when_no_git(qapp, tmp_path):
    entries = [_entry(102, steps=("step",))]
    config = _FakeConfig(config_dir=tmp_path)
    win = _build_window(qapp, config, entries)

    win._on_git_refs_ready({
        102: {"pr_number": None, "commit_hash": None, "base_url": None}
    })

    lbl = win._ref_labels.get(102)
    assert lbl is not None
    assert "href" not in lbl.text()
    assert "2026-06-23" in lbl.text()


# ═══════════════════════════════════════════════════════════════════════════════
# 14. Per-entry archive / unarchive
# ═══════════════════════════════════════════════════════════════════════════════

def test_complete_entry_archive_persists(qapp, tmp_path):
    entries = [_entry(200, steps=("step A", "step B"))]
    config = _FakeConfig(
        qa_step_results={"200": {"0": _pass_rec(), "1": _pass_rec()}},
        config_dir=tmp_path,
    )
    win = _build_window(qapp, config, entries)
    prior = config.save_calls

    win._on_archive(200)

    assert 200 in config.qa_archived_ids
    assert config.save_calls > prior


def test_incomplete_entry_remains_open(qapp, tmp_path):
    entries = [_entry(201, steps=("step A", "step B"))]
    config = _FakeConfig(
        qa_step_results={"201": {"0": _pass_rec()}},
        config_dir=tmp_path,
    )
    win = _build_window(qapp, config, entries)

    assert 201 in [e.id for e in win._open_entries()]


def test_archived_entry_excluded_from_open_entries(qapp, tmp_path):
    entries = [_entry(210, steps=("step A",)), _entry(211, steps=("step B",))]
    config = _FakeConfig(
        qa_step_results={"210": {"0": _pass_rec()}, "211": {"0": _pass_rec()}},
        qa_archived_ids=[210],
        config_dir=tmp_path,
    )
    win = _build_window(qapp, config, entries)

    open_ids = [e.id for e in win._open_entries()]
    assert 210 not in open_ids
    assert 211 in open_ids


def test_unarchive_restores_entry(qapp, tmp_path):
    entries = [_entry(221, steps=("step",))]
    config = _FakeConfig(
        qa_step_results={"221": {"0": _pass_rec()}},
        qa_archived_ids=[221],
        config_dir=tmp_path,
    )
    win = _build_window(qapp, config, entries)

    win._on_unarchive(221)

    assert 221 not in config.qa_archived_ids
    assert 221 in [e.id for e in win._open_entries()]


def test_config_qa_archived_ids_round_trip(tmp_path):
    import yaml
    from metatv.core.config import Config

    config = Config(config_dir=tmp_path, data_dir=tmp_path, cache_dir=tmp_path)
    config.qa_archived_ids = [10, 23, 47]
    config.save()

    with open(tmp_path / "config.yaml") as f:
        data = yaml.safe_load(f)
    loaded = Config(**data)

    assert loaded.qa_archived_ids == [10, 23, 47]


# ═══════════════════════════════════════════════════════════════════════════════
# 15. Archived section — collapsible (Commit 1, issue #92)
# ═══════════════════════════════════════════════════════════════════════════════

def test_archived_section_defaults_collapsed(qapp, tmp_path):
    """Archived section _qa_collapsed flag must be True when qa_archived_collapsed=True."""
    entries = [_entry(300, steps=("step A",))]
    config = _FakeConfig(
        qa_step_results={"300": {"0": _pass_rec()}},
        qa_archived_ids=[300],
        qa_archived_collapsed=True,
        config_dir=tmp_path,
    )
    win = _build_window(qapp, config, entries)

    assert win._archived_container is not None, "archived_container must exist"
    # Use the explicit flag rather than isVisible(), which is unreliable in
    # headless test environments (parent window never shown → always False).
    assert getattr(win._archived_container, "_qa_collapsed", None) is True, (
        "archived container _qa_collapsed must be True when qa_archived_collapsed=True"
    )


def test_archived_section_expands_when_collapsed_false(qapp, tmp_path):
    """Archived section _qa_collapsed flag must be False when qa_archived_collapsed=False."""
    entries = [_entry(301, steps=("step A",))]
    config = _FakeConfig(
        qa_step_results={"301": {"0": _pass_rec()}},
        qa_archived_ids=[301],
        qa_archived_collapsed=False,
        config_dir=tmp_path,
    )
    win = _build_window(qapp, config, entries)

    assert win._archived_container is not None
    assert getattr(win._archived_container, "_qa_collapsed", None) is False, (
        "archived container _qa_collapsed must be False when qa_archived_collapsed=False"
    )


def test_archived_toggle_flips_collapsed_state_and_persists(qapp, tmp_path):
    """Clicking the archived toggle flips qa_archived_collapsed and saves."""
    entries = [_entry(302, steps=("step",))]
    config = _FakeConfig(
        qa_step_results={"302": {"0": _pass_rec()}},
        qa_archived_ids=[302],
        qa_archived_collapsed=True,   # start collapsed
        config_dir=tmp_path,
    )
    win = _build_window(qapp, config, entries)
    prior_saves = config.save_calls

    # Simulate click via the toggle button.
    assert win._archived_toggle_btn is not None
    win._archived_toggle_btn.click()

    # _qa_collapsed flag now False; config persisted.
    assert getattr(win._archived_container, "_qa_collapsed", True) is False, (
        "_qa_collapsed must be False after expanding"
    )
    assert config.qa_archived_collapsed is False
    assert config.save_calls > prior_saves


def test_archived_toggle_re_collapses(qapp, tmp_path):
    """A second toggle click re-collapses the archived section."""
    entries = [_entry(303, steps=("step",))]
    config = _FakeConfig(
        qa_step_results={"303": {"0": _pass_rec()}},
        qa_archived_ids=[303],
        qa_archived_collapsed=False,  # start expanded
        config_dir=tmp_path,
    )
    win = _build_window(qapp, config, entries)

    # Click once → collapse.
    win._archived_toggle_btn.click()
    assert getattr(win._archived_container, "_qa_collapsed", False) is True
    assert config.qa_archived_collapsed is True


def test_archived_section_absent_when_no_archived_entries(qapp, tmp_path):
    """With no archived entries the archived container should not be rendered."""
    entries = [_entry(304, steps=("step",))]
    config = _FakeConfig(config_dir=tmp_path)
    win = _build_window(qapp, config, entries)

    assert win._archived_container is None, (
        "archived_container must be None when there are no archived entries"
    )

