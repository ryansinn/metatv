"""Dev-QA state leaves the user's config file.

Owner: *"qa_step_results should be purged out of the config and not written
back to it ... those are always going to grow, but they're supposed to be used
by you, claude, to reference how your PRs and commits land, basically the
technical side of the What's New for QA testing."*

Measured on their config: the nine ``qa_*`` fields are **1,797 of 4,768 lines —
38%** — and every one of the **130** ``config.save()`` call sites rewrote all
of it. It is not configuration; it is a growing dev record.

It now lives in ``qa_state.yaml`` beside config.yaml, and the two files are
compared and written **independently**: ticking a QA step does not touch
config.yaml, and changing a setting does not rewrite the QA record.

The field set is DERIVED from the ``qa_`` prefix, not enumerated, so a tenth
field lands in the sidecar without anyone remembering this file exists.
"""
from __future__ import annotations

import pytest
import yaml

from metatv.core.config import QA_STATE_FILENAME, Config, _qa_field_names


@pytest.fixture()
def cfg(tmp_path):
    return Config(config_dir=tmp_path / "cfg", data_dir=tmp_path / "data",
                  cache_dir=tmp_path / "cache")


def _read(path):
    return yaml.safe_load(path.read_text()) or {}


# ── the split ──────────────────────────────────────────────────────────────


def test_qa_state_is_not_written_into_config_yaml(cfg):
    cfg.qa_step_results = {"e1_s0": {"state": "pass"}}
    cfg.save()
    main = _read(cfg.config_dir / "config.yaml")
    assert [k for k in main if k.startswith("qa_")] == [], (
        "QA state is still in config.yaml — 38% of the file, rewritten by all "
        "130 save() call sites")


def test_qa_state_is_written_to_the_sidecar(cfg):
    cfg.qa_flagged_items = [{"id": "x", "title": "a thing"}]
    cfg.save()
    qa = _read(cfg.config_dir / QA_STATE_FILENAME)
    assert qa["qa_flagged_items"] == [{"id": "x", "title": "a thing"}]


def test_the_field_set_is_derived_from_the_prefix():
    """Not a hand-kept list — the failure mode this codebase keeps hitting."""
    names = _qa_field_names(Config)
    assert "qa_step_results" in names and "qa_flagged_items" in names
    assert len(names) >= 9
    assert all(n.startswith("qa_") for n in names)
    assert "sidebar_width" not in names


# ── independence, which is the actual point ────────────────────────────────


def test_a_qa_tick_does_not_rewrite_config_yaml(cfg, monkeypatch):
    """The reason for the whole change."""
    cfg.save()
    main_path = cfg.config_dir / "config.yaml"
    before = main_path.read_bytes()
    stamp = main_path.stat().st_mtime_ns

    cfg.qa_step_results = {"e2_s1": {"state": "fail"}}
    cfg.save()

    assert main_path.read_bytes() == before, "config.yaml was rewritten by a QA tick"
    assert main_path.stat().st_mtime_ns == stamp, "config.yaml was touched"
    assert _read(cfg.config_dir / QA_STATE_FILENAME)["qa_step_results"] == {
        "e2_s1": {"state": "fail"}}


def test_a_settings_change_does_not_rewrite_the_qa_record(cfg):
    cfg.qa_step_results = {"e1_s0": {"state": "pass"}}
    cfg.save()
    qa_path = cfg.config_dir / QA_STATE_FILENAME
    stamp = qa_path.stat().st_mtime_ns

    cfg.sidebar_width = 404
    cfg.save()

    assert qa_path.stat().st_mtime_ns == stamp, (
        "a settings change rewrote the QA record, which is the mirror of the "
        "bug this fixes")
    assert _read(cfg.config_dir / "config.yaml")["sidebar_width"] == 404


def test_a_user_who_never_runs_dev_mode_gets_no_sidecar(cfg):
    """No empty file for people who will never have QA state."""
    cfg.sidebar_width = 500
    cfg.save()
    assert not (cfg.config_dir / QA_STATE_FILENAME).exists()


# ── migration: nothing may be lost ─────────────────────────────────────────


def test_an_old_config_with_inline_qa_state_still_loads_it(tmp_path):
    """A config.yaml written before the split must keep working.

    This is the migration, and it is the case that loses a tester's whole
    record if it is wrong.
    """
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.yaml").write_text(yaml.safe_dump({
        "sidebar_width": 333,
        "qa_step_results": {"e9_s0": {"state": "pass"}},
        "qa_verified_id": 42,
    }))

    merged = Config._merge_qa_sidecar(cfg_dir, yaml.safe_load(
        (cfg_dir / "config.yaml").read_text()))
    c = Config(**merged, config_dir=cfg_dir,
               data_dir=tmp_path / "d", cache_dir=tmp_path / "x")

    assert c.qa_step_results == {"e9_s0": {"state": "pass"}}
    assert c.qa_verified_id == 42
    assert c.sidebar_width == 333


def test_the_next_save_moves_inline_state_into_the_sidecar(tmp_path):
    """And having loaded it, the next write relocates it — no manual step."""
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.yaml").write_text(yaml.safe_dump({
        "qa_step_results": {"e9_s0": {"state": "pass"}},
    }))
    merged = Config._merge_qa_sidecar(cfg_dir, yaml.safe_load(
        (cfg_dir / "config.yaml").read_text()))
    c = Config(**merged, config_dir=cfg_dir,
               data_dir=tmp_path / "d", cache_dir=tmp_path / "x")
    c.save()

    assert _read(cfg_dir / QA_STATE_FILENAME)["qa_step_results"] == {
        "e9_s0": {"state": "pass"}}
    assert [k for k in _read(cfg_dir / "config.yaml") if k.startswith("qa_")] == []


def test_the_sidecar_wins_over_a_stale_inline_copy(tmp_path):
    """Both present means config.yaml predates the split, so it is the older one."""
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir(parents=True)
    data = {"qa_verified_id": 1}
    (cfg_dir / QA_STATE_FILENAME).write_text(yaml.safe_dump({"qa_verified_id": 99}))

    merged = Config._merge_qa_sidecar(cfg_dir, data)
    assert merged["qa_verified_id"] == 99


def test_a_corrupt_sidecar_does_not_stop_the_app_loading(tmp_path):
    """Losing a dev tick list must never cost someone their actual settings."""
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / QA_STATE_FILENAME).write_text("{{{ not yaml at all")

    merged = Config._merge_qa_sidecar(cfg_dir, {"sidebar_width": 250})
    assert merged["sidebar_width"] == 250


def test_a_sidecar_that_is_not_a_mapping_is_ignored(tmp_path):
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / QA_STATE_FILENAME).write_text(yaml.safe_dump(["not", "a", "mapping"]))
    merged = Config._merge_qa_sidecar(cfg_dir, {"sidebar_width": 250})
    assert merged["sidebar_width"] == 250


def test_the_sidecar_cannot_smuggle_in_non_qa_keys(tmp_path):
    """A stray key in the sidecar must not override a real setting."""
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / QA_STATE_FILENAME).write_text(yaml.safe_dump({
        "qa_verified_id": 7, "sidebar_width": 9999,
    }))
    merged = Config._merge_qa_sidecar(cfg_dir, {"sidebar_width": 250})
    assert merged["qa_verified_id"] == 7
    assert merged["sidebar_width"] == 250, "a non-qa key leaked out of the sidecar"


def test_both_load_paths_merge_the_sidecar():
    """Including backup-restore, or a recovered config silently loses QA state."""
    import inspect
    assert inspect.getsource(Config.load).count("_merge_qa_sidecar(") == 2
