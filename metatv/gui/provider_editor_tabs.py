"""Provider editor — Summary/Connection/Settings tab content builders (Wave 7).

Split out of ``provider_editor.py`` to keep that file under the project's
1000-line limit. Mixed into
:class:`~metatv.gui.provider_editor.ProviderEditorView` via
``class ProviderEditorView(_ProviderEditorTabsMixin, QWidget): ...`` — every
method here reads/writes attributes set up on ``self`` by the host class
(``self.config``, ``self.db``, ``self._epg_manager``, the widgets built by
``ProviderEditorView._build_header_row``/``_build_action_bar``, …), exactly
like every other ``main_window_*`` mixin in this codebase.

Three tabs (built by ``_build_summary_tab``/``_build_connection_tab``/
``_build_settings_tab``, each wrapped in its own scroll area so tall content —
Connection's Credentials + DNS/URLs list — scrolls independently):

  * Summary    — icon/name/status dot, Enabled checkbox, action bar, Account Info.
  * Connection — Credentials, DNS/URLs list.
  * Settings   — Auto-refresh interval, EPG controls, adult-content flag.

The persistent Delete / Test Connection / Discard / Save Changes footer lives
OUTSIDE the ``QTabWidget`` (built directly by ``provider_editor.py``, not
here) — it applies to the whole source, not to a single tab, so it must never
appear to "belong" to just one of them.

Two methods below (``_build_epg_group``, ``_fetch_account_info``) need a class
defined in ``provider_editor.py``; both use a *local* (function-body) import
rather than a module-level one, so this module never imports
``provider_editor`` at parse time — that would be a circular import, since
``provider_editor.py`` imports :class:`_ProviderEditorTabsMixin` from here.
"""
from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QProgressBar,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)
from loguru import logger

from metatv.core.models import ProviderURL
from metatv.core.repositories import RepositoryFactory
from metatv.gui import cursor_affordance
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.url_row_widget import URLRowWidget


