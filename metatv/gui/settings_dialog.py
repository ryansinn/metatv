"""Settings dialog with Playback, Interaction, Recommendations, Metadata/API Keys, and Interface tabs."""

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QFormLayout, QComboBox, QCheckBox, QDoubleSpinBox, QSpinBox, QLineEdit,
    QPushButton, QLabel, QDialogButtonBox, QGroupBox, QListWidget, QListWidgetItem,
)
from loguru import logger

from metatv.core.config import Config
from metatv.core.epg_utils import EPG_INTERVAL_CHOICES, EPG_SCRUBBER_INCREMENTS
from metatv.core.http_headers import stream_user_agent
from metatv.core.media_mix import format_media_share
from metatv.core.preference_engine import RecScoringSettings
from metatv.gui import theme as _theme
from metatv.gui.middle_click_actions import (
    DEFAULT_MIDDLE_CLICK_ACTION,
    MIDDLE_CLICK_ACTIONS,
)

_SIDEBAR_SECTION_LABELS: dict[str, str] = {
    "alerts":      "Watch Alerts",
    "recommended": "Recommended",
    "queue":       "Watch Queue",
    "favorites":   "Favorites",
    "history":     "History",
    "sources":     "Sources",
}
_ALL_SIDEBAR_SECTIONS = list(_SIDEBAR_SECTION_LABELS.keys())


_CHANNEL_DENSITY_CHOICES: tuple[tuple[str, str], ...] = (
    ("Comfy (two lines)", "comfy"),
    ("Compact (one line)", "compact"),
)


def _load_channel_density(combo: QComboBox, config) -> None:
    """Select ``config.channel_list_density`` in ``combo`` (falls back to comfy).

    Factored out of ``_load_values`` so the density round-trip is testable
    against a bare ``QComboBox`` + a minimal fake config — no full
    ``SettingsDialog`` skeleton required.
    """
    density = getattr(config, "channel_list_density", "comfy")
    idx = combo.findData(density)
    combo.setCurrentIndex(idx if idx >= 0 else combo.findData("comfy"))


def _save_channel_density(combo: QComboBox, config) -> None:
    """Write the selected density back to ``config.channel_list_density``."""
    config.channel_list_density = combo.currentData() or "comfy"


def _dial_or_none(value: float, default: float):
    """Return ``None`` when a dial still sits on its default, else the value.

    Storing ``None`` for an untouched dial keeps config free of numbers the user
    never chose — and lets a future change to the shipped default reach everyone
    who never overrode it.
    """
    return None if abs(float(value) - float(default)) < 1e-9 else value


