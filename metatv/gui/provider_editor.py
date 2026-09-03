"""Provider editor — center-panel view for managing IPTV sources.

Embedded inside :class:`~metatv.gui.sources_manager_view.SourcesManagerView`'s
center pane (never added to the content stack directly). Selecting a different
source in the left column switches the editor to that provider without leaving
the view.

Wave 7 relayout: the detail pane is a ``QTabWidget`` (Summary / Connection /
Settings — content builders in ``provider_editor_tabs.py``, kept in a separate
module to stay under the project's 1000-line file limit) with a PERSISTENT
footer (Delete / Test Connection / Discard / Save Changes) below the tabs,
always visible regardless of the selected tab — Save/Discard apply to the
whole source, not to one tab, so a commit bar living inside a tab would wrongly
imply per-tab saving. The four per-row action buttons the pre-Wave-7 left
column rendered (refresh / analyze / EPG-refresh / enable-toggle — see
``sidebar/sources.py``'s ``ProviderItemWidget``) now live in the Summary tab's
action bar (``_build_action_bar``), wired to the SAME signals/handlers the row
buttons used — see the class docstring below for exactly how each was
re-pointed.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)
from loguru import logger

from metatv.core.database import Database, ProviderDB
from metatv.core.models import Provider, ProviderURL
from metatv.core.connection_diagnosis import diagnose
from metatv.gui.connection_diagnosis_text import _DIAGNOSIS_TEXT
from metatv.core.provider_probe import ProbeResult, ProbeStatus, probe_all_urls
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.provider import provider_url_to_raw
from metatv.gui import cursor_affordance
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.provider_editor_tabs import _ProviderEditorTabsMixin
from metatv.gui import deferred_config_save as _cfgsave

def _format_probe_message(result: ProbeResult) -> str:
    """Render a :class:`ProbeResult` into a short badge string (UI layer).

    Presentation lives here, not in ``core.provider_probe``, so the probe module
    stays UI-free and locale-free.
    """
    s = result.status
    if s is ProbeStatus.ACTIVE:
        return f"Active  {result.latency_ms} ms"
    if s is ProbeStatus.INACTIVE:
        return f"Account {result.detail}"
    if s is ProbeStatus.AUTH_FAILED:
        return "Auth failed"
    if s is ProbeStatus.HTTP_ERROR:
        return f"HTTP {result.detail}"
    if s is ProbeStatus.TIMEOUT:
        return "Timeout"
    return result.detail or "Error"


# ──────────────────────────────────────────────────────────────────────────────
# Background thread — fetches account info from provider API
# ──────────────────────────────────────────────────────────────────────────────

class FetchAccountInfoThread(QThread):
    """Fetches live account/subscription info from the Xtream auth endpoint."""

    finished = pyqtSignal(bool, object)  # success, info_dict | error_str

    def __init__(self, provider: Provider):
        super().__init__()
        self.provider = provider

    def run(self):
        try:
            asyncio.run(self._fetch())
        except Exception as e:
            self.finished.emit(False, str(e))

    async def _fetch(self):
        from metatv.providers.factory import get_provider
        plugin = get_provider(self.provider.type)
        if not plugin or not hasattr(plugin, "fetch_account_info"):
            self.finished.emit(False, "Source type does not support account info")
            return
        info = await plugin.fetch_account_info(self.provider)
        if info:
            self.finished.emit(True, info)
        else:
            self.finished.emit(False, "No response from source")


# ──────────────────────────────────────────────────────────────────────────────
# Background thread — tests ALL configured URLs in parallel
# ──────────────────────────────────────────────────────────────────────────────

class TestAllURLsThread(QThread):
    """Tests every URL simultaneously; emits a result per URL as they finish,
    then emits all_done with results sorted: successes (fastest first), failures last."""

    url_result = pyqtSignal(str, bool, int, str)  # url, success, ms, message
    all_done = pyqtSignal(list)                   # [(url, success, ms, message), ...]
    #: A DiagnosisReport, emitted alongside all_done. Carried separately because
    #: all_done's tuples are already formatted for display and have dropped the
    #: probe status and HTTP detail that the diagnosis is derived from — the
    #: information exists, it just stops here.
    diagnosis = pyqtSignal(object)

    def __init__(self, urls: List[str], username: str, password: str):
        super().__init__()
        self.urls = urls
        self.username = username
        self.password = password

    def run(self):
        try:
            asyncio.run(self._test_all())
        except Exception:
            # An empty result with no reason reads as "all of them failed".
            logger.exception("Testing all provider URLs failed")
            self.all_done.emit([])

    async def _test_all(self):
        def _emit(r: ProbeResult):
            # Streamed per-URL as each probe finishes (queued to the main thread).
            self.url_result.emit(r.url, r.success, r.latency_ms, _format_probe_message(r))

        results = await probe_all_urls(
            self.urls, self.username, self.password, on_result=_emit
        )
        self.all_done.emit(
            [(r.url, r.success, r.latency_ms, _format_probe_message(r)) for r in results]
        )
        # Diagnosed in core (no English there); phrased by the editor.
        self.diagnosis.emit(diagnose(results))


# ──────────────────────────────────────────────────────────────────────────────
# Icon picker
# ──────────────────────────────────────────────────────────────────────────────

class ProviderIconPicker(QWidget):
    """Icon display that reveals a colored-circle palette when clicked."""

    icon_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._icon = ""
        self._color_btns: List[tuple] = []
        self._setup()

    def _setup(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._btn = QPushButton(_icons.provider_icon)
        self._btn.setFixedSize(48, 48)
        _theme.style(self._btn, "ICON_PICK_MAIN_BTN")
        self._btn.setToolTip("Click to change icon")
        self._btn.clicked.connect(self._toggle_palette)
        layout.addWidget(self._btn)

        self._palette = QFrame()
        _theme.style(self._palette, "ICON_PICK_POPUP")
        self._palette.hide()
        pal_layout = QVBoxLayout(self._palette)
        pal_layout.setContentsMargins(8, 8, 8, 8)
        pal_layout.setSpacing(6)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(3)
        for icon in _icons.provider_icon_palette:
            b = QPushButton(icon)
            b.setFixedSize(30, 30)
            _theme.style(b, "ICON_PICK_BTN")
            b.clicked.connect(lambda checked, i=icon: self._pick(i))
            btn_row.addWidget(b)
            self._color_btns.append((icon, b))
        btn_row.addStretch()
        pal_layout.addLayout(btn_row)

        custom_row = QHBoxLayout()
        self._custom_label = QLabel("Custom:")
        _theme.style_fn(self._custom_label, lambda: f"font-size: {_theme.FONT_MD}; color: {_theme.COLOR_TEXT};")
        custom_row.addWidget(self._custom_label)
        self._custom_input = QLineEdit()
        self._custom_input.setClearButtonEnabled(True)
        self._custom_input.setPlaceholderText("emoji…")
        self._custom_input.setFixedWidth(80)
        self._custom_input.setMaxLength(8)
        _theme.style_fn(self._custom_input, lambda: f"font-size: {_theme.FONT_INPUT};")
        custom_row.addWidget(self._custom_input)
        apply_btn = QPushButton("Apply")
        apply_btn.setFixedWidth(54)
        apply_btn.clicked.connect(self._apply_custom)
        custom_row.addWidget(apply_btn)
        custom_row.addStretch()
        pal_layout.addLayout(custom_row)

        layout.addWidget(self._palette)

    def _toggle_palette(self):
        self._palette.setVisible(not self._palette.isVisible())

    def _pick(self, icon: str):
        self._icon = icon
        self._btn.setText(icon)
        self._palette.hide()
        self._update_selection(icon)
        self.icon_changed.emit(icon)

    def _apply_custom(self):
        text = self._custom_input.text().strip()
        if text:
            self._pick(text)

    def _update_selection(self, selected: str):
        for icon, btn in self._color_btns:
            _theme.style(
                btn,
                "ICON_PICK_BTN_SELECTED" if icon == selected else "ICON_PICK_BTN",
            )

    def get_icon(self) -> str:
        return self._icon

    def set_icon(self, icon: str):
        self._icon = icon
        self._btn.setText(icon if icon else _icons.provider_icon)
        self._update_selection(icon)

    def setEnabled(self, enabled: bool):
        super().setEnabled(enabled)
        self._btn.setEnabled(enabled)

    def refresh_theme(self) -> None:
        """Re-apply the active palette to this picker's own persistent chrome
        (main button, popup frame, "Custom:" label, and every palette-color
        swatch button) — all styled once at construction/``_update_selection``
        and never touched again except on the next colour pick. Called from
        ``ProviderEditorView.refresh_theme()``.
        """
        _theme.style(self._btn, "ICON_PICK_MAIN_BTN")
        _theme.style(self._palette, "ICON_PICK_POPUP")
        _theme.style_fn(self._custom_label, lambda: f"font-size: {_theme.FONT_MD}; color: {_theme.COLOR_TEXT};")
        _theme.style_fn(self._custom_input, lambda: f"font-size: {_theme.FONT_INPUT};")
        self._update_selection(self._icon)


class _CopyableLabel(QLabel):
    """A small label whose full text copies to the clipboard on click.

    Used for the auto-detected EPG URL: shown small/muted, copies the URL to the
    clipboard when clicked and flashes brief "Copied!" feedback. The displayed
    text may be elided; the untruncated value to copy is held in ``_full_text``.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._full_text = ""
        _theme.style_fn(self, lambda: f"font-size: {_theme.FONT_SM}; color: {_theme.COLOR_TEXT};")
        cursor_affordance.set_clickable(self)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)

    def set_url(self, url: str) -> None:
        self._full_text = url or ""
        self.setText(url or "")
        self.setToolTip("Click to copy" if url else "")

    def _copy(self) -> None:
        """Copy the full URL to the clipboard and flash brief feedback."""
        if not self._full_text:
            return
        QApplication.clipboard().setText(self._full_text)
        shown = self.text()
        self.setText(f"{_icons.notification_success_icon} Copied!")
        QTimer.singleShot(1200, lambda: self.setText(shown))

    def mousePressEvent(self, event):
        self._copy()
        super().mousePressEvent(event)


