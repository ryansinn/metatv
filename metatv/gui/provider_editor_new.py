"""Adding a source in the Sources editor — the one Add Source path.

There used to be a second one: ``AddProviderDialog``, which tested one address,
reported a bare HTTP code, had no icon picker, and taught a new user nothing
about where sources live. The owner's rule (2026-10-19, docs/UI_UX_GUIDELINES.md
"One process, never a parallel flow") retired it: every Add Source button opens
the Sources screen with a blank source in this mode, so a source is added on the
same form it is edited on.

The mode is a mixin on :class:`~metatv.gui.provider_editor.ProviderEditorView`
because it is a separate job (create, not update) sharing every field. Its rules:

* "Add Source" stays disabled until a connection test passes. A source cannot
  be added until it can be read; that was true of the dialog and stays true.
* Changing the credentials or the address list after a pass needs a new test —
  the pass was for what was tested. Renaming or picking an icon does not.
* Every test probes every address (``TestAllURLsThread``), and a total failure
  is explained by the editor's diagnosis panel, not just a status code.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from urllib.parse import urlparse

from loguru import logger

from metatv.core.database import ProviderDB
from metatv.core.models import Provider, ProviderURL
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.provider import provider_url_to_raw
from metatv.gui import icon_utils as _icon_utils

#: The Connection tab — where a new source starts (addresses and credentials).
_CONNECTION_TAB = 1


def default_name_for(url: str) -> str:
    """A name for a source nobody named: the host of its first address."""
    host = urlparse(url if "://" in url else f"http://{url}").hostname or ""
    return host or "New Source"


class _NewSourceMixin:
    """Create-mode for the Sources editor. See the module docstring."""

    _new_source: bool = False
    _new_tested_ok: bool = False

    # ── entering and leaving ────────────────────────────────────────────────

    def start_new_source(self) -> None:
        """Show a blank source ready to fill in, with Add Source gated on a test."""
        self._new_source = True
        self._new_tested_ok = False
        self._provider_id = None
        self._pending_account_info = None
        self._sync_analytics_tab()
        self._provider_urls = []
        self._pending_url_removals = set()
        self._loading = True
        try:
            self._name_input.clear()
            self._icon_picker.set_icon(self._suggested_icon())
            self._enabled_check.setChecked(True)
            self._username_input.clear()
            self._password_input.clear()
            self._new_url_input.clear()
            self._force_adult_check.setChecked(False)
            self._epg_enabled_check.setChecked(True)
            self._epg_url_override_input.clear()
            self._refresh_combo.setCurrentIndex(0)
            self._apply_account_info({})
            self._rebuild_url_list()
        finally:
            self._loading = False
        self._set_fields_enabled(True)
        self._diagnosis_lbl.hide()
        self._acct_error_lbl.hide()
        self._set_new_mode_chrome(True)
        self._tabs.setCurrentIndex(_CONNECTION_TAB)
        self._new_url_input.setFocus()

    def _leave_new_mode(self) -> None:
        """Back to editing an existing source (called on every load)."""
        if self._new_source:
            self._new_source = False
            self._new_tested_ok = False
            self._set_new_mode_chrome(False)

    def _set_new_mode_chrome(self, new: bool) -> None:
        """Hide what only an existing source has; relabel the primary button."""
        for w in (self._delete_btn, self._footer_divider, self._status_dot_lbl,
                  self._action_refresh_btn,
                  self._epg_refresh_btn, self._action_toggle_btn,
                  self._refresh_acct_btn):
            w.setVisible(not new)
        self._discard_btn.setText("Cancel" if new else "Discard")
        self._test_btn.setText("Test Connection")
        self._test_btn.setEnabled(True)
        _icon_utils.clear_button_icon(self._test_btn)
        if new:
            self._save_btn.setText("Add Source")
            self._sync_add_button()
        else:
            self._save_btn.setText("Save Changes")
            self._save_btn.setEnabled(True)
            self._save_btn.setToolTip("")

    # ── the test gate ───────────────────────────────────────────────────────

    def _sync_add_button(self) -> None:
        self._save_btn.setEnabled(self._new_tested_ok)
        self._save_btn.setToolTip(
            "" if self._new_tested_ok
            else "Test the connection first — a source is added once it connects")

    def _invalidate_new_test(self, *_args) -> None:
        """The credentials or addresses changed, so the last pass no longer counts."""
        if self._new_source and not self._loading and self._new_tested_ok:
            self._new_tested_ok = False
            self._test_btn.setText("Test Connection")
            _icon_utils.clear_button_icon(self._test_btn)
            self._sync_add_button()

    def _take_typed_url(self) -> None:
        """An address typed but not yet added is the one the user means to test."""
        if self._new_url_input.text().strip():
            self._add_url()

    def _new_test_finished(self, working: bool) -> None:
        self._new_tested_ok = working
        self._sync_add_button()

    # ── account info for a source that is not saved yet ─────────────────────

    def _draft_provider(self) -> Provider:
        urls = [pu.url for pu in self._provider_urls]
        return Provider(
            id="__new__", name="new", type="xtream", url=urls[0],
            urls=[ProviderURL(url=u) for u in urls],
            username=self._username_input.text().strip(),
            password=self._password_input.text().strip(),
        )

    # ── adding ──────────────────────────────────────────────────────────────

    def _suggested_icon(self) -> str:
        from metatv.gui.icons import pick_next_icon
        with self.db.session_scope(commit=False) as session:
            used = RepositoryFactory(session).providers.get_used_icons()
        return pick_next_icon(used)

    def _add_new_source(self) -> None:
        """Create the source from the form, then hand it to the host to load."""
        if not (self._new_source and self._new_tested_ok and self._provider_urls):
            return
        schedule = {0: "manual", 1: "launch", 2: "daily", 3: "weekly", 4: "monthly"}
        urls = self._provider_urls
        provider_id = str(uuid.uuid4())
        name = self._name_input.text().strip() or default_name_for(urls[0].url)
        with self.db.session_scope() as session:
            db_prov = ProviderDB(
                id=provider_id,
                name=name,
                type="xtream",
                url=urls[0].url,
                urls=[provider_url_to_raw(pu, priority=i) for i, pu in enumerate(urls)],
                username=self._username_input.text().strip(),
                password=self._password_input.text().strip(),
                icon=self._icon_picker.get_icon() or self._suggested_icon(),
                is_active=self._enabled_check.isChecked(),
                force_adult=self._force_adult_check.isChecked(),
                epg_enabled=self._epg_enabled_check.isChecked(),
                epg_url_override=self._epg_url_override_input.text().strip() or None,
                epg_refresh_interval=self._epg_interval_combo.currentData() or "default",
                refresh_schedule=schedule.get(self._refresh_combo.currentIndex(), "manual"),
            )
            info = self._pending_account_info
            if info:
                db_prov.account_status = info.get("status")
                db_prov.account_active_cons = info.get("active_cons", 0)
                db_prov.max_connections = info.get("max_connections", 1)
                db_prov.account_exp_date = self._parse_ts(info.get("exp_date"))
                db_prov.account_created_at = self._parse_ts(info.get("created_at"))
            db_prov.updated_at = datetime.now()
            session.add(db_prov)
        logger.info("Source '{}' added ({} address(es))", name, len(urls))
        epg = self._epg_enabled_check.isChecked()
        self._leave_new_mode()
        self.provider_added.emit(provider_id, epg)

    def _cancel_new_source(self) -> None:
        self._leave_new_mode()
        self.new_source_cancelled.emit()
