"""Settings dialog with Playback, Metadata/API Keys, and Sidebar tabs."""

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QFormLayout, QComboBox, QCheckBox, QSpinBox, QLineEdit,
    QPushButton, QLabel, QDialogButtonBox, QGroupBox, QListWidget, QListWidgetItem,
)
from loguru import logger

from metatv.core.config import Config
from metatv.core.epg_utils import EPG_INTERVAL_CHOICES
from metatv.core.http_headers import stream_user_agent
from metatv.gui import theme as _theme

_SIDEBAR_SECTION_LABELS: dict[str, str] = {
    "alerts":      "Alerts",
    "recommended": "Recommended",
    "queue":       "Watch Queue",
    "favorites":   "Favorites",
    "history":     "History",
    "sources":     "Sources",
}
_ALL_SIDEBAR_SECTIONS = list(_SIDEBAR_SECTION_LABELS.keys())


class SettingsDialog(QDialog):
    """Modal settings dialog with Playback and Metadata/API Keys tabs."""

    settings_applied = pyqtSignal()  # emitted on Apply (not OK — OK closes the dialog)

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Settings")
        self.setMinimumWidth(520)
        self.setModal(True)
        self._setup_ui()
        self._load_values()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_playback_tab(), "Playback")
        self._tabs.addTab(self._build_metadata_tab(), "Metadata & API Keys")
        self._tabs.addTab(self._build_sidebar_tab(), "Sidebar")
        layout.addWidget(self._tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel |
            QDialogButtonBox.StandardButton.Apply
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._apply)
        layout.addWidget(buttons)

    def _build_playback_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(16)
        layout.setContentsMargins(12, 12, 12, 12)

        player_group = QGroupBox("Player")
        player_form = QFormLayout(player_group)
        player_form.setSpacing(8)

        self._player_combo = QComboBox()
        self._player_combo.addItems(["mpv", "vlc", "custom"])
        player_form.addRow("Preferred player:", self._player_combo)

        self._player_mode_combo = QComboBox()
        self._player_mode_combo.addItems(["Single instance", "Multiple instances"])
        player_form.addRow("Player mode:", self._player_mode_combo)

        self._autoplay_check = QCheckBox("Autoplay next episode when playing from a season")
        player_form.addRow("", self._autoplay_check)

        self._prompt_after_autoplay_check = QCheckBox(
            "Ask \"Still here?\" after auto-advancing through episodes"
        )
        self._prompt_after_autoplay_check.setToolTip(
            "After the queue auto-advances through one or more episodes and the player\n"
            "closes, ask whether you actually watched them. Confirming promotes them from\n"
            "gray (auto-watched) to solid (fully engaged) and advances your resume point."
        )
        player_form.addRow("", self._prompt_after_autoplay_check)

        threshold_row = QHBoxLayout()
        self._watch_threshold_spin = QSpinBox()
        self._watch_threshold_spin.setRange(50, 100)
        self._watch_threshold_spin.setSuffix("%")
        self._watch_threshold_spin.setToolTip(
            "How much of a movie or episode must be watched before it counts as finished.\n"
            "Shows ✓ in the channel list and a Watched badge in the Discover view."
        )
        threshold_row.addWidget(self._watch_threshold_spin)
        threshold_row.addStretch()
        player_form.addRow("Mark as watched at:", threshold_row)

        partial_threshold_row = QHBoxLayout()
        self._watch_partial_spin = QSpinBox()
        self._watch_partial_spin.setRange(1, 49)
        self._watch_partial_spin.setSuffix("%")
        self._watch_partial_spin.setToolTip(
            "Minimum amount watched before a progress glyph (◔ / ◐ / ◕) appears in the\n"
            "channel list and series view.\n"
            "Below this percentage the item is treated as untouched (no indicator shown)."
        )
        partial_threshold_row.addWidget(self._watch_partial_spin)
        partial_threshold_row.addStretch()
        player_form.addRow("Mark as partially-watched after:", partial_threshold_row)

        self._close_player_check = QCheckBox("Close player when stream finishes")
        player_form.addRow("", self._close_player_check)

        self._buffer_combo = QComboBox()
        self._buffer_combo.addItem("Reconnect only (no extra buffer)", userData="reconnect_only")
        self._buffer_combo.addItem("Modest (~10s buffer)", userData="modest")
        self._buffer_combo.addItem("Large (~30s buffer)", userData="large")
        self._buffer_combo.setToolTip(
            "Controls how much media mpv buffers ahead while playing.\n"
            "\n"
            "• Reconnect only — no extra buffer; lowest memory use.\n"
            "• Modest (~10s) — default; absorbs brief network hiccups.\n"
            "• Large (~30s) — useful on congested or high-latency links.\n"
            "\n"
            "Auto-reconnect is always on regardless of this setting."
        )
        player_form.addRow("Buffering:", self._buffer_combo)

        buffer_hint = QLabel("Auto-reconnect is always on — streams resume after brief drops.")
        buffer_hint.setStyleSheet(_theme.META_HINT)
        player_form.addRow("", buffer_hint)

        self._prebuffer_check = QCheckBox("Pre-buffer before playing")
        self._prebuffer_check.setToolTip(
            "Wait until the buffer fills before starting — smoother start, slightly slower to begin."
        )
        player_form.addRow("", self._prebuffer_check)

        prebuffer_wait_row = QHBoxLayout()
        self._prebuffer_wait_spin = QSpinBox()
        self._prebuffer_wait_spin.setRange(1, 120)
        self._prebuffer_wait_spin.setSuffix(" s")
        self._prebuffer_wait_spin.setToolTip(
            "How many seconds of content to buffer before unpausing and starting playback."
        )
        prebuffer_wait_row.addWidget(self._prebuffer_wait_spin)
        prebuffer_wait_row.addStretch()
        player_form.addRow("Pre-buffer wait:", prebuffer_wait_row)

        self._split_check = QCheckBox("Split streams — one player window per source")
        self._split_check.setToolTip(
            "When on, a stream from a different source opens in its own player window "
            "instead of replacing the current one. Each source still allows only one connection."
        )
        player_form.addRow("", self._split_check)

        self._user_agent_view = QLineEdit()
        self._user_agent_view.setReadOnly(True)
        self._user_agent_view.setToolTip(
            "Sent when validating, diagnosing, and playing streams (shared across all three)."
        )
        player_form.addRow("HTTP User-Agent:", self._user_agent_view)

        layout.addWidget(player_group)

        net_group = QGroupBox("Network")
        net_form = QFormLayout(net_group)
        net_form.setSpacing(8)

        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(1, 60)
        self._timeout_spin.setSuffix(" s")
        net_form.addRow("Network timeout:", self._timeout_spin)

        self._reconnect_spin = QSpinBox()
        self._reconnect_spin.setRange(0, 10)
        net_form.addRow("Reconnect attempts:", self._reconnect_spin)

        layout.addWidget(net_group)

        epg_group = QGroupBox("EPG")
        epg_form = QFormLayout(epg_group)
        epg_form.setSpacing(8)

        self._epg_interval_combo = QComboBox()
        for value, label in EPG_INTERVAL_CHOICES:
            self._epg_interval_combo.addItem(label, value)
        self._epg_interval_combo.setToolTip(
            "Default EPG guide refresh frequency for all providers. "
            "Individual providers can override this in their editor. "
            "'Only when data is stale' waits until the guide has fully expired before re-fetching."
        )
        epg_form.addRow("EPG refresh:", self._epg_interval_combo)

        layout.addWidget(epg_group)

        mpv_group = QGroupBox("MPV Extra Arguments")
        mpv_layout = QVBoxLayout(mpv_group)
        mpv_layout.setSpacing(4)
        self._mpv_args_input = QLineEdit()
        self._mpv_args_input.setPlaceholderText("--cache=yes --demuxer-max-bytes=50M")
        hint = QLabel(
            "Space-separated flags passed directly to mpv. "
            "The Diagnose tool's “Apply tuning” writes its recommended cache flags here."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(_theme.META_HINT)
        mpv_layout.addWidget(self._mpv_args_input)
        mpv_layout.addWidget(hint)

        self._override_all_check = QCheckBox(
            "Override all — use only these flags (ignore profile, reconnect, User-Agent)"
        )
        self._override_all_check.setToolTip(
            "When enabled, mpv receives only the flags entered above.\n"
            "Warning: this bypasses the canonical User-Agent and auto-reconnect.\n"
            "Use only for advanced manual control."
        )
        mpv_layout.addWidget(self._override_all_check)
        layout.addWidget(mpv_group)

        search_group = QGroupBox("Search")
        search_form = QFormLayout(search_group)
        search_form.setSpacing(8)

        self._remember_search_check = QCheckBox("Remember last search")
        self._remember_search_check.setToolTip(
            "When on, MetaTV saves your search query, source filter, and active\n"
            "context chips when you change them, and restores them the next time\n"
            "you launch the app or return to the channel list."
        )
        search_form.addRow("", self._remember_search_check)

        search_hint = QLabel(
            "Restores the query text, source filter (if any), All/Hidden toggle, "
            "and genre/person chips from your last session."
        )
        search_hint.setWordWrap(True)
        search_hint.setStyleSheet(_theme.META_HINT)
        search_form.addRow("", search_hint)

        layout.addWidget(search_group)

        layout.addStretch()
        return tab

    def _build_metadata_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(16)
        layout.setContentsMargins(12, 12, 12, 12)

        meta_group = QGroupBox("Metadata Enrichment")
        meta_form = QFormLayout(meta_group)
        meta_form.setSpacing(8)

        self._meta_enabled_check = QCheckBox("Enable metadata enrichment")
        meta_form.addRow("", self._meta_enabled_check)

        self._meta_autofetch_check = QCheckBox("Auto-fetch on channel select")
        meta_form.addRow("", self._meta_autofetch_check)

        self._cache_ttl_spin = QSpinBox()
        self._cache_ttl_spin.setRange(1, 365)
        self._cache_ttl_spin.setSuffix(" days")
        meta_form.addRow("Cache TTL (fresh content):", self._cache_ttl_spin)

        self._cache_old_ttl_spin = QSpinBox()
        self._cache_old_ttl_spin.setRange(1, 365)
        self._cache_old_ttl_spin.setSuffix(" days")
        meta_form.addRow("Cache TTL (old content >2yr):", self._cache_old_ttl_spin)

        layout.addWidget(meta_group)

        tmdb_group = QGroupBox("TMDb")
        tmdb_form = QFormLayout(tmdb_group)
        tmdb_form.setSpacing(8)

        tmdb_key_row = QHBoxLayout()
        self._tmdb_key_input = QLineEdit()
        self._tmdb_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._tmdb_key_input.setPlaceholderText("your-tmdb-api-key")
        tmdb_key_row.addWidget(self._tmdb_key_input, 1)
        tmdb_link_btn = QPushButton("Get key →")
        tmdb_link_btn.setFixedWidth(80)
        tmdb_link_btn.setStyleSheet(
            f"QPushButton {{ color: {_theme.COLOR_ACCENT_BLUE}; border: none; padding: 0; }}"
            f" QPushButton:hover {{ color: {_theme.COLOR_ACCENT_BLUE_2}; }}"
        )
        tmdb_link_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://www.themoviedb.org/settings/api"))
        )
        tmdb_key_row.addWidget(tmdb_link_btn)
        tmdb_form.addRow("API key:", tmdb_key_row)

        self._tmdb_lang_input = QLineEdit()
        self._tmdb_lang_input.setPlaceholderText("en-US")
        self._tmdb_lang_input.setMaxLength(10)
        tmdb_form.addRow("Language:", self._tmdb_lang_input)

        layout.addWidget(tmdb_group)

        omdb_group = QGroupBox("OMDb")
        omdb_form = QFormLayout(omdb_group)
        omdb_form.setSpacing(8)

        omdb_key_row = QHBoxLayout()
        self._omdb_key_input = QLineEdit()
        self._omdb_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._omdb_key_input.setPlaceholderText("your-omdb-api-key")
        omdb_key_row.addWidget(self._omdb_key_input, 1)
        omdb_link_btn = QPushButton("Get key →")
        omdb_link_btn.setFixedWidth(80)
        omdb_link_btn.setStyleSheet(
            f"QPushButton {{ color: {_theme.COLOR_ACCENT_BLUE}; border: none; padding: 0; }}"
            f" QPushButton:hover {{ color: {_theme.COLOR_ACCENT_BLUE_2}; }}"
        )
        omdb_link_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://www.omdbapi.com/apikey.aspx"))
        )
        omdb_key_row.addWidget(omdb_link_btn)
        omdb_form.addRow("API key:", omdb_key_row)

        layout.addWidget(omdb_group)

        layout.addStretch()
        return tab

    def _build_sidebar_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)
        layout.setContentsMargins(12, 12, 12, 12)

        hint = QLabel(
            "Check sections to show them. Use the arrows to reorder.\n"
            "All changes apply immediately when you click OK or Apply."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {_theme.COLOR_MUTED}; font-size: {_theme.FONT_MD};")
        layout.addWidget(hint)

        self._sidebar_list = QListWidget()
        self._sidebar_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self._sidebar_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._sidebar_list.setFixedHeight(200)
        layout.addWidget(self._sidebar_list)

        arrow_row = QHBoxLayout()
        up_btn = QPushButton("▲  Move Up")
        up_btn.setFixedWidth(110)
        up_btn.clicked.connect(self._sidebar_move_up)
        down_btn = QPushButton("▼  Move Down")
        down_btn.setFixedWidth(110)
        down_btn.clicked.connect(self._sidebar_move_down)
        arrow_row.addWidget(up_btn)
        arrow_row.addWidget(down_btn)
        arrow_row.addStretch()
        layout.addLayout(arrow_row)


        layout.addStretch()
        return tab

    def _sidebar_move_up(self) -> None:
        row = self._sidebar_list.currentRow()
        if row > 0:
            item = self._sidebar_list.takeItem(row)
            self._sidebar_list.insertItem(row - 1, item)
            self._sidebar_list.setCurrentRow(row - 1)

    def _sidebar_move_down(self) -> None:
        row = self._sidebar_list.currentRow()
        if 0 <= row < self._sidebar_list.count() - 1:
            item = self._sidebar_list.takeItem(row)
            self._sidebar_list.insertItem(row + 1, item)
            self._sidebar_list.setCurrentRow(row + 1)

    def _load_values(self):
        """Populate widgets from current config."""
        c = self.config

        # Playback
        player_idx = {"mpv": 0, "vlc": 1}.get(c.preferred_player, 2)
        self._player_combo.setCurrentIndex(player_idx)

        mode_idx = 0 if c.player_mode == "single-instance" else 1
        self._player_mode_combo.setCurrentIndex(mode_idx)

        self._autoplay_check.setChecked(c.autoplay_season_episodes)
        self._prompt_after_autoplay_check.blockSignals(True)
        self._prompt_after_autoplay_check.setChecked(
            getattr(c, "prompt_after_autoplay", True)
        )
        self._prompt_after_autoplay_check.blockSignals(False)
        self._watch_threshold_spin.setValue(
            int(round(getattr(c, "watch_complete_threshold", 0.9) * 100))
        )
        self._watch_partial_spin.setValue(
            int(round(getattr(c, "watch_partial_threshold", 0.10) * 100))
        )
        self._close_player_check.setChecked(c.close_player_when_finished)
        self._timeout_spin.setValue(c.network_timeout)
        self._reconnect_spin.setValue(c.reconnect_attempts)

        buf_idx = self._buffer_combo.findData(c.buffer_profile)
        self._buffer_combo.setCurrentIndex(buf_idx if buf_idx >= 0 else self._buffer_combo.findData("modest"))

        self._user_agent_view.setText(stream_user_agent())

        self._mpv_args_input.setText(" ".join(c.mpv_extra_args))
        self._prebuffer_check.setChecked(getattr(c, "prebuffer_before_play", False))
        self._prebuffer_wait_spin.setValue(getattr(c, "prebuffer_wait_secs", 10))
        self._override_all_check.setChecked(getattr(c, "mpv_args_override_all", False))
        self._split_check.setChecked(getattr(c, "split_streams_by_source", False))

        # Search
        self._remember_search_check.blockSignals(True)
        self._remember_search_check.setChecked(getattr(c, "remember_search", True))
        self._remember_search_check.blockSignals(False)

        # EPG
        epg_idx = self._epg_interval_combo.findData(c.epg_default_refresh_interval)
        self._epg_interval_combo.setCurrentIndex(epg_idx if epg_idx >= 0 else 0)

        # Metadata
        self._meta_enabled_check.setChecked(c.metadata_enabled)
        self._meta_autofetch_check.setChecked(c.metadata_auto_fetch)
        self._cache_ttl_spin.setValue(c.metadata_cache_ttl_days)
        self._cache_old_ttl_spin.setValue(c.metadata_old_content_ttl_days)
        self._tmdb_key_input.setText(c.metadata_tmdb_api_key)
        self._tmdb_lang_input.setText(c.metadata_tmdb_language)
        self._omdb_key_input.setText(c.metadata_omdb_api_key)

        # Sidebar
        ordered = list(c.sidebar_sections or _ALL_SIDEBAR_SECTIONS)
        visible = set(c.sidebar_visible_sections or _ALL_SIDEBAR_SECTIONS)
        # Append any known sections not yet in the saved order (e.g. new sections added after install)
        for sid in _ALL_SIDEBAR_SECTIONS:
            if sid not in ordered:
                ordered.append(sid)
        self._sidebar_list.clear()
        for sid in ordered:
            label = _SIDEBAR_SECTION_LABELS.get(sid, sid)
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, sid)
            item.setCheckState(
                Qt.CheckState.Checked if sid in visible else Qt.CheckState.Unchecked
            )
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            self._sidebar_list.addItem(item)

    def _save_values(self):
        """Write widget values back to config and persist."""
        c = self.config

        # Playback
        c.preferred_player = self._player_combo.currentText()
        c.player_mode = (
            "single-instance" if self._player_mode_combo.currentIndex() == 0
            else "multiple-instances"
        )
        c.autoplay_season_episodes = self._autoplay_check.isChecked()
        c.prompt_after_autoplay = self._prompt_after_autoplay_check.isChecked()
        c.watch_complete_threshold = self._watch_threshold_spin.value() / 100.0
        c.watch_partial_threshold = self._watch_partial_spin.value() / 100.0
        c.close_player_when_finished = self._close_player_check.isChecked()
        c.network_timeout = self._timeout_spin.value()
        c.reconnect_attempts = self._reconnect_spin.value()
        c.buffer_profile = self._buffer_combo.currentData()
        # Reset to "auto" so the buffer_profile (now the sole buffer control) takes effect;
        # an explicit byte size in default_cache_size would bypass the profile entirely.
        c.default_cache_size = "auto"

        raw_args = self._mpv_args_input.text().strip()
        c.mpv_extra_args = raw_args.split() if raw_args else []
        c.prebuffer_before_play = self._prebuffer_check.isChecked()
        c.prebuffer_wait_secs = self._prebuffer_wait_spin.value()
        c.mpv_args_override_all = self._override_all_check.isChecked()
        c.split_streams_by_source = self._split_check.isChecked()

        # Search
        c.remember_search = self._remember_search_check.isChecked()

        # EPG
        epg_val = self._epg_interval_combo.currentData()
        if epg_val:
            c.epg_default_refresh_interval = epg_val

        # Metadata
        c.metadata_enabled = self._meta_enabled_check.isChecked()
        c.metadata_auto_fetch = self._meta_autofetch_check.isChecked()
        c.metadata_cache_ttl_days = self._cache_ttl_spin.value()
        c.metadata_old_content_ttl_days = self._cache_old_ttl_spin.value()
        c.metadata_tmdb_api_key = self._tmdb_key_input.text().strip()
        c.metadata_tmdb_language = self._tmdb_lang_input.text().strip()
        c.metadata_omdb_api_key = self._omdb_key_input.text().strip()

        # Sidebar
        new_order = []
        new_visible = []
        for i in range(self._sidebar_list.count()):
            item = self._sidebar_list.item(i)
            sid = item.data(Qt.ItemDataRole.UserRole)
            new_order.append(sid)
            if item.checkState() == Qt.CheckState.Checked:
                new_visible.append(sid)
        c.sidebar_sections = new_order
        c.sidebar_visible_sections = new_visible

        c.save()
        logger.info("Settings saved")

    def _apply(self):
        self._save_values()
        self.settings_applied.emit()

    def _accept(self):
        self._save_values()
        self.accept()