class SettingsDialog(QDialog):
    """Modal settings dialog with Playback, Interaction, Metadata/API Keys, and Interface tabs."""

    settings_applied = pyqtSignal()  # emitted on Apply (not OK — OK closes the dialog)
    check_updates_requested = pyqtSignal()  # "Check for updates now" clicked (Interface → Updates)

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
        self._tabs.addTab(self._build_interaction_tab(), "Interaction")
        self._tabs.addTab(self._build_recommendations_tab(), "Recommendations")
        self._tabs.addTab(self._build_metadata_tab(), "Metadata & API Keys")
        self._tabs.addTab(self._build_interface_tab(), "Interface")
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
        self._buffer_combo.addItem("Open-ended (disk-backed, max buffer)", userData="open_ended")
        self._buffer_combo.setToolTip(
            "Controls how much media mpv buffers ahead while playing.\n"
            "\n"
            "• Reconnect only — no extra buffer; lowest memory use.\n"
            "• Modest (~10s) — default; absorbs brief network hiccups.\n"
            "• Large (~30s) — useful on congested or high-latency links.\n"
            "• Open-ended — buffers as far ahead as the stream allows\n"
            "  (disk-backed, up to 2 GiB / 1 hour); best for unstable\n"
            "  streams or when you want the maximum lead time. Uses more\n"
            "  disk space while playing.\n"
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

        self._recheck_failed_on_refresh_check = QCheckBox(
            "Re-check failed streams on source refresh"
        )
        self._recheck_failed_on_refresh_check.setToolTip(
            "When a source finishes refreshing, immediately re-probe any of its\n"
            "streams that previously failed (flagged/degraded/dead) instead of\n"
            "waiting for the background retry checker's own schedule. Recovered\n"
            "streams are restored to full visibility right away."
        )
        net_form.addRow("", self._recheck_failed_on_refresh_check)

        layout.addWidget(net_group)

        mpv_group = QGroupBox("MPV Extra Arguments")
        mpv_layout = QVBoxLayout(mpv_group)
        mpv_layout.setSpacing(4)
        self._mpv_args_input = QLineEdit()
        self._mpv_args_input.setClearButtonEnabled(True)
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

        layout.addStretch()
        return tab

    def _build_interaction_tab(self) -> QWidget:
        """Build the Interaction tab — how clicks on a channel row play it.

        Houses the default double-click action (``playback_resume_mode``) and the
        configurable middle-click action (``middle_click_action``); the latter's
        combo is populated from the shared ``MIDDLE_CLICK_ACTIONS`` registry so new
        actions appear here automatically.
        """
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(16)
        layout.setContentsMargins(12, 12, 12, 12)

        click_group = QGroupBox("Channel row clicks")
        click_form = QFormLayout(click_group)
        click_form.setSpacing(8)

        self._resume_mode_combo = QComboBox()
        self._resume_mode_combo.addItem("Resume (when a saved position exists)", userData="resume")
        self._resume_mode_combo.addItem("Start from beginning", userData="beginning")
        self._resume_mode_combo.setToolTip(
            "What a bare double-click on a movie does when you've already started it.\n"
            "\n"
            "• Resume — pick up from your saved position when one exists (default).\n"
            "• Start from beginning — always start at the beginning.\n"
            "\n"
            "The details-pane Play button always starts from the beginning and Resume\n"
            "always resumes; right-click any movie for a one-time override without\n"
            "changing this setting."
        )
        click_form.addRow("Default double-click action:", self._resume_mode_combo)

        self._middle_click_combo = QComboBox()
        for action in MIDDLE_CLICK_ACTIONS:
            self._middle_click_combo.addItem(action.label, userData=action.key)
        self._middle_click_combo.setToolTip(
            "What a middle-click on a channel row does.\n"
            "\n"
            "• Resume from saved position — pick up where you left off (default).\n"
            "• Play with endless buffer — disk-backed maximum buffer for unstable streams.\n"
            "\n"
            "Independent of the double-click default above."
        )
        click_form.addRow("Middle-click action:", self._middle_click_combo)

        layout.addWidget(click_group)

        layout.addStretch()
        return tab

    def _build_recommendations_tab(self) -> QWidget:
        """Build the Recommendations tab — steering dials for the preference engine.

        Every control ships at the engine's own default (``RecScoringSettings``),
        so this panel is for steering, not required setup: an untouched tab writes
        nothing and the engine keeps using its defaults.
        """
        defaults = RecScoringSettings()

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(16)
        layout.setContentsMargins(12, 12, 12, 12)

        # ── Movie / series mix ──────────────────────────────────────────────
        mix_group = QGroupBox("Movie / series mix")
        mix_layout = QVBoxLayout(mix_group)
        mix_layout.setSpacing(8)

        self._rec_mix_auto_check = QCheckBox(
            "Automatic — follow the balance of what you actually watch"
        )
        self._rec_mix_auto_check.setToolTip(
            "Derives the split from your likes, favorites, queue and plays, damped by\n"
            "square root so the smaller type is never crowded out: 100 movies to 15\n"
            "series lands at roughly 72 : 28, not 87 : 13."
        )
        self._rec_mix_auto_check.toggled.connect(self._on_rec_mix_auto_toggled)
        mix_layout.addWidget(self._rec_mix_auto_check)

        mix_row = QHBoxLayout()
        self._rec_mix_spin = QSpinBox()
        self._rec_mix_spin.setRange(0, 100)
        self._rec_mix_spin.setSuffix("% movies")
        self._rec_mix_spin.setToolTip(
            "Your own split: the share of recommendation slots given to movies.\n"
            "The rest go to series. Shared with the slider in the Recommendations dashboard."
        )
        self._rec_mix_spin.valueChanged.connect(self._on_rec_mix_value_changed)
        mix_row.addWidget(self._rec_mix_spin)

        self._rec_mix_ratio_label = QLabel("")
        self._rec_mix_ratio_label.setStyleSheet(_theme.META_HINT)
        mix_row.addWidget(self._rec_mix_ratio_label)
        mix_row.addStretch()
        mix_layout.addLayout(mix_row)

        mix_hint = QLabel(
            "The Recommendations dashboard shows the ratio currently in use "
            "and has the same control as a slider."
        )
        mix_hint.setWordWrap(True)
        mix_hint.setStyleSheet(_theme.META_HINT)
        mix_layout.addWidget(mix_hint)
        layout.addWidget(mix_group)

        # ── Attribute weights ───────────────────────────────────────────────
        weights_group = QGroupBox("Attribute weights")
        weights_form = QFormLayout(weights_group)
        weights_form.setSpacing(8)

        def _weight_spin(tooltip: str, default: float) -> QDoubleSpinBox:
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 5.0)
            spin.setSingleStep(0.05)
            spin.setDecimals(2)
            spin.setToolTip(f"{tooltip}\nDefault: {default:g}. 0 turns the field off entirely.")
            return spin

        self._rec_genre_spin = _weight_spin(
            "How much a shared genre counts. This is the reference unit — the other "
            "weights are relative to it.", defaults.genre_weight)
        weights_form.addRow("Genre:", self._rec_genre_spin)

        self._rec_director_spin = _weight_spin(
            "How much a shared director counts.", defaults.director_weight)
        weights_form.addRow("Director:", self._rec_director_spin)

        self._rec_actor_spin = _weight_spin(
            "How much a shared cast member counts. Deliberately small — a matched "
            "face nudges, it does not decide.", defaults.actor_weight)
        weights_form.addRow("Cast:", self._rec_actor_spin)

        self._rec_keyword_spin = _weight_spin(
            "How much shared plot keywords count.", defaults.keyword_weight)
        weights_form.addRow("Keywords:", self._rec_keyword_spin)

        layout.addWidget(weights_group)

        # ── Tuning ──────────────────────────────────────────────────────────
        tuning_group = QGroupBox("Tuning")
        tuning_form = QFormLayout(tuning_group)
        tuning_form.setSpacing(8)

        self._rec_actor_support_spin = QSpinBox()
        self._rec_actor_support_spin.setRange(1, 10)
        self._rec_actor_support_spin.setSuffix(" titles")
        self._rec_actor_support_spin.setToolTip(
            "How many liked or favorited titles a performer must appear in before they\n"
            f"count at all. Default: {defaults.actor_min_support}. 1 lets a single film's\n"
            "whole cast shape your recommendations."
        )
        tuning_form.addRow("Cast needs support of:", self._rec_actor_support_spin)

        self._rec_diversity_spin = QDoubleSpinBox()
        self._rec_diversity_spin.setRange(0.1, 1.0)
        self._rec_diversity_spin.setSingleStep(0.05)
        self._rec_diversity_spin.setDecimals(2)
        self._rec_diversity_spin.setToolTip(
            "Knock-down applied to the next candidate sharing a performer or director\n"
            f"already placed in the list. Default: {defaults.people_diversity_decay:g};\n"
            "lower spreads faces out harder, 1.00 turns the spreading off."
        )
        tuning_form.addRow("People diversity:", self._rec_diversity_spin)

        self._rec_impression_spin = QSpinBox()
        self._rec_impression_spin.setRange(0, 20)
        self._rec_impression_spin.setSuffix("% per view")
        self._rec_impression_spin.setToolTip(
            "How much an item's score drops each time it has been shown to you, so the\n"
            f"list rotates. Default: {round(defaults.impression_decay * 100)}%; 0 keeps "
            "shown items at full strength."
        )
        tuning_form.addRow("Impression decay:", self._rec_impression_spin)

        self._rec_liked_cap_spin = QSpinBox()
        self._rec_liked_cap_spin.setRange(0, 10)
        self._rec_liked_cap_spin.setSuffix(" slots")
        self._rec_liked_cap_spin.setToolTip(
            "How many slots things you have already liked may occupy; the rest go to\n"
            f"fresh discoveries. Default: {defaults.liked_cap}."
        )
        tuning_form.addRow("Already-liked items:", self._rec_liked_cap_spin)

        layout.addWidget(tuning_group)

        reset_row = QHBoxLayout()
        self._rec_reset_btn = QPushButton("Reset to defaults")
        self._rec_reset_btn.setToolTip(
            "Put every recommendation dial on this tab back to its shipped default."
        )
        self._rec_reset_btn.clicked.connect(self._reset_recommendation_defaults)
        reset_row.addStretch()
        reset_row.addWidget(self._rec_reset_btn)
        layout.addLayout(reset_row)

        layout.addStretch()
        return tab

    def _on_rec_mix_auto_toggled(self, checked: bool) -> None:
        """Automatic owns the split — the manual percentage is inert while it is on."""
        self._rec_mix_spin.setEnabled(not checked)
        self._rec_mix_ratio_label.setVisible(not checked)

    def _on_rec_mix_value_changed(self, value: int) -> None:
        self._rec_mix_ratio_label.setText(f"({format_media_share(value / 100.0)} movies : series)")

    def _reset_recommendation_defaults(self) -> None:
        """Restore every Recommendations dial to the engine default (mix included)."""
        defaults = RecScoringSettings()
        self._rec_mix_auto_check.setChecked(True)
        self._rec_mix_spin.setValue(50)
        self._rec_genre_spin.setValue(defaults.genre_weight)
        self._rec_director_spin.setValue(defaults.director_weight)
        self._rec_actor_spin.setValue(defaults.actor_weight)
        self._rec_keyword_spin.setValue(defaults.keyword_weight)
        self._rec_actor_support_spin.setValue(defaults.actor_min_support)
        self._rec_diversity_spin.setValue(defaults.people_diversity_decay)
        self._rec_impression_spin.setValue(int(round(defaults.impression_decay * 100)))
        self._rec_liked_cap_spin.setValue(defaults.liked_cap)

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
        self._tmdb_key_input.setClearButtonEnabled(True)
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
        self._tmdb_lang_input.setClearButtonEnabled(True)
        self._tmdb_lang_input.setPlaceholderText("en-US")
        self._tmdb_lang_input.setMaxLength(10)
        tmdb_form.addRow("Language:", self._tmdb_lang_input)

        layout.addWidget(tmdb_group)

        omdb_group = QGroupBox("OMDb")
        omdb_form = QFormLayout(omdb_group)
        omdb_form.setSpacing(8)

        omdb_key_row = QHBoxLayout()
        self._omdb_key_input = QLineEdit()
        self._omdb_key_input.setClearButtonEnabled(True)
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

        epg_group = QGroupBox("EPG")
        epg_form = QFormLayout(epg_group)
        epg_form.setSpacing(8)

        self._epg_interval_combo = QComboBox()
        for value, label in EPG_INTERVAL_CHOICES:
            self._epg_interval_combo.addItem(label, value)
        self._epg_interval_combo.setToolTip(
            "Default EPG guide refresh frequency for all providers. "
            "Individual providers can override this in their editor. "
            "'Auto' (the default) self-tunes: it refreshes at half the guide depth, "
            "clamped to 6 hours – 7 days, so there is always headroom. "
            "'Only when data is stale' waits until the guide has fully expired before re-fetching."
        )
        epg_form.addRow("EPG refresh:", self._epg_interval_combo)

        self._epg_hide_older_spin = QSpinBox()
        self._epg_hide_older_spin.setRange(0, 168)  # 0 = no extra back-browse … 7 days
        self._epg_hide_older_spin.setSuffix(" h")
        self._epg_hide_older_spin.setToolTip(
            "Browse opens at 'now' (currently-airing + upcoming) and its timeline\n"
            "reaches back to the start of everything on right now. This setting lets\n"
            "you scrub FURTHER back: drag the handle to browse up to this many hours\n"
            "into the past. 0 (the default) keeps the timeline at the oldest show\n"
            "currently airing — no further back."
        )
        epg_form.addRow("Allow browsing back:", self._epg_hide_older_spin)

        self._epg_scrubber_increment_combo = QComboBox()
        for _mins in EPG_SCRUBBER_INCREMENTS:
            self._epg_scrubber_increment_combo.addItem(f"{_mins} minutes", _mins)
        self._epg_scrubber_increment_combo.setToolTip(
            "Granularity of the Browse timeline scrubber. Dragging the handle snaps to "
            "this interval (and each scroll step of the handle is one interval)."
        )
        epg_form.addRow("Scrubber snap:", self._epg_scrubber_increment_combo)

        self._epg_notify_minutes_spin = QSpinBox()
        self._epg_notify_minutes_spin.setRange(5, 120)
        self._epg_notify_minutes_spin.setSuffix(" min")
        self._epg_notify_minutes_spin.setToolTip(
            "How many minutes before a Watchlist programme starts MetaTV shows a "
            "notification toast."
        )
        epg_form.addRow("Notify before show:", self._epg_notify_minutes_spin)

        self._epg_auto_refresh_check = QCheckBox("Auto-refresh guides on launch and interval")
        self._epg_auto_refresh_check.setToolTip(
            "When on, MetaTV automatically fetches new EPG guide data on launch and "
            "at each source's refresh interval. Turn off to only refresh EPG "
            "manually (the Refresh button on the EPG screen still works)."
        )
        epg_form.addRow("", self._epg_auto_refresh_check)

        layout.addWidget(epg_group)

        layout.addStretch()
        return tab

    def _build_interface_tab(self) -> QWidget:
        """Build the Interface tab containing Search and Sidebar settings."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(16)
        layout.setContentsMargins(12, 12, 12, 12)

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

        channel_list_group = QGroupBox("Channel List")
        channel_list_form = QFormLayout(channel_list_group)
        channel_list_form.setSpacing(8)

        self._channel_density_combo = QComboBox()
        for label, value in _CHANNEL_DENSITY_CHOICES:
            self._channel_density_combo.addItem(label, value)
        self._channel_density_combo.setToolTip(
            "Comfy shows two lines per row (title + a badge row of language/\n"
            "quality/category). Compact fits everything on one line. Applies\n"
            "immediately when you click OK or Apply."
        )
        channel_list_form.addRow("Row density:", self._channel_density_combo)

        layout.addWidget(channel_list_group)

        sources_group = QGroupBox("Sources")
        sources_form = QFormLayout(sources_group)
        sources_form.setSpacing(8)

        self._refresh_all_inactive_check = QCheckBox(
            "Refresh inactive sources when refreshing all"
        )
        self._refresh_all_inactive_check.setToolTip(
            "When off, 'Refresh All' skips sources you've disabled. "
            "Refreshing a single source still works."
        )
        sources_form.addRow("", self._refresh_all_inactive_check)

        layout.addWidget(sources_group)

        updates_group = QGroupBox("Updates")
        updates_layout = QVBoxLayout(updates_group)
        updates_layout.setSpacing(8)

        self._update_check_enabled_check = QCheckBox("Automatically check for updates")
        self._update_check_enabled_check.setToolTip(
            "When on, the packaged app checks GitHub for a newer release on startup\n"
            "(at most once a day) and offers to download it. Running from source is\n"
            "never auto-checked — use the button below to check on demand."
        )
        updates_layout.addWidget(self._update_check_enabled_check)

        check_now_row = QHBoxLayout()
        self._check_updates_btn = QPushButton("Check for updates now")
        self._check_updates_btn.setToolTip("Check GitHub Releases for a newer version right now.")
        self._check_updates_btn.clicked.connect(self.check_updates_requested.emit)
        check_now_row.addWidget(self._check_updates_btn)
        check_now_row.addStretch()
        updates_layout.addLayout(check_now_row)

        layout.addWidget(updates_group)

        sidebar_group = QGroupBox("Sidebar")
        sidebar_layout = QVBoxLayout(sidebar_group)
        sidebar_layout.setSpacing(10)

        hint = QLabel(
            "Check sections to show them. Use the arrows to reorder.\n"
            "All changes apply immediately when you click OK or Apply."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {_theme.COLOR_MUTED}; font-size: {_theme.FONT_MD};")
        sidebar_layout.addWidget(hint)

        self._sidebar_list = QListWidget()
        self._sidebar_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self._sidebar_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._sidebar_list.setFixedHeight(200)
        sidebar_layout.addWidget(self._sidebar_list)

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
        sidebar_layout.addLayout(arrow_row)

        layout.addWidget(sidebar_group)

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

        # Interaction
        resume_mode = getattr(c, "playback_resume_mode", "resume")
        resume_idx = self._resume_mode_combo.findData(resume_mode)
        self._resume_mode_combo.setCurrentIndex(
            resume_idx if resume_idx >= 0 else self._resume_mode_combo.findData("resume")
        )

        mc_action = getattr(c, "middle_click_action", DEFAULT_MIDDLE_CLICK_ACTION)
        mc_idx = self._middle_click_combo.findData(mc_action)
        self._middle_click_combo.setCurrentIndex(
            mc_idx if mc_idx >= 0
            else self._middle_click_combo.findData(DEFAULT_MIDDLE_CLICK_ACTION)
        )

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
        self._recheck_failed_on_refresh_check.setChecked(
            getattr(c, "recheck_failed_on_refresh", True)
        )

        buf_idx = self._buffer_combo.findData(c.buffer_profile)
        self._buffer_combo.setCurrentIndex(buf_idx if buf_idx >= 0 else self._buffer_combo.findData("modest"))

        self._user_agent_view.setText(stream_user_agent())

        self._mpv_args_input.setText(" ".join(c.mpv_extra_args))
        self._prebuffer_check.setChecked(getattr(c, "prebuffer_before_play", False))
        self._prebuffer_wait_spin.setValue(getattr(c, "prebuffer_wait_secs", 10))
        self._override_all_check.setChecked(getattr(c, "mpv_args_override_all", False))
        self._split_check.setChecked(getattr(c, "split_streams_by_source", False))

        # Recommendations — every dial falls back to the engine's own default.
        rec = RecScoringSettings.from_config(c)
        saved_mix = getattr(c, "rec_media_mix", None)
        for widget, value in (
            (self._rec_mix_auto_check, saved_mix is None),
            (self._rec_mix_spin, 50 if saved_mix is None else int(round(float(saved_mix) * 100))),
            (self._rec_genre_spin, rec.genre_weight),
            (self._rec_director_spin, rec.director_weight),
            (self._rec_actor_spin, rec.actor_weight),
            (self._rec_keyword_spin, rec.keyword_weight),
            (self._rec_actor_support_spin, rec.actor_min_support),
            (self._rec_diversity_spin, rec.people_diversity_decay),
            (self._rec_impression_spin, int(round(rec.impression_decay * 100))),
            (self._rec_liked_cap_spin, rec.liked_cap),
        ):
            widget.blockSignals(True)
            if isinstance(widget, QCheckBox):
                widget.setChecked(value)
            else:
                widget.setValue(value)
            widget.blockSignals(False)
        # Signals were blocked during the restore, so sync the dependent state by hand.
        self._on_rec_mix_auto_toggled(self._rec_mix_auto_check.isChecked())
        self._on_rec_mix_value_changed(self._rec_mix_spin.value())

        # Search
        self._remember_search_check.blockSignals(True)
        self._remember_search_check.setChecked(getattr(c, "remember_search", True))
        self._remember_search_check.blockSignals(False)

        # Channel List
        self._channel_density_combo.blockSignals(True)
        _load_channel_density(self._channel_density_combo, c)
        self._channel_density_combo.blockSignals(False)

        # Sources
        self._refresh_all_inactive_check.blockSignals(True)
        self._refresh_all_inactive_check.setChecked(
            getattr(c, "refresh_all_includes_inactive", False)
        )
        self._refresh_all_inactive_check.blockSignals(False)

        # Updates
        self._update_check_enabled_check.blockSignals(True)
        self._update_check_enabled_check.setChecked(
            getattr(c, "update_check_enabled", True)
        )
        self._update_check_enabled_check.blockSignals(False)

        # EPG
        epg_idx = self._epg_interval_combo.findData(c.epg_default_refresh_interval)
        self._epg_interval_combo.setCurrentIndex(epg_idx if epg_idx >= 0 else 0)
        self._epg_hide_older_spin.setValue(
            getattr(c, "epg_browse_hide_older_than_hours", 0)
        )
        scrub_inc = getattr(c, "epg_scrubber_increment_minutes", 30)
        scrub_idx = self._epg_scrubber_increment_combo.findData(scrub_inc)
        if scrub_idx < 0:
            scrub_idx = self._epg_scrubber_increment_combo.findData(30)
        self._epg_scrubber_increment_combo.setCurrentIndex(max(scrub_idx, 0))
        self._epg_notify_minutes_spin.setValue(
            getattr(c, "epg_notification_minutes_before", 15)
        )
        self._epg_auto_refresh_check.setChecked(
            getattr(c, "epg_auto_refresh", True)
        )

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
        c.recheck_failed_on_refresh = self._recheck_failed_on_refresh_check.isChecked()
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

        # Interaction
        c.playback_resume_mode = self._resume_mode_combo.currentData() or "resume"
        c.middle_click_action = (
            self._middle_click_combo.currentData() or DEFAULT_MIDDLE_CLICK_ACTION
        )

        # Recommendations — a dial left at its default is stored as None so it keeps
        # tracking the engine default instead of freezing today's number.
        defaults = RecScoringSettings()
        c.rec_media_mix = (
            None if self._rec_mix_auto_check.isChecked()
            else self._rec_mix_spin.value() / 100.0
        )
        c.rec_weight_genre = _dial_or_none(self._rec_genre_spin.value(), defaults.genre_weight)
        c.rec_weight_director = _dial_or_none(
            self._rec_director_spin.value(), defaults.director_weight)
        c.rec_weight_actor = _dial_or_none(self._rec_actor_spin.value(), defaults.actor_weight)
        c.rec_weight_keyword = _dial_or_none(
            self._rec_keyword_spin.value(), defaults.keyword_weight)
        c.rec_actor_min_support = _dial_or_none(
            self._rec_actor_support_spin.value(), defaults.actor_min_support)
        c.rec_people_diversity_decay = _dial_or_none(
            self._rec_diversity_spin.value(), defaults.people_diversity_decay)
        c.rec_impression_decay = _dial_or_none(
            self._rec_impression_spin.value() / 100.0, defaults.impression_decay)
        c.rec_liked_cap = _dial_or_none(self._rec_liked_cap_spin.value(), defaults.liked_cap)

        # Search
        c.remember_search = self._remember_search_check.isChecked()

        # Channel List
        _save_channel_density(self._channel_density_combo, c)

        # Sources
        c.refresh_all_includes_inactive = self._refresh_all_inactive_check.isChecked()

        # Updates
        c.update_check_enabled = self._update_check_enabled_check.isChecked()

        # EPG
        epg_val = self._epg_interval_combo.currentData()
        if epg_val:
            c.epg_default_refresh_interval = epg_val
        c.epg_browse_hide_older_than_hours = self._epg_hide_older_spin.value()
        scrub_inc_val = self._epg_scrubber_increment_combo.currentData()
        if scrub_inc_val:
            c.epg_scrubber_increment_minutes = scrub_inc_val
        c.epg_notification_minutes_before = self._epg_notify_minutes_spin.value()
        c.epg_auto_refresh = self._epg_auto_refresh_check.isChecked()

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