# ──────────────────────────────────────────────────────────────────────────────
# Main editor view (center panel)
# ──────────────────────────────────────────────────────────────────────────────

class ProviderEditorView(_ProviderEditorTabsMixin, QWidget):
    """Full-panel provider editor.

    Shows account info, credentials, URLs, and settings for one provider.
    Clicking a different source in the left column calls load_provider() to switch.

    Action-bar re-pointing (Wave 7 — moved off the left-column row, see
    ``sidebar/sources.py``'s ``ProviderItemWidget(show_actions=False)``):

    * Refresh        → reuses the pre-existing (previously unemitted)
      ``refresh_requested`` signal, already connected in ``main_window.py`` to
      ``self.refresh_provider`` — no new plumbing needed, just a new emitter.
    * Analyze / Enable-Disable / Refresh Guide → three NEW signals
      (``analyze_requested``, ``toggle_active_requested``,
      ``epg_refresh_requested``); ``SourcesManagerView`` connects each to its
      existing public ``providerAnalyzeClicked``/``providerToggleClicked``/
      ``providerEpgRefreshClicked`` signals, so ``main_window.py``'s handler
      wiring for those three is completely unchanged.
    * "Refresh Guide" reuses the pre-Wave-7 ``_epg_refresh_btn`` attribute name
      (relocated from the old EPG group into the action bar, restyled/retexted)
      so ``tests/test_provider_editor_epg_autodetect.py`` needed no changes.
    """

    done = pyqtSignal()                     # user clicked "Done" — exit editor mode
    provider_saved = pyqtSignal(str)        # provider_id saved
    provider_deleted = pyqtSignal(str)      # provider_id deleted (finished — kept for compatibility)
    provider_delete_requested = pyqtSignal(str)  # provider_id — user confirmed delete; MainWindow runs the purge off-thread
    refresh_requested = pyqtSignal(str)     # provider_id — action bar "Refresh" clicked
    account_info_updated = pyqtSignal(str)  # provider_id — account info changed (expiration, connections, etc.)
    analyze_requested = pyqtSignal(str)         # provider_id — action bar "Analyze" clicked
    toggle_active_requested = pyqtSignal(str)   # provider_id — action bar Enable/Disable clicked
    epg_refresh_requested = pyqtSignal(str)     # provider_id — action bar "Refresh Guide" clicked

    def __init__(self, db: Database, config=None, epg_manager=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.config = config
        self._epg_manager = epg_manager
        self._provider_id: Optional[str] = None
        self._provider_urls: List[ProviderURL] = []
        self._pending_url_removals: set = set()  # urls (never idx) pending Save-time removal
        self._account_thread: Optional[FetchAccountInfoThread] = None
        self._test_thread: Optional[TestAllURLsThread] = None
        self._test_results_pending: int = 0
        self._pending_account_info: Optional[Dict] = None
        self._epg_was_enabled: bool = True  # tracks loaded state for enabled→disabled detection
        self._epg_url_override: str = ""   # tracks loaded URL override for change detection in _save
        self._loaded_epg_url: str = ""     # auto-built epg_url at load time (for refresh button enablement)
        self._loading: bool = False        # True while load_provider populates fields; suppresses dirty-marking
        self._current_is_active: bool = True    # mirrors the name-row status dot + toggle action label
        self._current_is_expired: bool = False  # date-based subscription expiry, mirrors the left-column row dot
        self._setup_ui()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_summary_tab(), "Summary")
        self._tabs.addTab(self._build_connection_tab(), "Connection")
        self._tabs.addTab(self._build_settings_tab(), "Settings")
        root.addWidget(self._tabs, 1)

        self._build_footer_row(root)
        self._connect_dirty_signals()

        self._set_fields_enabled(False)
        self._restore_tab_state()
        self._tabs.currentChanged.connect(self._on_tab_changed)

    def _restore_tab_state(self) -> None:
        """Restore the last-selected tab from config, signals blocked (rule:
        block → set every widget → unblock, then connect handlers in a
        separate pass — ``_on_tab_changed`` is connected AFTER this call)."""
        idx = getattr(self.config, "provider_editor_selected_tab", 0) if self.config else 0
        idx = max(0, min(idx, self._tabs.count() - 1))
        self._tabs.blockSignals(True)
        self._tabs.setCurrentIndex(idx)
        self._tabs.blockSignals(False)

    def _on_tab_changed(self, index: int) -> None:
        if self.config is not None:
            self.config.provider_editor_selected_tab = index
            _cfgsave.save_soon(self)

    def _build_header_row(self, layout: QVBoxLayout) -> None:
        """Icon + provider name (with a small status dot beside it, consistent
        with the left-column rows' dots) + Enabled checkbox."""
        row = QHBoxLayout()

        # Icon picker
        icon_col = QVBoxLayout()
        icon_col.setSpacing(2)
        self._icon_field_lbl = QLabel("Icon")
        _theme.style(self._icon_field_lbl, "CHANNEL_NAME_DIM")
        icon_col.addWidget(self._icon_field_lbl)
        self._icon_picker = ProviderIconPicker()
        icon_col.addWidget(self._icon_picker)
        icon_col.addStretch()
        row.addLayout(icon_col)
        row.addSpacing(10)

        name_col = QVBoxLayout()
        name_col.setSpacing(2)
        self._name_field_lbl = QLabel("Source Name")
        _theme.style(self._name_field_lbl, "CHANNEL_NAME_DIM")
        name_col.addWidget(self._name_field_lbl)
        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        self._status_dot_lbl = QLabel("")
        self._status_dot_lbl.setFixedWidth(14)
        name_row.addWidget(self._status_dot_lbl)
        self._name_input = QLineEdit()
        self._name_input.setClearButtonEnabled(True)
        _theme.style_fn(self._name_input, lambda: f"font-size: {_theme.FONT_HEADING}; font-weight: 600;")
        self._name_input.setPlaceholderText("My Source")
        name_row.addWidget(self._name_input, 1)
        name_col.addLayout(name_row)
        row.addLayout(name_col, 1)

        row.addSpacing(16)

        self._enabled_check = QCheckBox("Enabled")
        self._enabled_check.setToolTip("Enable or disable this source")
        self._enabled_check.setChecked(True)
        row.addWidget(self._enabled_check)

        layout.addLayout(row)

    def _update_status_dot(self, is_active: bool, is_expired: bool) -> None:
        """Colour the small name-row status dot — identical 3-state logic to the
        left-column rows' dot (green=active, red=expired, gray=disabled), so a
        glance at either surface agrees. The verbose account_status string stays
        fully available in Account Info's "Status:" line."""
        if is_expired:
            self._status_dot_lbl.setText(_icons.status_dot_icon)
            _theme.style_fn(self._status_dot_lbl, lambda: f"color: {_theme.COLOR_ERR};")
            self._status_dot_lbl.setToolTip("Subscription expired")
        elif is_active:
            self._status_dot_lbl.setText(_icons.status_dot_icon)
            _theme.style_fn(self._status_dot_lbl, lambda: f"color: {_theme.COLOR_OK};")
            self._status_dot_lbl.setToolTip("Active")
        else:
            self._status_dot_lbl.setText(_icons.inactive_dot_icon)
            _theme.style_fn(self._status_dot_lbl, lambda: f"color: {_theme.COLOR_MUTED_2};")
            self._status_dot_lbl.setToolTip("Disabled")

    # ── Action bar (Summary tab) ─────────────────────────────────────────────

    def _build_action_bar(self, layout: QVBoxLayout) -> None:
        """Right-aligned text+icon action buttons, directly beneath the
        provider-name row: the four actions the left-column row used to own."""
        row = QHBoxLayout()
        row.addStretch()

        self._action_refresh_btn = QPushButton(f"{_icons.refresh_icon}  Refresh")
        self._action_refresh_btn.setToolTip("Refresh channels from this source")
        _theme.style(self._action_refresh_btn, "PANEL_BTN")
        self._action_refresh_btn.clicked.connect(self._on_action_refresh_clicked)
        row.addWidget(self._action_refresh_btn)

        self._action_analyze_btn = QPushButton(f"{_icons.analyze_icon}  Analyze")
        self._action_analyze_btn.setToolTip("Analyze source overlap and content")
        _theme.style(self._action_analyze_btn, "PANEL_BTN")
        self._action_analyze_btn.clicked.connect(self._on_action_analyze_clicked)
        row.addWidget(self._action_analyze_btn)

        # Reuses the pre-Wave-7 "_epg_refresh_btn" name (relocated here from the
        # EPG group; see the class docstring) — its enabled-state is still
        # computed by _update_epg_refresh_btn_state() in provider_editor_tabs.py.
        self._epg_refresh_btn = QPushButton(f"{_icons.calendar_icon}  Refresh Guide")
        self._epg_refresh_btn.setToolTip(
            "Immediately re-fetch this source's EPG guide, bypassing the throttle. "
            "Disabled when EPG is off or no URL is configured."
        )
        _theme.style(self._epg_refresh_btn, "PANEL_BTN")
        self._epg_refresh_btn.clicked.connect(self._on_action_epg_clicked)
        row.addWidget(self._epg_refresh_btn)

        self._action_toggle_btn = QPushButton("Disable")
        self._action_toggle_btn.setToolTip("Enable / Disable this source")
        _theme.style(self._action_toggle_btn, "PANEL_BTN")
        self._action_toggle_btn.clicked.connect(self._on_action_toggle_clicked)
        row.addWidget(self._action_toggle_btn)

        layout.addLayout(row)

    def _on_action_refresh_clicked(self) -> None:
        if self._provider_id:
            self.refresh_requested.emit(self._provider_id)

    def _on_action_analyze_clicked(self) -> None:
        if self._provider_id:
            self.analyze_requested.emit(self._provider_id)

    def _on_action_epg_clicked(self) -> None:
        if self._provider_id:
            self.epg_refresh_requested.emit(self._provider_id)

    def _on_action_toggle_clicked(self) -> None:
        if self._provider_id:
            self.toggle_active_requested.emit(self._provider_id)

    def _update_toggle_action_label(self, is_active: bool) -> None:
        self._action_toggle_btn.setText("Disable" if is_active else "Enable")

    def set_toggle_busy(self, busy: bool) -> None:
        """Spinner/disable on the action bar's Enable/Disable button while a
        toggle operation is in flight — reuses ``SourcesManagerView._busy_ids``,
        the same busy machinery the retired row's toggle button used, just
        rendered here instead. On completion, re-reads is_active/expiry fresh
        from the DB (one row) so the label/status dot reflect the outcome even
        on failure (where the DB value never actually changed) without a full
        ``load_provider()`` reload that would stomp unsaved edits elsewhere."""
        self._action_toggle_btn.setEnabled(not busy)
        if busy:
            self._action_toggle_btn.setText(f"{_icons.loading_icon}  Updating…")
            self._action_toggle_btn.setToolTip("Updating…")
            return
        self._action_toggle_btn.setToolTip("Enable / Disable this source")
        if self._provider_id:
            with self.db.session_scope(commit=False) as session:
                row = session.query(ProviderDB).filter_by(id=self._provider_id).first()
                if row is not None:
                    self._current_is_active = bool(row.is_active)
                    self._current_is_expired = bool(
                        row.account_exp_date and row.account_exp_date <= datetime.now()
                    )
        self._update_toggle_action_label(self._current_is_active)
        self._update_status_dot(self._current_is_active, self._current_is_expired)

    def set_epg_busy(self, busy: bool) -> None:
        """Spinner/disable on the action bar's "Refresh Guide" button while an
        EPG fetch is in flight (mirrors the retired row EPG pip's spinner)."""
        if busy:
            self._epg_refresh_btn.setEnabled(False)
            self._epg_refresh_btn.setText(f"{_icons.loading_icon}  Refreshing…")
            self._epg_refresh_btn.setToolTip("Refreshing EPG…")
        else:
            self._epg_refresh_btn.setText(f"{_icons.calendar_icon}  Refresh Guide")
            self._update_epg_refresh_btn_state()

    # ── Persistent footer ────────────────────────────────────────────────────

    def _build_footer_row(self, root: QVBoxLayout) -> None:
        """Delete / Test Connection / Discard / Save Changes — OUTSIDE the
        QTabWidget, always visible regardless of the selected tab. Delete sits
        far left with a visual divider separating it from the Test/Discard/Save
        group (destructive action must never read as adjacent to Save)."""
        self._footer = QWidget()
        _theme.style(self._footer, "PROVIDER_FOOTER")
        row = QHBoxLayout(self._footer)
        row.setContentsMargins(16, 10, 16, 10)

        self._delete_btn = QPushButton(f"{_icons.delete_icon}  Delete Source")
        _theme.style(self._delete_btn, "DELETE_BTN")
        self._delete_btn.clicked.connect(self._delete_provider)
        row.addWidget(self._delete_btn)

        row.addSpacing(12)
        self._footer_divider = QFrame()
        self._footer_divider.setFrameShape(QFrame.Shape.NoFrame)
        self._footer_divider.setFixedWidth(1)
        self._footer_divider.setMinimumHeight(20)
        _theme.style(self._footer_divider, "FOOTER_DIVIDER")
        row.addWidget(self._footer_divider)

        row.addStretch()

        self._test_btn = QPushButton("Test Connection")
        self._test_btn.setFixedWidth(140)
        self._test_btn.setToolTip("Click to re-test connection")
        self._test_btn.clicked.connect(self._test_connection)
        row.addWidget(self._test_btn)

        self._discard_btn = QPushButton("Discard")
        self._discard_btn.setFixedWidth(80)
        self._discard_btn.clicked.connect(self._discard)
        row.addWidget(self._discard_btn)

        self._save_btn = QPushButton("Save Changes")
        self._save_btn.setMinimumWidth(120)
        self._save_btn.setDefault(True)
        _theme.style(self._save_btn, "SAVE_BTN")
        self._save_btn.clicked.connect(self._save)
        row.addWidget(self._save_btn)

        # Why every address failed, and what to do about it. Hidden until a
        # test actually fails everywhere — a permanently-present empty panel
        # would be furniture.
        self._diagnosis_lbl = QLabel()
        self._diagnosis_lbl.setWordWrap(True)
        self._diagnosis_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        _theme.style(self._diagnosis_lbl, "NOTICE_WARN")
        self._diagnosis_lbl.hide()
        root.addWidget(self._diagnosis_lbl)

        root.addWidget(self._footer)

    def _connect_dirty_signals(self) -> None:
        """Wire all editable-field change signals to ``_mark_dirty``.

        Called once from ``_setup_ui`` (after the tabs — and therefore every
        field — are already constructed) so the wiring stays in one place.
        """
        self._name_input.textChanged.connect(self._mark_dirty)
        self._username_input.textChanged.connect(self._mark_dirty)
        self._password_input.textChanged.connect(self._mark_dirty)
        self._epg_url_override_input.textChanged.connect(self._mark_dirty)
        self._enabled_check.toggled.connect(self._mark_dirty)
        self._force_adult_check.toggled.connect(self._mark_dirty)
        self._epg_enabled_check.toggled.connect(self._mark_dirty)
        self._refresh_combo.currentIndexChanged.connect(self._mark_dirty)
        self._epg_interval_combo.currentIndexChanged.connect(self._mark_dirty)
        self._icon_picker.icon_changed.connect(self._mark_dirty)

    def _mark_dirty(self, *_args) -> None:
        """Restore the Save button to its active state when the user edits a field.

        Early-returns while ``_loading`` is True so programmatic field population
        during ``load_provider`` does not falsely trip the dirty state.
        """
        if self._loading:
            return
        self._save_btn.setText("Save Changes")
        self._save_btn.setEnabled(True)

    def refresh_theme(self) -> None:
        """Re-apply the active palette to this editor's own persistent chrome
        styled once at construction (header field labels, the action-bar
        buttons, the footer + its divider/Delete/Save buttons, and the
        Connection tab's username/password visibility toggles) and forward to
        the icon picker, which has its own ``refresh_theme()`` — same
        recursion pattern as ``MainWindow.refresh_theme()`` forwarding to
        ``details_pane``/``filter_panel``.

        Data-driven labels (account status/remaining/EPG-freshness colour,
        the name-row status dot) are recomputed fresh from current tokens on
        every ``load_provider()``/refresh, same rationale as the channel-list
        row delegate — left out of this sweep, same as ``_acct_cons_lbl``'s
        sibling ``_acct_status_lbl`` isn't touched here either.
        """
        _theme.style(self._icon_field_lbl, "CHANNEL_NAME_DIM")
        _theme.style(self._name_field_lbl, "CHANNEL_NAME_DIM")
        if hasattr(self._icon_picker, "refresh_theme"):
            self._icon_picker.refresh_theme()

        for btn in (
            self._action_refresh_btn, self._action_analyze_btn,
            self._epg_refresh_btn, self._action_toggle_btn,
        ):
            _theme.style(btn, "PANEL_BTN")

        _theme.style(self._footer, "PROVIDER_FOOTER")
        _theme.style(self._delete_btn, "DELETE_BTN")
        _theme.style(self._footer_divider, "FOOTER_DIVIDER")
        _theme.style(self._save_btn, "SAVE_BTN")

        _theme.style(self._acct_cons_lbl, "FIELD_LABEL")
        _theme.style(self._username_eye_btn, "EYE_BTN")
        _theme.style(self._password_eye_btn, "EYE_BTN")

    # ── Public API ────────────────────────────────────────────────────────────

    def load_provider(self, provider_id: str, force: bool = False):
        """Switch the editor to the given provider. Safe to call while editing.

        Args:
            provider_id: The provider to display.
            force: When True, reload even if ``provider_id`` matches the currently
                loaded provider.  Used by ``_discard`` to revert in-progress edits.
        """
        if provider_id == self._provider_id and not force:
            return  # already showing this one

        # Reset per-source transient button state before populating the new provider.
        # This prevents Test Connection result text and the "Saved" state from the
        # previous source bleeding through to the newly-loaded one.
        self._test_btn.setText("Test Connection")
        self._test_btn.setEnabled(True)
        self._save_btn.setText("Save Changes")
        self._save_btn.setEnabled(True)

        # Prompt if there are unsaved changes?  Keep simple for now.
        self._provider_id = provider_id
        self._pending_account_info = None

        session = self.db.get_session()
        self._loading = True
        try:
            repos = RepositoryFactory(session)
            db_prov = repos.providers.get_by_id(provider_id)
            if not db_prov:
                logger.error(f"ProviderEditorView: provider not found: {provider_id}")
                return
            provider = repos.providers.to_model(db_prov)
            # Most reliable first, which is what the group box has always
            # CLAIMED ("sorted by reliability") and never did — the list was
            # stored order, so a 0% address could sit above an 86% one.
            #
            # Sorted on load only, so a ⤒ try-first pick isn't fought by a
            # re-sort on repaint. try_first leads even this — a one-shot
            # override outranks the evidence. Untested addresses sort after
            # tested ones: unreached is not "most reliable", it's unknown.
            self._provider_urls = sorted(
                provider.urls,
                key=lambda pu: (
                    not pu.try_first,
                    (pu.success_count + pu.failure_count) == 0,
                    -pu.reliability_score,
                ),
            )
            self._pending_url_removals = set()

            # Populate fields
            self._name_input.setText(db_prov.name)
            self._icon_picker.set_icon(getattr(db_prov, "icon", "") or "")
            self._enabled_check.setChecked(bool(db_prov.is_active))
            self._username_input.setText(db_prov.username or "")
            self._password_input.setText(db_prov.password or "")

            schedule_map = {"manual": 0, "launch": 1, "daily": 2, "weekly": 3, "monthly": 4}
            self._refresh_combo.setCurrentIndex(schedule_map.get(db_prov.refresh_schedule or "manual", 0))

            self._force_adult_check.setChecked(bool(getattr(db_prov, "force_adult", False)))

            epg_enabled = bool(getattr(db_prov, "epg_enabled", True))
            self._epg_enabled_check.setChecked(epg_enabled)
            self._epg_was_enabled = epg_enabled

            # URL override
            epg_url_override = getattr(db_prov, "epg_url_override", None) or ""
            self._epg_url_override = epg_url_override  # capture loaded value for change detection in _save
            self._epg_url_override_input.setText(epg_url_override)
            self._epg_url_override_input.setPlaceholderText("(uses auto-detected URL)")
            # Resolve the auto-detected URL fresh from CURRENT credentials — never
            # read the stored epg_url column. That column was a write-once cache: a
            # re-subscription changes username/password but the cached column keeps
            # the OLD account's URL forever, so a green AUTODETECTED badge could show
            # a URL built from credentials that no longer exist.
            self._loaded_epg_url = (
                self._epg_manager.build_epg_url(db_prov) or "" if self._epg_manager else ""
            )

            # Refresh interval
            epg_interval = getattr(db_prov, "epg_refresh_interval", None) or "default"
            combo = self._epg_interval_combo
            idx = combo.findData(epg_interval)
            combo.setCurrentIndex(idx if idx >= 0 else 0)  # fallback to "Use default"

            # Update EPG controls enabled state + auto-detect display
            self._update_epg_controls_enabled(epg_enabled)
            self._update_epg_autodetected_display()
            self._update_epg_refresh_btn_state()

            # Account info from DB (cached)
            self._apply_account_info({
                "status": db_prov.account_status or "",
                "exp_date_dt": db_prov.account_exp_date,
                "created_at_dt": db_prov.account_created_at,
                "active_cons": db_prov.account_active_cons or 0,
                "max_connections": db_prov.max_connections or 1,
            }, from_cache=True)
            # Effective URL (override-aware) — never the stale cached epg_url column;
            # see the auto-detected-URL comment above for why.
            effective_epg_url = (
                self._epg_manager.effective_epg_url(db_prov) if self._epg_manager else ""
            )
            self._set_epg_status_label(
                effective_epg_url, db_prov.epg_data_end,
                epg_data_start=getattr(db_prov, "epg_data_start", None),
            )

            self._rebuild_url_list()
            self._set_fields_enabled(True)

            # Name-row status dot + action-bar toggle label — identical 3-state
            # logic to the left-column row's dot.
            self._current_is_active = bool(db_prov.is_active)
            self._current_is_expired = bool(
                db_prov.account_exp_date and db_prov.account_exp_date <= datetime.now()
            )
            self._update_status_dot(self._current_is_active, self._current_is_expired)
            self._update_toggle_action_label(self._current_is_active)

        finally:
            self._loading = False
            session.close()

    # ── Save / delete / discard / test connection ───────────────────────────

    def _save(self):
        if not self._provider_id:
            return

        session = self.db.get_session()
        try:
            db_prov = session.query(ProviderDB).filter_by(id=self._provider_id).first()
            if not db_prov:
                return

            db_prov.name = self._name_input.text().strip() or db_prov.name
            db_prov.icon = self._icon_picker.get_icon()
            db_prov.is_active = self._enabled_check.isChecked()
            db_prov.username = self._username_input.text().strip()
            db_prov.password = self._password_input.text().strip()
            db_prov.force_adult = self._force_adult_check.isChecked()

            epg_now_enabled = self._epg_enabled_check.isChecked()
            db_prov.epg_enabled = epg_now_enabled

            # EPG refresh interval
            db_prov.epg_refresh_interval = self._epg_interval_combo.currentData() or "default"

            # EPG URL override — if changed, null epg_last_fetched to force a refetch
            new_epg_override = self._epg_url_override_input.text().strip() or None
            old_epg_override = getattr(self, "_epg_url_override", None) or None
            db_prov.epg_url_override = new_epg_override
            if new_epg_override != old_epg_override:
                # URL changed: old data stays visible until next fetch; force refetch
                db_prov.epg_last_fetched = None
                logger.info(f"EPG URL override changed for {self._provider_id}; forcing refetch")

            schedule_map = {0: "manual", 1: "launch", 2: "daily", 3: "weekly", 4: "monthly"}
            db_prov.refresh_schedule = schedule_map.get(self._refresh_combo.currentIndex(), "manual")

            # URLs — surviving excludes ghost rows the user removed (keyed by url, never index).
            removed = self._pending_url_removals
            surviving = [pu for pu in self._provider_urls if pu.url not in removed]
            if surviving:
                db_prov.url = surviving[0].url  # primary = first surviving URL
            db_prov.urls = [provider_url_to_raw(pu, priority=i) for i, pu in enumerate(surviving)]

            # Account info (if freshly fetched)
            if self._pending_account_info:
                info = self._pending_account_info
                db_prov.account_status = info.get("status")
                db_prov.account_active_cons = info.get("active_cons", 0)
                db_prov.max_connections = info.get("max_connections", 1)
                db_prov.account_exp_date = self._parse_ts(info.get("exp_date"))
                db_prov.account_created_at = self._parse_ts(info.get("created_at"))

            # Purge EPG data on enabled→disabled transition so the UI reflects
            # the change immediately (no stale programmes in On Now / Watchlist).
            # Reuses the open session so the purge and the settings update commit
            # together atomically.
            if self._epg_was_enabled and not epg_now_enabled and self._epg_manager:
                self._epg_manager.purge_provider_epg(self._provider_id, session)

            db_prov.updated_at = datetime.now()
            session.commit()
            logger.info(f"Provider '{db_prov.name}' saved")
            # Reflect updated state so repeated saves behave correctly.
            self._epg_was_enabled = epg_now_enabled
            self._epg_url_override = new_epg_override or ""
            self._current_is_active = bool(db_prov.is_active)
            self._update_status_dot(self._current_is_active, self._current_is_expired)
            self._update_toggle_action_label(self._current_is_active)
            # Ghost rows are now actually deleted — drop them from memory too and rebuild.
            self._provider_urls = surviving
            self._pending_url_removals = set()
            self._rebuild_url_list()
            # Show transient "Saved" confirmation — persists until the next field edit,
            # at which point _mark_dirty() restores "Save Changes" and re-enables the button.
            self._save_btn.setText(f"{_icons.notification_success_icon} Saved")
            self._save_btn.setEnabled(False)
            self.provider_saved.emit(self._provider_id)

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to save provider: {e}")
            QMessageBox.critical(self, "Save Failed", str(e))
        finally:
            session.close()

    def _discard(self):
        """Reload from DB, discarding unsaved changes."""
        if self._provider_id:
            self.load_provider(self._provider_id, force=True)

    def _delete_provider(self):
        """Confirm the delete, then hand it to MainWindow to run OFF the UI thread.

        The purge (``prune_provider_content`` over hundreds of thousands of rows)
        must not run on the Qt main thread — doing so froze the app ("Not
        Responding") for minutes on a large DB.  We keep the confirmation modal
        here (it needs a parent widget), then emit ``provider_delete_requested`` so
        the MainWindow owner submits the purge to its shared executor and refreshes
        the dependent views on completion (the "provider mutations funnel through
        MainWindow" rule).  The finished side clears the editor.
        """
        if not self._provider_id:
            return
        session = self.db.get_session()
        try:
            db_prov = session.query(ProviderDB).filter_by(id=self._provider_id).first()
            name = db_prov.name if db_prov else "this source"
        finally:
            session.close()

        reply = QMessageBox.question(
            self, "Delete Source",
            f"Delete '{name}' and all its channels? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Hand off to the MainWindow owner — it runs the purge off-thread.
        self.provider_delete_requested.emit(self._provider_id)

    def _test_connection(self):
        """Test ALL configured URLs in parallel, then reorder by response time."""
        if not self._provider_id or not self._provider_urls:
            return

        username = self._username_input.text().strip()
        password = self._password_input.text().strip()
        urls = [pu.url for pu in self._provider_urls]

        self._test_btn.setEnabled(False)
        self._test_btn.setText(f"Testing 0/{len(urls)}…")
        self._acct_error_lbl.hide()
        self._test_results_pending = len(urls)

        # Show "Testing…" badge on every row
        from metatv.gui.url_row_widget import URLRowWidget
        for i in range(self._url_list.count()):
            w = self._url_list.itemWidget(self._url_list.item(i))
            if isinstance(w, URLRowWidget):
                w.show_testing()

        self._test_thread = TestAllURLsThread(urls, username, password)
        self._test_thread.url_result.connect(self._on_single_url_result)
        self._test_thread.all_done.connect(self._on_all_urls_done)
        self._test_thread.diagnosis.connect(self._on_diagnosis)
        self._test_thread.start()

    def _on_single_url_result(self, url: str, success: bool, ms: int, message: str):
        """Update the matching URL row badge as each result arrives."""
        from metatv.gui.url_row_widget import URLRowWidget
        self._test_results_pending = max(0, self._test_results_pending - 1)
        total = len(self._provider_urls)
        done = total - self._test_results_pending
        self._test_btn.setText(f"Testing {done}/{total}…")

        for i in range(self._url_list.count()):
            w = self._url_list.itemWidget(self._url_list.item(i))
            if isinstance(w, URLRowWidget) and w.provider_url.url == url:
                w.show_test_result(success, message)
                break

    def _on_diagnosis(self, report) -> None:
        """Show why every address failed — or hide the panel when one worked.

        Only speaks up on a TOTAL failure. A partial failure is normal and is
        the entire reason a source carries several addresses; announcing it
        would train the user to ignore this panel.
        """
        phrasing = _DIAGNOSIS_TEXT.get(report.diagnosis)
        if phrasing is None:
            self._diagnosis_lbl.hide()
            return

        headline, advice = phrasing
        evidence = ""
        if report.refusal_codes:
            evidence = f" (HTTP {', '.join(report.refusal_codes)})"
        self._diagnosis_lbl.setText(
            f"{headline}{evidence}\n\n{advice}"
        )
        self._diagnosis_lbl.show()

    def _on_all_urls_done(self, sorted_results: list):
        """Reorder URL list: successes fastest-first, failures last."""
        self._test_btn.setEnabled(True)
        working = [r for r in sorted_results if r[1]]
        failed  = [r for r in sorted_results if not r[1]]

        ok_icon = self.config.notification_success_icon if self.config else "✓"
        err_icon = self.config.notification_error_icon if self.config else "✗"
        self._test_btn.setText(
            f"{ok_icon} {len(working)}/{len(sorted_results)} working"
            if working else f"{err_icon} All {len(sorted_results)} failed"
        )

        if not sorted_results:
            return

        # Build url→ProviderURL map so we keep stats
        url_map = {pu.url.rstrip("/"): pu for pu in self._provider_urls}

        new_order: List[ProviderURL] = []
        for url, success, _ms, _ in sorted_results:
            pu = url_map.get(url.rstrip("/"))
            if pu:
                # Update cumulative stats
                if success:
                    pu.success_count += 1
                else:
                    pu.failure_count += 1
                new_order.append(pu)

        # Assign fresh priorities
        for i, pu in enumerate(new_order):
            pu.priority = i

        self._provider_urls = new_order
        self._rebuild_url_list()

        # Auto-fetch account info if at least one URL worked
        if working:
            self._fetch_account_info()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _set_fields_enabled(self, enabled: bool):
        for w in [self._icon_picker, self._name_input, self._enabled_check,
                  self._username_input, self._password_input, self._refresh_combo,
                  self._force_adult_check, self._url_list, self._new_url_input,
                  self._refresh_acct_btn, self._test_btn,
                  self._action_refresh_btn, self._action_analyze_btn,
                  self._action_toggle_btn]:
            w.setEnabled(enabled)
        # The action bar's Refresh Guide button has its own gating (EPG
        # on + has URL) — _update_epg_refresh_btn_state, called from
        # load_provider, is the source of truth once a provider is loaded.
        if not enabled:
            self._epg_refresh_btn.setEnabled(False)

    @staticmethod
    def _parse_ts(ts) -> Optional[datetime]:
        if not ts:
            return None
        try:
            return datetime.fromtimestamp(int(ts))
        except (TypeError, ValueError, OSError, OverflowError):
            return None  # silent: junk timestamp from the provider — show nothing
