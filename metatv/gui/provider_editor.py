"""Provider editor — center-panel view for managing IPTV sources.

Replaces the channel list when the user enters provider-edit mode.
Clicking a different source in the sidebar switches the editor to that provider
without leaving the view.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Optional, List, Dict, Any

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QFont, QColor, QPalette
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QGroupBox,
    QListWidget, QListWidgetItem, QComboBox,
    QScrollArea, QFrame, QSizePolicy, QMessageBox,
    QCheckBox, QProgressBar, QTextEdit, QSpacerItem, QSpinBox,
)
from loguru import logger

from metatv.core.database import Database, ProviderDB
from metatv.core.models import Provider, ProviderURL
from metatv.core.repositories import RepositoryFactory


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
            self.finished.emit(False, "Provider type does not support account info")
            return
        info = await plugin.fetch_account_info(self.provider)
        if info:
            self.finished.emit(True, info)
        else:
            self.finished.emit(False, "No response from provider")


# ──────────────────────────────────────────────────────────────────────────────
# Background thread — tests ALL configured URLs in parallel
# ──────────────────────────────────────────────────────────────────────────────

class TestAllURLsThread(QThread):
    """Tests every URL simultaneously; emits a result per URL as they finish,
    then emits all_done with results sorted: successes (fastest first), failures last."""

    url_result = pyqtSignal(str, bool, int, str)  # url, success, ms, message
    all_done = pyqtSignal(list)                   # [(url, success, ms, message), ...]

    def __init__(self, urls: List[str], username: str, password: str):
        super().__init__()
        self.urls = urls
        self.username = username
        self.password = password

    def run(self):
        try:
            asyncio.run(self._test_all())
        except Exception as e:
            self.all_done.emit([])

    async def _test_all(self):
        import aiohttp
        from time import time

        results: List[tuple] = []

        from metatv.providers.xtream import _DEFAULT_HEADERS

        async def test_one(url: str):
            start = time()
            clean = url.rstrip("/")
            auth_url = f"{clean}/player_api.php?username={self.username}&password={self.password}"
            try:
                async with aiohttp.ClientSession(headers=_DEFAULT_HEADERS) as session:
                    async with session.get(auth_url, timeout=aiohttp.ClientTimeout(total=12)) as resp:
                        ms = int((time() - start) * 1000)
                        if resp.status == 200:
                            data = await resp.json(content_type=None)
                            user_info = data.get("user_info", {}) if isinstance(data, dict) else {}
                            auth = user_info.get("auth", 0)
                            status = user_info.get("status", "")
                            if auth and status.lower() == "active":
                                msg = f"Active  {ms} ms"
                                self.url_result.emit(url, True, ms, msg)
                                results.append((url, True, ms, msg))
                            elif auth:
                                msg = f"Account {status}"
                                self.url_result.emit(url, False, ms, msg)
                                results.append((url, False, ms, msg))
                            else:
                                msg = "Auth failed"
                                self.url_result.emit(url, False, ms, msg)
                                results.append((url, False, ms, msg))
                        else:
                            msg = f"HTTP {resp.status}"
                            self.url_result.emit(url, False, ms, msg)
                            results.append((url, False, ms, msg))
            except asyncio.TimeoutError:
                ms = int((time() - start) * 1000)
                self.url_result.emit(url, False, ms, "Timeout")
                results.append((url, False, ms, "Timeout"))
            except Exception as e:
                ms = int((time() - start) * 1000)
                msg = str(e)[:80]
                self.url_result.emit(url, False, ms, msg)
                results.append((url, False, ms, msg))

        await asyncio.gather(*[test_one(u) for u in self.urls])

        # Sort: working → fastest first; failed → least failures first
        sorted_results = sorted(results, key=lambda r: (0 if r[1] else 1, r[2]))
        self.all_done.emit(sorted_results)


# ──────────────────────────────────────────────────────────────────────────────
# URL row widget inside the URL list
# ──────────────────────────────────────────────────────────────────────────────

class URLRowWidget(QWidget):
    """Single URL row: move up/down, live test result badge, stats, remove."""

    moveUp = pyqtSignal()
    moveDown = pyqtSignal()
    removed = pyqtSignal()

    def __init__(self, provider_url: ProviderURL, index: int, total: int, parent=None):
        super().__init__(parent)
        self.provider_url = provider_url
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # Order controls
        order_col = QVBoxLayout()
        order_col.setSpacing(1)
        self._up_btn = QPushButton("▲")
        self._up_btn.setFixedSize(22, 18)
        self._up_btn.setEnabled(index > 0)
        self._up_btn.clicked.connect(self.moveUp)
        self._down_btn = QPushButton("▼")
        self._down_btn.setFixedSize(22, 18)
        self._down_btn.setEnabled(index < total - 1)
        self._down_btn.clicked.connect(self.moveDown)
        order_col.addWidget(self._up_btn)
        order_col.addWidget(self._down_btn)
        layout.addLayout(order_col)

        # Priority badge
        badge = QLabel(f"#{index + 1}")
        badge.setFixedWidth(24)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet("color: #888; font-size: 10px;")
        layout.addWidget(badge)

        # URL + stats column
        info_col = QVBoxLayout()
        info_col.setSpacing(2)

        url_label = QLabel(provider_url.url)
        url_label.setStyleSheet("font-weight: 600;")
        url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        info_col.addWidget(url_label)

        self._stats_label = QLabel(self._build_stats(provider_url))
        self._stats_label.setStyleSheet("color: #888; font-size: 10px;")
        info_col.addWidget(self._stats_label)
        layout.addLayout(info_col, 1)

        # Live test result badge (hidden until a test runs)
        self._result_badge = QLabel("")
        self._result_badge.setFixedWidth(110)
        self._result_badge.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._result_badge.setStyleSheet("font-size: 10px; font-weight: 600;")
        self._result_badge.hide()
        layout.addWidget(self._result_badge)

        # Remove button
        rm_btn = QPushButton("✕")
        rm_btn.setFixedSize(24, 24)
        rm_btn.setToolTip("Remove this URL")
        rm_btn.setStyleSheet("""
            QPushButton { color: #e05050; border: 1px solid #555; border-radius: 3px; }
            QPushButton:hover { background: rgba(224,80,80,0.2); }
        """)
        rm_btn.clicked.connect(self.removed)
        layout.addWidget(rm_btn)

    def show_testing(self):
        """Show a 'Testing…' spinner while waiting for result."""
        self._result_badge.setText("⟳ Testing…")
        self._result_badge.setStyleSheet("font-size: 10px; color: #888;")
        self._result_badge.show()

    def show_test_result(self, success: bool, message: str):
        """Update badge with pass/fail result."""
        if success:
            self._result_badge.setText(f"✓  {message}")
            self._result_badge.setStyleSheet("font-size: 10px; font-weight: 600; color: #4CAF50;")
        else:
            self._result_badge.setText(f"✗  {message}")
            self._result_badge.setStyleSheet("font-size: 10px; font-weight: 600; color: #e05050;")
        self._result_badge.show()

    def clear_test_result(self):
        self._result_badge.hide()
        self._result_badge.setText("")

    @staticmethod
    def _build_stats(pu: ProviderURL) -> str:
        total = pu.success_count + pu.failure_count
        if total == 0:
            return "Untested"
        rel = f"{pu.reliability_score:.0f}% reliability"
        parts = [rel, f"✓{pu.success_count}", f"✗{pu.failure_count}"]
        if pu.last_success:
            parts.append(f"last ok {pu.last_success.strftime('%m/%d')}")
        return "  ·  ".join(parts)


# ──────────────────────────────────────────────────────────────────────────────
# Icon palette
# ──────────────────────────────────────────────────────────────────────────────

ICON_PALETTE = ['🔴', '🟠', '🟡', '🟢', '🔵', '🟣', '🟤', '⚫', '⚪', '🔶', '🔷', '🔸', '🔹']


def pick_next_icon(used_icons: List[str]) -> str:
    """Return the first palette icon not already in use; cycle if palette exhausted."""
    for icon in ICON_PALETTE:
        if icon not in used_icons:
            return icon
    return ICON_PALETTE[len(used_icons) % len(ICON_PALETTE)]


class ProviderIconPicker(QWidget):
    """Icon display that reveals a colored-circle palette when clicked."""

    icon_changed = pyqtSignal(str)

    _BTN_STYLE = (
        "QPushButton { font-size: 17px; border: 2px solid transparent;"
        " border-radius: 5px; padding: 0; }"
        " QPushButton:hover { border: 2px solid #4488ff;"
        " background: rgba(68,136,255,0.15); }"
    )
    _BTN_SELECTED_STYLE = (
        "QPushButton { font-size: 17px; border: 2px solid #4488ff;"
        " border-radius: 5px; padding: 0;"
        " background: rgba(68,136,255,0.2); }"
        " QPushButton:hover { border: 2px solid #4488ff;"
        " background: rgba(68,136,255,0.25); }"
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self._icon = ""
        self._color_btns: List[tuple] = []
        self._setup()

    def _setup(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._btn = QPushButton("📡")
        self._btn.setFixedSize(48, 48)
        self._btn.setStyleSheet(
            "QPushButton { font-size: 24px; border: 1px solid rgba(255,255,255,0.15);"
            " border-radius: 6px; }"
            " QPushButton:hover { border: 1px solid #4488ff;"
            " background: rgba(68,136,255,0.1); }"
        )
        self._btn.setToolTip("Click to change icon")
        self._btn.clicked.connect(self._toggle_palette)
        layout.addWidget(self._btn)

        self._palette = QFrame()
        self._palette.setStyleSheet(
            "QFrame { background: rgba(40,40,50,0.97);"
            " border: 1px solid rgba(255,255,255,0.18); border-radius: 8px; }"
        )
        self._palette.hide()
        pal_layout = QVBoxLayout(self._palette)
        pal_layout.setContentsMargins(8, 8, 8, 8)
        pal_layout.setSpacing(6)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(3)
        for icon in ICON_PALETTE:
            b = QPushButton(icon)
            b.setFixedSize(30, 30)
            b.setStyleSheet(self._BTN_STYLE)
            b.clicked.connect(lambda checked, i=icon: self._pick(i))
            btn_row.addWidget(b)
            self._color_btns.append((icon, b))
        btn_row.addStretch()
        pal_layout.addLayout(btn_row)

        custom_row = QHBoxLayout()
        lbl = QLabel("Custom:")
        lbl.setStyleSheet("font-size: 11px; color: #888;")
        custom_row.addWidget(lbl)
        self._custom_input = QLineEdit()
        self._custom_input.setPlaceholderText("emoji…")
        self._custom_input.setFixedWidth(80)
        self._custom_input.setMaxLength(8)
        self._custom_input.setStyleSheet("font-size: 16px;")
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
            btn.setStyleSheet(
                self._BTN_SELECTED_STYLE if icon == selected else self._BTN_STYLE
            )

    def get_icon(self) -> str:
        return self._icon

    def set_icon(self, icon: str):
        self._icon = icon
        self._btn.setText(icon if icon else "📡")
        self._update_selection(icon)

    def setEnabled(self, enabled: bool):
        super().setEnabled(enabled)
        self._btn.setEnabled(enabled)


# ──────────────────────────────────────────────────────────────────────────────
# Subscription time helper
# ──────────────────────────────────────────────────────────────────────────────

def subscription_color(exp_date: Optional[datetime], created_at: Optional[datetime]) -> str:
    """Return a CSS hex color for the subscription time remaining."""
    if exp_date is None:
        return ""
    now = datetime.now()
    if exp_date <= now:
        return "#888888"  # expired — gray
    days_remaining = (exp_date - now).days
    if created_at and created_at < exp_date:
        total_days = (exp_date - created_at).days
        pct = days_remaining / total_days if total_days > 0 else 1.0
    else:
        pct = min(1.0, days_remaining / 30.0)  # fallback: 30-day window

    if pct > 0.15 and days_remaining > 7:
        return "#4CAF50"   # green — plenty of time
    elif pct > 0.05 or days_remaining > 2:
        return "#FFC107"   # amber — getting close
    else:
        return "#F44336"   # red — expiring very soon


# ──────────────────────────────────────────────────────────────────────────────
# Main editor view (center panel)
# ──────────────────────────────────────────────────────────────────────────────

class ProviderEditorView(QWidget):
    """Full-panel provider editor.

    Shows account info, credentials, URLs, and settings for one provider.
    Clicking a different source in the sidebar calls load_provider() to switch.
    """

    done = pyqtSignal()                     # user clicked "Done" — exit editor mode
    provider_saved = pyqtSignal(str)        # provider_id saved
    provider_deleted = pyqtSignal(str)      # provider_id deleted
    refresh_requested = pyqtSignal(str)     # provider_id — trigger channel refresh

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self._provider_id: Optional[str] = None
        self._provider_urls: List[ProviderURL] = []
        self._account_thread: Optional[FetchAccountInfoThread] = None
        self._test_thread: Optional[TestAllURLsThread] = None
        self._test_results_pending: int = 0
        self._pending_account_info: Optional[Dict] = None
        self._setup_ui()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Top bar ──────────────────────────────────────────────────────────
        top_bar = QWidget()
        top_bar.setStyleSheet("background: rgba(255,255,255,0.04); border-bottom: 1px solid rgba(255,255,255,0.08);")
        top_bar.setFixedHeight(46)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(12, 0, 12, 0)

        done_btn = QPushButton("← Done Editing Sources")
        done_btn.setStyleSheet("""
            QPushButton { border: none; color: #4488ff; font-size: 13px; padding: 4px 8px; }
            QPushButton:hover { color: #88aaff; }
        """)
        done_btn.clicked.connect(self.done)
        top_layout.addWidget(done_btn)
        top_layout.addStretch()

        self._status_indicator = QLabel("")
        self._status_indicator.setStyleSheet("font-size: 12px; font-weight: 600;")
        top_layout.addWidget(self._status_indicator)

        root.addWidget(top_bar)

        # ── Scroll area ──────────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(24, 20, 24, 20)
        self._content_layout.setSpacing(16)

        self._build_header_row()
        self._build_account_info_group()
        self._build_credentials_group()
        self._build_urls_group()
        self._build_settings_group()
        self._build_epg_group()
        self._content_layout.addStretch(1)
        self._build_footer_row()

        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        self._set_fields_enabled(False)

    def _build_header_row(self):
        row = QHBoxLayout()

        # Icon picker
        icon_col = QVBoxLayout()
        icon_col.setSpacing(2)
        lbl_icon = QLabel("Icon")
        lbl_icon.setStyleSheet("color: #888; font-size: 11px;")
        icon_col.addWidget(lbl_icon)
        self._icon_picker = ProviderIconPicker()
        icon_col.addWidget(self._icon_picker)
        icon_col.addStretch()
        row.addLayout(icon_col)
        row.addSpacing(10)

        name_col = QVBoxLayout()
        name_col.setSpacing(2)
        lbl = QLabel("Provider Name")
        lbl.setStyleSheet("color: #888; font-size: 11px;")
        name_col.addWidget(lbl)
        self._name_input = QLineEdit()
        self._name_input.setStyleSheet("font-size: 15px; font-weight: 600;")
        self._name_input.setPlaceholderText("My Provider")
        name_col.addWidget(self._name_input)
        row.addLayout(name_col, 1)

        row.addSpacing(16)

        self._enabled_check = QCheckBox("Enabled")
        self._enabled_check.setToolTip("Enable or disable this provider")
        self._enabled_check.setChecked(True)
        row.addWidget(self._enabled_check)

        self._content_layout.addLayout(row)

    def _build_account_info_group(self):
        group = QGroupBox("Account Info")
        layout = QVBoxLayout(group)
        layout.setSpacing(8)

        # Status row
        status_row = QHBoxLayout()
        self._acct_status_lbl = QLabel("—")
        self._acct_status_lbl.setStyleSheet("font-weight: 600;")
        status_row.addWidget(QLabel("Status:"))
        status_row.addWidget(self._acct_status_lbl)
        status_row.addSpacing(24)
        status_row.addWidget(QLabel("Connections:"))
        self._acct_cons_lbl = QLabel("—")
        self._acct_cons_lbl.setStyleSheet("font-weight: 600;")
        status_row.addWidget(self._acct_cons_lbl)
        status_row.addStretch()
        layout.addLayout(status_row)

        # Dates row
        dates_row = QHBoxLayout()
        dates_row.addWidget(QLabel("Created:"))
        self._acct_created_lbl = QLabel("—")
        dates_row.addWidget(self._acct_created_lbl)
        dates_row.addSpacing(24)
        dates_row.addWidget(QLabel("Expires:"))
        self._acct_exp_lbl = QLabel("—")
        dates_row.addWidget(self._acct_exp_lbl)
        dates_row.addStretch()
        layout.addLayout(dates_row)

        # Remaining bar
        bar_row = QHBoxLayout()
        bar_row.addWidget(QLabel("Remaining:"))
        self._acct_remaining_lbl = QLabel("—")
        bar_row.addWidget(self._acct_remaining_lbl)
        self._acct_progress = QProgressBar()
        self._acct_progress.setTextVisible(False)
        self._acct_progress.setFixedHeight(6)
        self._acct_progress.setRange(0, 100)
        self._acct_progress.setValue(0)
        self._acct_progress.hide()
        bar_row.addWidget(self._acct_progress, 1)
        layout.addLayout(bar_row)

        # Refresh button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._refresh_acct_btn = QPushButton("↻  Refresh Account Info")
        self._refresh_acct_btn.setFixedWidth(180)
        self._refresh_acct_btn.clicked.connect(self._fetch_account_info)
        btn_row.addWidget(self._refresh_acct_btn)
        layout.addLayout(btn_row)

        self._acct_error_lbl = QLabel("")
        self._acct_error_lbl.setStyleSheet("color: #e05050; font-size: 11px;")
        self._acct_error_lbl.hide()
        layout.addWidget(self._acct_error_lbl)

        self._content_layout.addWidget(group)

    def _build_credentials_group(self):
        group = QGroupBox("Credentials")
        form = QFormLayout(group)
        form.setSpacing(8)

        self._username_input = QLineEdit()
        self._username_input.setPlaceholderText("username")
        form.addRow("Username:", self._username_input)

        pw_row = QHBoxLayout()
        self._password_input = QLineEdit()
        self._password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._password_input.setPlaceholderText("password")
        pw_row.addWidget(self._password_input, 1)
        show_btn = QPushButton("Show")
        show_btn.setFixedWidth(52)
        show_btn.setCheckable(True)
        show_btn.toggled.connect(
            lambda checked: self._password_input.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
            )
        )
        pw_row.addWidget(show_btn)
        form.addRow("Password:", pw_row)

        self._content_layout.addWidget(group)

    def _build_urls_group(self):
        group = QGroupBox("DNS / URLs  (sorted by reliability — drag or use arrows to reorder)")
        layout = QVBoxLayout(group)
        layout.setSpacing(6)

        self._url_list = QListWidget()
        self._url_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self._url_list.setSpacing(2)
        layout.addWidget(self._url_list)

        add_row = QHBoxLayout()
        self._new_url_input = QLineEdit()
        self._new_url_input.setPlaceholderText("http://newdomain.com:8080")
        self._new_url_input.returnPressed.connect(self._add_url)
        add_row.addWidget(self._new_url_input, 1)
        add_btn = QPushButton("Add URL")
        add_btn.setFixedWidth(80)
        add_btn.clicked.connect(self._add_url)
        add_row.addWidget(add_btn)
        layout.addLayout(add_row)

        self._content_layout.addWidget(group)

    def _build_settings_group(self):
        group = QGroupBox("Settings")
        form = QFormLayout(group)
        form.setSpacing(8)

        self._refresh_combo = QComboBox()
        self._refresh_combo.addItems(["Manual", "On App Launch", "Daily", "Weekly", "Every 30 Days"])
        form.addRow("Auto-refresh:", self._refresh_combo)

        self._force_adult_check = QCheckBox("Mark all channels from this source as adult content")
        self._force_adult_check.setToolTip(
            "Enable when this provider doesn't tag channels with adult flags "
            "but you want the adult content filter to apply to it."
        )
        form.addRow("Adult content:", self._force_adult_check)

        self._content_layout.addWidget(group)

    def _build_epg_group(self):
        group = QGroupBox("EPG Feed")
        layout = QVBoxLayout(group)
        layout.setSpacing(6)

        hint = QLabel(
            "XMLTV EPG feed URL for this provider. "
            "Xtream sources typically provide one at /xmltv.php."
        )
        hint.setStyleSheet("color: #888; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        url_row = QHBoxLayout()
        self._epg_url_input = QLineEdit()
        self._epg_url_input.setPlaceholderText("http://provider.example.com:8080/xmltv.php?username=…&password=…")
        url_row.addWidget(self._epg_url_input, 1)

        auto_btn = QPushButton("Auto-detect")
        auto_btn.setFixedWidth(100)
        auto_btn.setToolTip("Build XMLTV URL from configured credentials and primary server URL")
        auto_btn.clicked.connect(self._auto_detect_epg)
        url_row.addWidget(auto_btn)
        layout.addLayout(url_row)

        refresh_row = QHBoxLayout()
        refresh_lbl = QLabel("Refresh when data expires within")
        refresh_lbl.setStyleSheet("color: #aaa; font-size: 11px;")
        refresh_row.addWidget(refresh_lbl)
        self._epg_refresh_hours = QSpinBox()
        self._epg_refresh_hours.setRange(6, 168)
        self._epg_refresh_hours.setSingleStep(12)
        self._epg_refresh_hours.setSuffix("h")
        self._epg_refresh_hours.setValue(48)
        self._epg_refresh_hours.setFixedWidth(72)
        self._epg_refresh_hours.setToolTip(
            "Auto-refresh EPG data this many hours before the current data expires.\n"
            "Default 48h — with a 6-day feed, this means one refresh per week."
        )
        refresh_row.addWidget(self._epg_refresh_hours)
        refresh_row.addStretch()
        layout.addLayout(refresh_row)

        self._content_layout.addWidget(group)

    def _build_footer_row(self):
        row = QHBoxLayout()

        delete_btn = QPushButton("🗑  Delete Provider")
        delete_btn.setStyleSheet("""
            QPushButton { color: #e05050; border: 1px solid #e05050; border-radius: 4px; padding: 6px 14px; }
            QPushButton:hover { background: rgba(224,80,80,0.15); }
        """)
        delete_btn.clicked.connect(self._delete_provider)
        row.addWidget(delete_btn)
        row.addStretch()

        self._test_btn = QPushButton("Test Connection")
        self._test_btn.setFixedWidth(140)
        self._test_btn.clicked.connect(self._test_connection)
        row.addWidget(self._test_btn)

        discard_btn = QPushButton("Discard")
        discard_btn.setFixedWidth(80)
        discard_btn.clicked.connect(self._discard)
        row.addWidget(discard_btn)

        save_btn = QPushButton("Save Changes")
        save_btn.setMinimumWidth(120)
        save_btn.setDefault(True)
        save_btn.setStyleSheet("""
            QPushButton { background: #2255cc; color: white; border-radius: 4px; padding: 6px 18px; font-weight: 600; }
            QPushButton:hover { background: #3366dd; }
            QPushButton:disabled { background: #333; color: #666; }
        """)
        save_btn.clicked.connect(self._save)
        row.addWidget(save_btn)

        self._content_layout.addLayout(row)

    # ── Public API ────────────────────────────────────────────────────────────

    def load_provider(self, provider_id: str):
        """Switch the editor to the given provider. Safe to call while editing."""
        if provider_id == self._provider_id:
            return  # already showing this one

        # Prompt if there are unsaved changes?  Keep simple for now.
        self._provider_id = provider_id
        self._pending_account_info = None

        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            db_prov = repos.providers.get_by_id(provider_id)
            if not db_prov:
                logger.error(f"ProviderEditorView: provider not found: {provider_id}")
                return
            provider = repos.providers.to_model(db_prov)
            self._provider_urls = list(provider.urls)

            # Populate fields
            self._name_input.setText(db_prov.name)
            self._icon_picker.set_icon(getattr(db_prov, "icon", "") or "")
            self._enabled_check.setChecked(bool(db_prov.is_active))
            self._username_input.setText(db_prov.username or "")
            self._password_input.setText(db_prov.password or "")

            schedule_map = {"manual": 0, "launch": 1, "daily": 2, "weekly": 3, "monthly": 4}
            self._refresh_combo.setCurrentIndex(schedule_map.get(db_prov.refresh_schedule or "manual", 0))

            self._epg_url_input.setText(getattr(db_prov, "epg_url", "") or "")
            self._epg_refresh_hours.setValue(getattr(db_prov, "epg_refresh_hours_before", 48) or 48)
            self._force_adult_check.setChecked(bool(getattr(db_prov, "force_adult", False)))

            # Account info from DB (cached)
            self._apply_account_info({
                "status": db_prov.account_status or "",
                "exp_date_dt": db_prov.account_exp_date,
                "created_at_dt": db_prov.account_created_at,
                "active_cons": db_prov.account_active_cons or 0,
                "max_connections": db_prov.max_connections or 1,
            }, from_cache=True)

            self._rebuild_url_list()
            self._set_fields_enabled(True)

            # Update top-bar status
            status = db_prov.account_status or ""
            if status.lower() == "active":
                self._status_indicator.setText("● Active")
                self._status_indicator.setStyleSheet("color: #4CAF50; font-size: 12px; font-weight: 600;")
            elif status.lower() == "expired":
                self._status_indicator.setText("⚠ Expired")
                self._status_indicator.setStyleSheet("color: #F44336; font-size: 12px; font-weight: 600;")
            elif status:
                self._status_indicator.setText(f"● {status}")
                self._status_indicator.setStyleSheet("color: #FFC107; font-size: 12px; font-weight: 600;")
            else:
                self._status_indicator.setText("")

        finally:
            session.close()

    # ── Account info ──────────────────────────────────────────────────────────

    def _fetch_account_info(self):
        if not self._provider_id:
            return
        self._refresh_acct_btn.setEnabled(False)
        self._refresh_acct_btn.setText("Fetching…")
        self._acct_error_lbl.hide()

        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            db_prov = repos.providers.get_by_id(self._provider_id)
            if not db_prov:
                return
            provider = repos.providers.to_model(db_prov)
        finally:
            session.close()

        self._account_thread = FetchAccountInfoThread(provider)
        self._account_thread.finished.connect(self._on_account_info_fetched)
        self._account_thread.start()

    def _on_account_info_fetched(self, success: bool, result):
        self._refresh_acct_btn.setEnabled(True)
        self._refresh_acct_btn.setText("↻  Refresh Account Info")

        if not success:
            self._acct_error_lbl.setText(f"Failed: {result}")
            self._acct_error_lbl.show()
            return

        info = result
        self._pending_account_info = info  # stored on save

        # Parse timestamps
        exp_dt = self._parse_ts(info.get("exp_date"))
        created_dt = self._parse_ts(info.get("created_at"))

        self._apply_account_info({
            "status": info.get("status", ""),
            "exp_date_dt": exp_dt,
            "created_at_dt": created_dt,
            "active_cons": info.get("active_cons", 0),
            "max_connections": info.get("max_connections", 1),
        })

        # Auto-populate EPG URL if empty and server_info provides a base URL
        if not self._epg_url_input.text().strip():
            self._try_populate_epg_from_info(info)

        # Update top-bar
        status = info.get("status", "")
        if status.lower() == "active":
            self._status_indicator.setText("● Active")
            self._status_indicator.setStyleSheet("color: #4CAF50; font-size: 12px; font-weight: 600;")
        elif status.lower() == "expired":
            self._status_indicator.setText("⚠ Expired")
            self._status_indicator.setStyleSheet("color: #F44336; font-size: 12px; font-weight: 600;")
        else:
            self._status_indicator.setText(f"● {status}" if status else "")

    def _apply_account_info(self, data: dict, from_cache: bool = False):
        """Populate account info labels from a data dict."""
        status = data.get("status", "")
        exp_dt: Optional[datetime] = data.get("exp_date_dt")
        created_dt: Optional[datetime] = data.get("created_at_dt")
        active_cons = data.get("active_cons", 0)
        max_cons = data.get("max_connections", 1)

        # Status label
        if status.lower() == "active":
            color = "#4CAF50"
        elif status.lower() == "expired":
            color = "#F44336"
        elif status:
            color = "#FFC107"
        else:
            color = "#888"
        self._acct_status_lbl.setText(status or "Unknown")
        self._acct_status_lbl.setStyleSheet(f"font-weight: 600; color: {color};")

        # Connections
        self._acct_cons_lbl.setText(f"{active_cons} / {max_cons}")

        # Dates
        self._acct_created_lbl.setText(created_dt.strftime("%Y-%m-%d") if created_dt else "—")
        self._acct_exp_lbl.setText(exp_dt.strftime("%Y-%m-%d") if exp_dt else "—")

        # Remaining bar
        if exp_dt:
            now = datetime.now()
            col = subscription_color(exp_dt, created_dt)
            if exp_dt > now:
                days_left = (exp_dt - now).days
                total_days = (exp_dt - created_dt).days if created_dt else 30
                pct = max(0, min(100, int(days_left / total_days * 100))) if total_days > 0 else 100
                suffix = " (cached)" if from_cache else ""
                self._acct_remaining_lbl.setText(f"{days_left} days  ({pct}%){suffix}")
                self._acct_remaining_lbl.setStyleSheet(f"font-weight: 600; color: {col};")
                self._acct_progress.setValue(pct)
                self._acct_progress.setStyleSheet(f"""
                    QProgressBar::chunk {{ background: {col}; border-radius: 3px; }}
                    QProgressBar {{ border-radius: 3px; background: rgba(255,255,255,0.1); }}
                """)
                self._acct_progress.show()
            else:
                self._acct_remaining_lbl.setText("Expired")
                self._acct_remaining_lbl.setStyleSheet("font-weight: 600; color: #F44336;")
                self._acct_progress.setValue(0)
                self._acct_progress.show()
        else:
            self._acct_remaining_lbl.setText("—")
            self._acct_progress.hide()

    # ── URL list ──────────────────────────────────────────────────────────────

    def _rebuild_url_list(self):
        self._url_list.clear()
        total = len(self._provider_urls)
        for i, pu in enumerate(self._provider_urls):
            item = QListWidgetItem()
            widget = URLRowWidget(pu, i, total)
            widget.moveUp.connect(lambda idx=i: self._move_url(idx, -1))
            widget.moveDown.connect(lambda idx=i: self._move_url(idx, 1))
            widget.removed.connect(lambda idx=i: self._remove_url(idx))
            item.setSizeHint(QSize(0, 58))
            self._url_list.addItem(item)
            self._url_list.setItemWidget(item, widget)
        # Fit list height to content (max ~4 rows)
        row_h = 62
        self._url_list.setFixedHeight(min(max(row_h, total * row_h), row_h * 5))

    def _add_url(self):
        url = self._new_url_input.text().strip()
        if not url:
            return
        if any(u.url.rstrip("/") == url.rstrip("/") for u in self._provider_urls):
            return  # duplicate
        max_pri = max((u.priority for u in self._provider_urls), default=-1)
        self._provider_urls.append(ProviderURL(url=url, priority=max_pri + 1))
        self._new_url_input.clear()
        self._rebuild_url_list()

    def _remove_url(self, idx: int):
        if len(self._provider_urls) <= 1:
            QMessageBox.warning(self, "Cannot Remove", "At least one URL is required.")
            return
        self._provider_urls.pop(idx)
        self._rebuild_url_list()

    def _move_url(self, idx: int, delta: int):
        new_idx = idx + delta
        if new_idx < 0 or new_idx >= len(self._provider_urls):
            return
        self._provider_urls[idx], self._provider_urls[new_idx] = (
            self._provider_urls[new_idx], self._provider_urls[idx]
        )
        # Re-assign priority to match visual order
        for i, pu in enumerate(self._provider_urls):
            pu.priority = i
        self._rebuild_url_list()

    # ── Save / delete / discard ───────────────────────────────────────────────

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
            db_prov.epg_url = self._epg_url_input.text().strip()
            db_prov.epg_refresh_hours_before = self._epg_refresh_hours.value()
            db_prov.force_adult = self._force_adult_check.isChecked()

            schedule_map = {0: "manual", 1: "launch", 2: "daily", 3: "weekly", 4: "monthly"}
            db_prov.refresh_schedule = schedule_map.get(self._refresh_combo.currentIndex(), "manual")

            # URLs
            if self._provider_urls:
                db_prov.url = self._provider_urls[0].url  # primary = first in list
            raw_urls = []
            for i, pu in enumerate(self._provider_urls):
                raw_urls.append({
                    "url": pu.url,
                    "priority": i,
                    "is_active": pu.is_active,
                    "success_count": pu.success_count,
                    "failure_count": pu.failure_count,
                })
            db_prov.urls = raw_urls

            # Account info (if freshly fetched)
            if self._pending_account_info:
                info = self._pending_account_info
                db_prov.account_status = info.get("status")
                db_prov.account_active_cons = info.get("active_cons", 0)
                db_prov.max_connections = info.get("max_connections", 1)
                db_prov.account_exp_date = self._parse_ts(info.get("exp_date"))
                db_prov.account_created_at = self._parse_ts(info.get("created_at"))

            db_prov.updated_at = datetime.now()
            session.commit()
            logger.info(f"Provider '{db_prov.name}' saved")
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
            self.load_provider(self._provider_id)

    def _delete_provider(self):
        if not self._provider_id:
            return
        session = self.db.get_session()
        try:
            db_prov = session.query(ProviderDB).filter_by(id=self._provider_id).first()
            name = db_prov.name if db_prov else "this provider"
        finally:
            session.close()

        reply = QMessageBox.question(
            self, "Delete Provider",
            f"Delete '{name}' and all its channels? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        session = self.db.get_session()
        try:
            session.query(ProviderDB).filter_by(id=self._provider_id).delete()
            session.commit()
            pid = self._provider_id
            self._provider_id = None
            self._set_fields_enabled(False)
            self.provider_deleted.emit(pid)
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to delete provider: {e}")
            QMessageBox.critical(self, "Delete Failed", str(e))
        finally:
            session.close()

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
        for i in range(self._url_list.count()):
            w = self._url_list.itemWidget(self._url_list.item(i))
            if isinstance(w, URLRowWidget):
                w.show_testing()

        self._test_thread = TestAllURLsThread(urls, username, password)
        self._test_thread.url_result.connect(self._on_single_url_result)
        self._test_thread.all_done.connect(self._on_all_urls_done)
        self._test_thread.start()

    def _on_single_url_result(self, url: str, success: bool, ms: int, message: str):
        """Update the matching URL row badge as each result arrives."""
        self._test_results_pending = max(0, self._test_results_pending - 1)
        total = len(self._provider_urls)
        done = total - self._test_results_pending
        self._test_btn.setText(f"Testing {done}/{total}…")

        for i in range(self._url_list.count()):
            w = self._url_list.itemWidget(self._url_list.item(i))
            if isinstance(w, URLRowWidget) and w.provider_url.url == url:
                w.show_test_result(success, message)
                break

    def _on_all_urls_done(self, sorted_results: list):
        """Reorder URL list: successes fastest-first, failures last."""
        self._test_btn.setEnabled(True)
        working = [r for r in sorted_results if r[1]]
        failed  = [r for r in sorted_results if not r[1]]

        self._test_btn.setText(
            f"✓ {len(working)}/{len(sorted_results)} working"
            if working else f"✗ All {len(sorted_results)} failed"
        )

        if not sorted_results:
            return

        # Build url→ProviderURL map so we keep stats
        url_map = {pu.url.rstrip("/"): pu for pu in self._provider_urls}

        new_order: List[ProviderURL] = []
        for url, success, ms, _ in sorted_results:
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

    # ── EPG helpers ───────────────────────────────────────────────────────────

    def _build_xmltv_url(self) -> str:
        """Construct the standard Xtream XMLTV URL from the primary server URL and credentials."""
        if not self._provider_urls:
            return ""
        base = self._provider_urls[0].url.rstrip("/")
        username = self._username_input.text().strip()
        password = self._password_input.text().strip()
        if username and password:
            return f"{base}/xmltv.php?username={username}&password={password}"
        return f"{base}/xmltv.php"

    def _try_populate_epg_from_info(self, info: dict):
        """Attempt to fill the EPG URL from server_info if it exposes a usable URL."""
        server_info = info.get("server_info", {}) if isinstance(info, dict) else {}
        # Some providers expose an explicit EPG/XMLTV URL in server_info
        epg_url = server_info.get("epg_url") or server_info.get("xmltv_url") or server_info.get("xmltv_api")
        if epg_url:
            self._epg_url_input.setText(str(epg_url))
            return
        # Fall back to constructing the standard Xtream XMLTV URL
        constructed = self._build_xmltv_url()
        if constructed:
            self._epg_url_input.setText(constructed)

    def _auto_detect_epg(self):
        """Populate EPG URL by constructing the standard XMLTV endpoint from current credentials."""
        url = self._build_xmltv_url()
        if url:
            self._epg_url_input.setText(url)
        else:
            self._epg_url_input.setPlaceholderText("Add at least one server URL first")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _set_fields_enabled(self, enabled: bool):
        for w in [self._icon_picker, self._name_input, self._enabled_check,
                  self._username_input, self._password_input, self._refresh_combo,
                  self._force_adult_check, self._url_list, self._new_url_input,
                  self._refresh_acct_btn, self._test_btn, self._epg_url_input]:
            w.setEnabled(enabled)

    @staticmethod
    def _parse_ts(ts) -> Optional[datetime]:
        if not ts:
            return None
        try:
            return datetime.fromtimestamp(int(ts))
        except Exception:
            return None