def _wrap_scroll(content: QWidget) -> QScrollArea:
    """Wrap *content* in a borderless, resizable vertical-scroll area — one
    shared helper so all three tabs scroll identically."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidget(content)
    return scroll


class _ProviderEditorTabsMixin:
    """Mixin: builds the Summary/Connection/Settings tab content."""

    # ── Tab assembly ─────────────────────────────────────────────────────── #

    def _build_summary_tab(self) -> QScrollArea:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)
        self._build_header_row(layout)
        self._build_action_bar(layout)
        self._build_account_info_group(layout)
        layout.addStretch(1)
        return _wrap_scroll(content)

    def _build_connection_tab(self) -> QScrollArea:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)
        self._build_credentials_group(layout)
        self._build_urls_group(layout)
        layout.addStretch(1)
        return _wrap_scroll(content)

    def _build_settings_tab(self) -> QScrollArea:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)
        self._build_refresh_settings_group(layout)
        self._build_epg_group(layout)
        layout.addStretch(1)
        return _wrap_scroll(content)

    # ── Account Info (Summary tab) ──────────────────────────────────────── #

    def _build_account_info_group(self, layout: QVBoxLayout) -> None:
        group = QGroupBox("Account Info")
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(8)

        # Status row
        status_row = QHBoxLayout()
        self._acct_status_lbl = QLabel("—")
        self._acct_status_lbl.setStyleSheet(_theme.FIELD_LABEL)
        status_row.addWidget(QLabel("Status:"))
        status_row.addWidget(self._acct_status_lbl)
        status_row.addSpacing(24)
        status_row.addWidget(QLabel("Connections:"))
        self._acct_cons_lbl = QLabel("—")
        self._acct_cons_lbl.setStyleSheet(_theme.FIELD_LABEL)
        status_row.addWidget(self._acct_cons_lbl)
        status_row.addStretch()
        group_layout.addLayout(status_row)

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
        group_layout.addLayout(dates_row)

        # EPG guide status — surfaces a provider feed serving stale/out-of-date data
        # (so a blank EPG view reads as "provider's guide is stale", not "our bug").
        # Mirrored by _epg_freshness_lbl in the Settings tab's EPG group — both are
        # kept in sync by _set_epg_status_label (single source of truth).
        epg_row = QHBoxLayout()
        epg_row.addWidget(QLabel("EPG guide:"))
        self._acct_epg_lbl = QLabel("—")
        epg_row.addWidget(self._acct_epg_lbl)
        epg_row.addStretch()
        group_layout.addLayout(epg_row)

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
        group_layout.addLayout(bar_row)

        # Refresh button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._refresh_acct_btn = QPushButton("↻  Refresh Account Info")
        self._refresh_acct_btn.setFixedWidth(180)
        self._refresh_acct_btn.clicked.connect(self._fetch_account_info)
        btn_row.addWidget(self._refresh_acct_btn)
        group_layout.addLayout(btn_row)

        self._acct_error_lbl = QLabel("")
        self._acct_error_lbl.setStyleSheet(f"color: {_theme.COLOR_ERR_2}; font-size: {_theme.FONT_MD};")
        self._acct_error_lbl.hide()
        group_layout.addWidget(self._acct_error_lbl)

        layout.addWidget(group)

    def _fetch_account_info(self) -> None:
        from metatv.gui.provider_editor import FetchAccountInfoThread

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

    def _on_account_info_fetched(self, success: bool, result) -> None:
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

        # Account fetch never changes is_active — only the expiry-derived half of
        # the name-row status dot can have moved.
        self._current_is_expired = bool(exp_dt and exp_dt <= datetime.now())
        self._update_status_dot(self._current_is_active, self._current_is_expired)

        # Auto-save fresh account info to database immediately
        self._persist_account_info(info)

    def _apply_account_info(self, data: dict, from_cache: bool = False) -> None:
        """Populate account info labels from a data dict."""
        status = data.get("status", "")
        exp_dt = data.get("exp_date_dt")
        created_dt = data.get("created_at_dt")
        active_cons = data.get("active_cons", 0)
        max_cons = data.get("max_connections", 1)

        # Status label
        if status.lower() == "active":
            color = _theme.COLOR_OK
        elif status.lower() == "expired":
            color = _theme.COLOR_ERR
        elif status:
            color = _theme.COLOR_WARN
        else:
            color = _theme.COLOR_MUTED
        self._acct_status_lbl.setText(status or "Unknown")
        self._acct_status_lbl.setStyleSheet(f"font-weight: 600; color: {color};")

        # Connections
        self._acct_cons_lbl.setText(f"{active_cons} / {max_cons}")

        # Dates
        self._acct_created_lbl.setText(created_dt.strftime("%Y-%m-%d") if created_dt else "—")
        self._acct_exp_lbl.setText(exp_dt.strftime("%Y-%m-%d") if exp_dt else "—")

        # Remaining bar
        if exp_dt:
            from metatv.gui.provider_editor import subscription_color
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
                self._acct_progress.setStyleSheet(
                    f"QProgressBar::chunk {{ background: {col}; border-radius: 3px; }}"
                    f"QProgressBar {{ border-radius: 3px; background: {_theme.OVERLAY_10}; }}"
                )
                self._acct_progress.show()
            else:
                self._acct_remaining_lbl.setText("Expired")
                self._acct_remaining_lbl.setStyleSheet(f"font-weight: 600; color: {_theme.COLOR_ERR};")
                self._acct_progress.setValue(0)
                self._acct_progress.show()
        else:
            self._acct_remaining_lbl.setText("—")
            self._acct_progress.hide()

    def _persist_account_info(self, info: dict) -> None:
        """Immediately save fresh account info to database.

        Called when account refresh succeeds, so changes persist even if user
        navigates away without clicking Save. Emits account_info_updated signal
        so sidebar can refresh its display.
        """
        from metatv.core.database import ProviderDB

        if not self._provider_id or not info:
            return

        session = self.db.get_session()
        try:
            db_prov = session.query(ProviderDB).filter_by(id=self._provider_id).first()
            if not db_prov:
                return

            db_prov.account_status = info.get("status")
            db_prov.account_active_cons = info.get("active_cons", 0)
            db_prov.max_connections = info.get("max_connections", 1)
            db_prov.account_exp_date = self._parse_ts(info.get("exp_date"))
            db_prov.account_created_at = self._parse_ts(info.get("created_at"))
            db_prov.updated_at = datetime.now()
            session.commit()
            logger.info(f"Account info auto-saved for '{db_prov.name}'")
            self.account_info_updated.emit(self._provider_id)
        except Exception as e:
            logger.error(f"Failed to auto-save account info: {e}")
        finally:
            session.close()

    # ── Credentials (Connection tab) ────────────────────────────────────── #

    def _build_credentials_group(self, layout: QVBoxLayout) -> None:
        group = QGroupBox("Credentials")
        form = QFormLayout(group)
        form.setSpacing(8)

        un_row = QHBoxLayout()
        self._username_input = QLineEdit()
        self._username_input.setClearButtonEnabled(True)
        self._username_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._username_input.setPlaceholderText("username")
        un_row.addWidget(self._username_input, 1)
        self._username_eye_btn = QPushButton(
            self.config.visibility_toggle_icon if self.config else _icons.visibility_toggle_icon
        )
        self._username_eye_btn.setFixedWidth(28)
        self._username_eye_btn.setCheckable(True)
        self._username_eye_btn.setStyleSheet(_theme.EYE_BTN)
        self._username_eye_btn.toggled.connect(
            lambda checked: self._username_input.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
            )
        )
        un_row.addWidget(self._username_eye_btn)
        form.addRow("Username:", un_row)

        pw_row = QHBoxLayout()
        self._password_input = QLineEdit()
        self._password_input.setClearButtonEnabled(True)
        self._password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._password_input.setPlaceholderText("password")
        pw_row.addWidget(self._password_input, 1)
        self._password_eye_btn = QPushButton(
            self.config.visibility_toggle_icon if self.config else _icons.visibility_toggle_icon
        )
        self._password_eye_btn.setFixedWidth(28)
        self._password_eye_btn.setCheckable(True)
        self._password_eye_btn.setStyleSheet(_theme.EYE_BTN)
        self._password_eye_btn.toggled.connect(
            lambda checked: self._password_input.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
            )
        )
        pw_row.addWidget(self._password_eye_btn)
        form.addRow("Password:", pw_row)

        layout.addWidget(group)

    # ── DNS / URLs (Connection tab) ─────────────────────────────────────── #

    def _build_urls_group(self, layout: QVBoxLayout) -> None:
        group = QGroupBox("DNS / URLs  (sorted by reliability — drag or use arrows to reorder)")
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(6)

        # Input ABOVE the list it feeds (#16). A tester pasted URLs into the big
        # list below because that is the obvious target — the list is large and
        # looks like a text area, while the real input sat underneath it, out of
        # the reading path. Entry first, then the result of entering.
        add_row = QHBoxLayout()
        self._new_url_input = QLineEdit()
        self._new_url_input.setClearButtonEnabled(True)
        self._new_url_input.setPlaceholderText("Paste a URL here, e.g. http://newdomain.com:8080")
        self._new_url_input.setToolTip(
            "Add another address for this source. Extra URLs are used as "
            "fallbacks when the first one stops responding."
        )
        self._new_url_input.returnPressed.connect(self._add_url)
        add_row.addWidget(self._new_url_input, 1)
        add_btn = QPushButton("Add URL")
        add_btn.setFixedWidth(80)
        add_btn.setToolTip("Add this address to the list below")
        cursor_affordance.set_clickable(add_btn)
        add_btn.clicked.connect(self._add_url)
        add_row.addWidget(add_btn)
        group_layout.addLayout(add_row)

        self._url_list = QListWidget()
        self._url_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self._url_list.setSpacing(2)
        self._url_list.setToolTip(
            "Addresses already added for this source, most reliable first. "
            "Drag or use the arrows to reorder."
        )
        group_layout.addWidget(self._url_list)

        layout.addWidget(group)

    def _rebuild_url_list(self) -> None:
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

    def _add_url(self) -> None:
        url = self._new_url_input.text().strip()
        if not url:
            return
        if any(u.url.rstrip("/") == url.rstrip("/") for u in self._provider_urls):
            return  # duplicate
        max_pri = max((u.priority for u in self._provider_urls), default=-1)
        self._provider_urls.append(ProviderURL(url=url, priority=max_pri + 1))
        self._new_url_input.clear()
        self._rebuild_url_list()

    def _remove_url(self, idx: int) -> None:
        if len(self._provider_urls) <= 1:
            QMessageBox.warning(self, "Cannot Remove", "At least one URL is required.")
            return
        self._provider_urls.pop(idx)
        self._rebuild_url_list()

    def _move_url(self, idx: int, delta: int) -> None:
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

    # ── General settings (Settings tab) ─────────────────────────────────── #

    def _build_refresh_settings_group(self, layout: QVBoxLayout) -> None:
        group = QGroupBox("General")
        form = QFormLayout(group)
        form.setSpacing(8)

        self._refresh_combo = QComboBox()
        self._refresh_combo.addItems(["Manual", "On App Launch", "Daily", "Weekly", "Every 30 Days"])
        form.addRow("Auto-refresh:", self._refresh_combo)

        self._force_adult_check = QCheckBox("Mark all channels from this source as adult content")
        self._force_adult_check.setToolTip(
            "Enable when this source doesn't tag channels with adult flags "
            "but you want the adult content filter to apply to it."
        )
        form.addRow("Adult content:", self._force_adult_check)

        layout.addWidget(group)

    # ── EPG (Settings tab) ───────────────────────────────────────────────── #

    def _build_epg_group(self, layout: QVBoxLayout) -> None:
        """Build the EPG configuration group box with all EPG controls.

        The manual "refresh now" trigger for this group lives in the Summary
        tab's action bar (``ProviderEditorView._build_action_bar`` →
        ``self._epg_refresh_btn``, reused from its pre-Wave-7 location so this
        group only owns enable / URL override / refresh-interval / freshness —
        the group's job is configuration, not the one-off action.
        """
        from metatv.core.epg_utils import EPG_INTERVAL_CHOICES
        from metatv.gui.provider_editor import _CopyableLabel

        group = QGroupBox("TV guide (EPG)")
        outer = QVBoxLayout(group)
        outer.setSpacing(8)

        explainer = QLabel(
            "A TV guide lists what is playing on each live channel and when. "
            "With it you get the EPG view, On Now, and the ability to set "
            "reminders for upcoming programmes. Most sources publish one "
            "automatically. Leave this on unless the guide is wrong or you "
            "want to save the download."
        )
        explainer.setWordWrap(True)
        explainer.setStyleSheet(_theme.SECTION_HINT)
        outer.addWidget(explainer)

        form_host = QWidget()
        form = QFormLayout(form_host)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)
        outer.addWidget(form_host)

        # 1. Enable / disable — with a right-aligned auto-detect status badge
        self._epg_enabled_check = QCheckBox("Fetch EPG guide for this source")
        self._epg_enabled_check.setChecked(True)
        self._epg_enabled_check.setToolTip(
            "When enabled, MetaTV downloads this source's XMLTV guide data and "
            "shows programme info in the EPG view, On Now, and Watchlist. "
            "Disabling immediately removes the fetched guide data for this source "
            "and skips it on future EPG refreshes. Re-enabling allows the next "
            "refresh to re-fetch it."
        )
        self._epg_detect_badge = QLabel("")
        self._epg_detect_badge.setTextFormat(Qt.TextFormat.RichText)
        enable_row = QHBoxLayout()
        enable_row.setContentsMargins(0, 0, 0, 0)
        enable_row.addWidget(self._epg_enabled_check)
        enable_row.addStretch()
        enable_row.addWidget(self._epg_detect_badge)
        enable_container = QWidget()
        enable_container.setLayout(enable_row)
        form.addRow("Enable EPG:", enable_container)

        # 1b. Auto-detected URL (smaller, click-to-copy). Hidden when none detected.
        self._epg_autodetected_lbl = _CopyableLabel()
        self._epg_autodetected_lbl.setVisible(False)
        form.addRow("", self._epg_autodetected_lbl)

        # 2. URL override
        self._epg_url_override_input = QLineEdit()
        self._epg_url_override_input.setClearButtonEnabled(True)
        self._epg_url_override_input.setPlaceholderText("(uses auto-detected URL)")
        self._epg_url_override_input.setToolTip(
            "Optional: supply your own XMLTV URL for this source. "
            "Leave blank to use the auto-detected feed. "
            "Changing this URL forces the guide to re-fetch on next refresh."
        )
        form.addRow("XMLTV URL override:", self._epg_url_override_input)

        # 3. Freshness label (read-only) — mirrors Account Info's "EPG guide:" line
        # (self._acct_epg_lbl); both are kept in sync by _set_epg_status_label.
        self._epg_freshness_lbl = QLabel("—")
        self._epg_freshness_lbl.setToolTip(
            "Current state of the downloaded EPG guide data for this source."
        )
        form.addRow("Guide freshness:", self._epg_freshness_lbl)

        # 4. Refresh interval
        self._epg_interval_combo = QComboBox()
        self._epg_interval_combo.addItem("Use default (from Settings)", "default")
        for value, label in EPG_INTERVAL_CHOICES:
            self._epg_interval_combo.addItem(label, value)
        self._epg_interval_combo.setToolTip(
            "How often to re-fetch this source's EPG guide. "
            "'Use default' inherits the global setting from Settings → EPG refresh "
            "(the default is Auto). "
            "'Auto' self-tunes: it refreshes at half the guide's depth, clamped to "
            "6 hours – 7 days, so there is always guide headroom. "
            "'Only when data is stale' waits until the guide has fully expired."
        )
        form.addRow("Refresh interval:", self._epg_interval_combo)

        # Disable EPG controls when the checkbox is unchecked
        self._epg_enabled_check.toggled.connect(self._update_epg_controls_enabled)
        self._epg_url_override_input.textChanged.connect(
            lambda _: self._update_epg_refresh_btn_state()
        )
        self._update_epg_controls_enabled(self._epg_enabled_check.isChecked())

        layout.addWidget(group)

    def _update_epg_controls_enabled(self, enabled: bool) -> None:
        """Enable/disable EPG sub-controls based on the Enable EPG checkbox."""
        self._epg_url_override_input.setEnabled(enabled)
        self._epg_interval_combo.setEnabled(enabled)
        self._update_epg_refresh_btn_state()

    def _update_epg_refresh_btn_state(self) -> None:
        """Enable the action bar's "Refresh Guide" button when EPG is on and an
        effective URL exists — the override OR the auto-detected URL (so the
        built-in feed can be refreshed without typing a custom URL)."""
        enabled = self._epg_enabled_check.isChecked()
        has_url = bool(
            self._epg_url_override_input.text().strip()
            or (self._provider_id and getattr(self, "_loaded_epg_url", ""))
        )
        self._epg_refresh_btn.setEnabled(enabled and has_url)

    def _update_epg_autodetected_display(self) -> None:
        """Render the right-aligned auto-detect badge and the click-to-copy auto URL
        line from ``self._loaded_epg_url``: green AUTODETECTED + the URL when one
        exists, red NOT FOUND with the URL line hidden otherwise."""
        auto_url = getattr(self, "_loaded_epg_url", "") or ""
        if auto_url:
            self._epg_detect_badge.setText(
                f'<span style="color:{_theme.COLOR_OK}">{_icons.status_dot_icon}</span> AUTODETECTED'
            )
            self._epg_detect_badge.setToolTip(
                "An XMLTV guide URL was auto-detected from this source's credentials."
            )
            self._epg_autodetected_lbl.set_url(auto_url)
            self._epg_autodetected_lbl.setVisible(True)
        else:
            self._epg_detect_badge.setText(
                f'<span style="color:{_theme.COLOR_ERR}">{_icons.status_dot_icon}</span> NOT FOUND'
            )
            self._epg_detect_badge.setToolTip(
                "No XMLTV guide URL could be auto-detected. Add a URL override to fetch EPG."
            )
            self._epg_autodetected_lbl.set_url("")
            self._epg_autodetected_lbl.setVisible(False)

    def _set_epg_status_label(self, epg_url, epg_data_end, epg_data_start=None) -> None:
        """Populate both EPG-guide status lines (Account Info's "EPG guide:" and
        Settings' "Guide freshness:" — one computation, two displays) from the
        provider's cached EPG fields.

        When the effective refresh interval is Auto, also shows the guide depth
        and the resolved interval so the user can see exactly what Auto computed.

        Uses the canonical epg_is_stale boundary so this matches the EPG view notice.

        Args:
            epg_url:        Effective EPG URL (auto-detected or override).
            epg_data_end:   Latest non-filler programme stop (UTC-naive).
            epg_data_start: Earliest programme start (UTC-naive); used only for the
                            Auto depth annotation.
        """
        from metatv.core.epg_utils import epg_auto_delta, epg_is_stale, to_local

        if not epg_url:
            text, style = "Not configured", f"color: {_theme.COLOR_MUTED};"
        elif epg_data_end is None:
            text, style = "No guide data fetched yet", f"color: {_theme.COLOR_MUTED};"
        else:
            try:
                day = to_local(epg_data_end).strftime("%d %b %Y").lstrip("0")
            except Exception:
                day = str(epg_data_end)
            if epg_is_stale(epg_data_end):
                text = f"{_icons.notification_warning_icon} Stale — guide ends {day} (source out of date)"
                style = f"color: {_theme.COLOR_WARN};"
            else:
                auto_note = ""
                if epg_data_start is not None and epg_data_end is not None:
                    depth = epg_data_end - epg_data_start
                    depth_days = depth.total_seconds() / 86400
                    resolved = epg_auto_delta(epg_data_start, epg_data_end)
                    resolved_hours = resolved.total_seconds() / 3600
                    resolved_str = (
                        f"{resolved_hours:.0f}h" if resolved_hours < 24
                        else f"{resolved_hours / 24:.0f}d"
                    )
                    auto_note = (
                        f" · Auto: ~{depth_days:.0f}-day feed → refreshing ~every {resolved_str}"
                    )
                text = f"Current — guide through {day}{auto_note}"
                style = f"color: {_theme.COLOR_OK};"

        for lbl in (self._acct_epg_lbl, self._epg_freshness_lbl):
            lbl.setText(text)
            lbl.setStyleSheet(style)
