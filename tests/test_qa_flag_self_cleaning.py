"""Behavioral tests for QA flagged-item self-cleaning.

A flagged item that a later ``WhatsNewEntry`` claims via
``addresses=("flagged:<id>")`` auto-files into the collapsed "✓ Resolved"
sub-section, leaving the active Flagged list to show only items still needing
work — the tester never manually marks a fixed flag done.

These execute the real ``QAChecklistWindow`` render path (headless Qt) and
assert the active/resolved split, the count, and the collapse default.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


class _Cfg:
    """Minimal Config stand-in; config_dir is a tmp dir so digests stay isolated."""

    def __init__(self, flagged: list[dict], config_dir: Path) -> None:
        self.qa_verified_id = 0
        self.qa_step_results: dict = {}
        self.qa_archived_ids: list = []
        self.qa_archived_collapsed = True
        self.qa_flagged_items = flagged
        self.qa_flagged_collapsed = False
        self.qa_resolved_collapsed = True
        self.qa_addressed: dict = {}
        self.config_dir = config_dir
        self.save_calls = 0

    def save(self) -> None:
        self.save_calls += 1


def _entry(eid: int, steps=(), addresses=()) -> SimpleNamespace:
    return SimpleNamespace(
        id=eid, version="0.9.0", date="2026-06-28", title=f"Entry {eid}",
        items=("x",), test_steps=steps, addresses=addresses,
    )


def _flag(item_id: str, title: str = "thing") -> dict:
    return {
        "id": item_id, "created": "2026-06-28T00:00:00+00:00", "build_sha": "abc",
        "title": title, "note": "", "attachments": [], "status": "open", "type": "bug",
    }


def _win(qapp, config, entries):
    from metatv.gui.qa_checklist_window import QAChecklistWindow
    return QAChecklistWindow(config, entries)  # type: ignore[arg-type]


def test_addressed_flag_is_resolved(qapp, tmp_path):
    """An entry addressing 'flagged:AAA' makes that flag report resolved."""
    cfg = _Cfg([_flag("AAA")], tmp_path)
    win = _win(qapp, cfg, [_entry(91, ("verify the fix",), ("flagged:AAA",))])
    assert win._is_flagged_resolved("AAA") is True


def test_unaddressed_flag_stays_active(qapp, tmp_path):
    """With no addressing entry the flag stays active and no Resolved group renders."""
    cfg = _Cfg([_flag("BBB")], tmp_path)
    win = _win(qapp, cfg, [_entry(91, ("step",))])  # addresses=() default
    assert win._is_flagged_resolved("BBB") is False
    assert win._resolved_container is None


def test_resolved_item_filed_out_of_active_list(qapp, tmp_path):
    """Addressed flag goes to the Resolved container; unaddressed stays active."""
    cfg = _Cfg([_flag("CCC"), _flag("DDD")], tmp_path)
    win = _win(qapp, cfg, [_entry(91, ("step",), ("flagged:CCC",))])
    # Active container holds only the unaddressed item (DDD)…
    assert win._flagged_container.layout().count() == 1
    # …and the resolved container holds the addressed one (CCC).
    assert win._resolved_container is not None
    assert win._resolved_container.layout().count() == 1


def test_active_count_excludes_resolved(qapp, tmp_path):
    """Two addressed + one active → 1 active card, 2 resolved cards."""
    cfg = _Cfg([_flag("F1"), _flag("F2"), _flag("ACT")], tmp_path)
    win = _win(qapp, cfg, [_entry(91, ("s",), ("flagged:F1", "flagged:F2"))])
    assert win._flagged_container.layout().count() == 1
    assert win._resolved_container.layout().count() == 2


def test_resolved_subsection_collapsed_by_default(qapp, tmp_path):
    """The Resolved sub-section honors qa_resolved_collapsed (default True)."""
    cfg = _Cfg([_flag("EEE")], tmp_path)
    win = _win(qapp, cfg, [_entry(91, ("step",), ("flagged:EEE",))])
    assert getattr(win._resolved_container, "_qa_collapsed", None) is True
