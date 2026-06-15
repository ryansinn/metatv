"""Behavioral tests for PR-3 — provider-editor button UX.

Covers:
  A. Save-button dirty/saved cycle.
  B. Test Connection tooltip.
  C. Source-switch button-state reset.
  D. Discard no-op bug fix (force=True).

All tests execute the real code paths and assert the outcome that regresses.
No shape-only assertions.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication, QPushButton, QLineEdit

from metatv.gui import icons as _icons


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# ── helpers ──────────────────────────────────────────────────────────────────

def _bare_editor(qapp):
    """Minimal ProviderEditorView instance with just the attributes each method
    touches, built via ``__new__`` to avoid a real Database at construction time."""
    from metatv.gui.provider_editor import ProviderEditorView
    ed = ProviderEditorView.__new__(ProviderEditorView)
    ed._loading = False
    ed._save_btn = QPushButton("Save Changes")
    ed._save_btn.setEnabled(True)
    ed._test_btn = QPushButton("Test Connection")
    ed._test_btn.setEnabled(True)
    return ed


@pytest.fixture()
def file_db(tmp_path):
    """File-backed Database (not :memory:) so pooled connections share tables."""
    from metatv.core.database import Database
    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.create_tables()
    yield d
    d.close()


def _seed_provider(db, name: str = "TestProv", username: str = "u1") -> str:
    """Insert a ProviderDB row and return its id."""
    from metatv.core.database import ProviderDB
    pid = str(uuid.uuid4())
    with db.session_scope() as session:
        session.add(ProviderDB(
            id=pid,
            name=name,
            type="xtream",
            url="http://example.com:8080",
            username=username,
            password="pass",
            urls=[{"url": "http://example.com:8080", "priority": 0,
                   "is_active": True, "success_count": 0, "failure_count": 0}],
        ))
    return pid


# ─────────────────────────────────────────────────────────────────────────────
# A. Save → dirty cycle
# ─────────────────────────────────────────────────────────────────────────────

def test_mark_dirty_restores_save_button(qapp):
    """After a successful save, _mark_dirty must restore the button text and
    re-enable it — proving the next edit clears the "Saved" indicator."""
    ed = _bare_editor(qapp)
    # Simulate the post-save state that _save() sets
    ed._save_btn.setText(f"{_icons.notification_success_icon} Saved")
    ed._save_btn.setEnabled(False)

    ed._mark_dirty()

    assert ed._save_btn.text() == "Save Changes"
    assert ed._save_btn.isEnabled()


def test_mark_dirty_blocked_while_loading(qapp):
    """_mark_dirty must be a no-op while _loading is True.

    The _loading guard prevents programmatic field-population in load_provider()
    from falsely marking the form dirty.  Without it, loading a provider would
    immediately re-enable and re-label the Save button.
    """
    ed = _bare_editor(qapp)
    # Put into post-save state
    ed._save_btn.setText(f"{_icons.notification_success_icon} Saved")
    ed._save_btn.setEnabled(False)

    ed._loading = True
    ed._mark_dirty()

    # Button must be unchanged — the loading guard short-circuited the method.
    assert ed._save_btn.text() == f"{_icons.notification_success_icon} Saved"
    assert not ed._save_btn.isEnabled()


# ─────────────────────────────────────────────────────────────────────────────
# B. Test Connection tooltip
# ─────────────────────────────────────────────────────────────────────────────

def test_test_connection_tooltip_set(qapp, file_db):
    """The Test Connection button must carry a tooltip that includes 're-test'
    so users know the button is still actionable after results are displayed."""
    from metatv.gui.provider_editor import ProviderEditorView
    pid = _seed_provider(file_db)
    # Construct a real editor — this calls _setup_ui which builds _test_btn with its tooltip.
    ed = ProviderEditorView(file_db)
    assert "re-test" in ed._test_btn.toolTip()


# ─────────────────────────────────────────────────────────────────────────────
# C. Source-switch resets per-source button state
# ─────────────────────────────────────────────────────────────────────────────

def test_source_switch_resets_both_buttons(qapp, file_db):
    """Switching providers must reset Test Connection text and the Save-button
    state so the previous source's results don't bleed through.

    Pin the concrete regression: a user tests provider A (button shows
    "3/3 working"), saves (button shows "Saved"/disabled), then clicks provider B
    in the sidebar.  Both buttons must read "Test Connection" / "Save Changes"
    after load_provider() for B completes.
    """
    from metatv.gui.provider_editor import ProviderEditorView

    pid_a = _seed_provider(file_db, name="ProvA", username="ua")
    pid_b = _seed_provider(file_db, name="ProvB", username="ub")

    ed = ProviderEditorView(file_db)
    ed.load_provider(pid_a)

    # Simulate stale button state from previous operations on provider A
    ed._test_btn.setText("3/3 working")
    ed._save_btn.setText(f"{_icons.notification_success_icon} Saved")
    ed._save_btn.setEnabled(False)

    # Switch to provider B — must reset both
    ed.load_provider(pid_b)

    assert ed._test_btn.text() == "Test Connection"
    assert ed._test_btn.isEnabled()
    assert ed._save_btn.text() == "Save Changes"
    assert ed._save_btn.isEnabled()


# ─────────────────────────────────────────────────────────────────────────────
# D. Discard no-op bug (force=True)
# ─────────────────────────────────────────────────────────────────────────────

def test_load_provider_force_defeats_same_id_guard(qapp, file_db):
    """load_provider(pid, force=True) must reload even when pid == _provider_id.

    The original bug: _discard() called load_provider(self._provider_id) which
    short-circuited on `if provider_id == self._provider_id: return`, so Discard
    was a no-op and unsaved edits were never reverted.

    This test drives the fix directly: load a provider, mutate a field,
    call load_provider(same_pid, force=True), and assert the field reverts to
    the DB value.
    """
    from metatv.gui.provider_editor import ProviderEditorView

    pid = _seed_provider(file_db, name="Original Name", username="origuser")
    ed = ProviderEditorView(file_db)
    ed.load_provider(pid)

    # Sanity: initial load populated the field
    assert ed._name_input.text() == "Original Name"

    # Simulate the user typing a new name (unsaved edit)
    ed._name_input.setText("Changed by user")
    assert ed._name_input.text() == "Changed by user"

    # Force-reload (what _discard() now calls) — must revert to DB value
    ed.load_provider(pid, force=True)
    assert ed._name_input.text() == "Original Name"


def test_discard_reverts_unsaved_edits(qapp, file_db):
    """_discard() must call load_provider with force=True, reverting edits.

    This is the end-to-end regression test for the discard no-op bug.
    """
    from metatv.gui.provider_editor import ProviderEditorView

    pid = _seed_provider(file_db, name="Stable Name", username="stableuser")
    ed = ProviderEditorView(file_db)
    ed.load_provider(pid)

    # Mutate a field without saving
    ed._name_input.setText("Unsaved Edit")

    # Discard must revert
    ed._discard()
    assert ed._name_input.text() == "Stable Name"
