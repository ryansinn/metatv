"""Settings dialog: three-panel layout — left-nav sections, center controls, right help."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QCheckBox, QComboBox, QDialogButtonBox, QFormLayout,
    QListWidgetItem,
)
from loguru import logger

from metatv.core.config import Config
from metatv.core.http_headers import stream_user_agent
from metatv.core.preference_engine import RecScoringSettings
from metatv.gui.middle_click_actions import DEFAULT_MIDDLE_CLICK_ACTION
from metatv.gui.settings_dialog_tabs import SettingsTabsMixin
from metatv.gui.three_panel_section_nav import ThreePanelSectionNav

_SIDEBAR_SECTION_LABELS: dict[str, str] = {
    "alerts":      "Watch Alerts",
    "downloads":   "Downloads",
    "recordings":  "Recordings",
    "recommended": "Recommended",
    "queue":       "Watch Queue",
    "favorites":   "Favorites",
    "history":     "History",
    # "sources" deliberately absent (Wave 6) — Sources left the reorderable
    # sidebar section stack for the always-visible status strip + Sources
    # manager view; it can no longer be reordered/hidden here.
}
_ALL_SIDEBAR_SECTIONS = list(_SIDEBAR_SECTION_LABELS.keys())




def _fit_list_to_rows(widget) -> None:
    """Shrink a fixed-length list to the rows it actually holds.

    The sidebar-section list carried ``setFixedHeight(200)``, roughly double
    what it needs: the section set is a fixed five, and the comment beside it
    records that "sources" LEFT the list in Wave 6 — the constant outlived its
    content and left a ~110px void under the last row.

    Sized from the rows rather than re-guessed, so adding or removing a section
    can never reopen the gap. No-ops on an empty list, and adds the frame so
    the last row is never clipped.
    """
    count = widget.count()
    if not count:
        return
    row_h = widget.sizeHintForRow(0)
    if row_h <= 0:
        return
    frame = widget.frameWidth() * 2
    widget.setFixedHeight(row_h * count + frame + 2)


def _align_label_columns(page) -> None:
    """Give every form on ONE settings page the same label-column width.

    Qt sizes each ``QFormLayout``'s label column independently, and a page
    holds several. On Interface that meant "Theme:" let its combo start at
    x=246 while "Platform names:" in the very next group pushed its combo to
    x=297 — the control column wandered as you read down, with no rule behind
    where it landed.

    Per PAGE, not per dialog. Aligning across all thirteen forms works, but the
    widest label in the whole dialog is Playback\'s "Mark as partially-watched
    after:", which would impose a 178px column on Interface for the sake of
    matching a page you cannot see at the same time — correct alignment, real
    wasted space. Sections are separate views; alignment is a within-view
    property.

    The width is MEASURED, not a constant, so the column stays right when a
    label is reworded or translated and there is no magic number to drift.

    Called once per page rather than threaded through ~40 ``addRow`` sites —
    one seam, and a new form aligns without anyone remembering to opt in.
    """
    forms = page.findChildren(QFormLayout)
    labels = [
        item.widget()
        for form in forms
        for i in range(form.rowCount())
        for item in [form.itemAt(i, QFormLayout.ItemRole.LabelRole)]
        if item is not None and item.widget() is not None
    ]
    if not labels:
        return
    widest = max(label.sizeHint().width() for label in labels)
    for label in labels:
        label.setMinimumWidth(widest)


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


def _load_sidebar_density(combo: QComboBox, config) -> None:
    """Select ``config.sidebar_row_density`` in ``combo`` (falls back to compact).

    Mirrors :func:`_load_channel_density` — factored out so the round-trip is
    testable against a bare ``QComboBox`` + a minimal fake config.
    """
    density = getattr(config, "sidebar_row_density", "compact")
    idx = combo.findData(density)
    combo.setCurrentIndex(idx if idx >= 0 else combo.findData("compact"))


def _save_sidebar_density(combo: QComboBox, config) -> None:
    """Write the selected density back to ``config.sidebar_row_density``."""
    config.sidebar_row_density = combo.currentData() or "compact"


def _load_platform_name_style(combo: QComboBox, config) -> None:
    """Select ``config.platform_name_style`` in ``combo`` (falls back to "auto").

    Mirrors :func:`_load_channel_density` — factored out so the round-trip is
    testable against a bare ``QComboBox`` + a minimal fake config.
    """
    style = getattr(config, "platform_name_style", "auto")
    idx = combo.findData(style)
    combo.setCurrentIndex(idx if idx >= 0 else combo.findData("auto"))


def _save_platform_name_style(combo: QComboBox, config) -> None:
    """Write the selected style back to ``config.platform_name_style``."""
    config.platform_name_style = combo.currentData() or "auto"


def _load_theme_combo(combo: QComboBox, config) -> None:
    """Select ``config.theme_name`` in ``combo`` (falls back to Midnight).

    Factored out like ``_load_channel_density`` so the round-trip is testable
    against a bare ``QComboBox`` + a minimal fake config.
    """
    from metatv.gui import theme_palettes
    name = getattr(config, "theme_name", theme_palettes.DEFAULT_PALETTE)
    idx = combo.findData(name)
    combo.setCurrentIndex(idx if idx >= 0 else combo.findData(theme_palettes.DEFAULT_PALETTE))


def _save_theme_combo(combo: QComboBox, config) -> None:
    """Write the selected palette name back to ``config.theme_name``."""
    from metatv.gui import theme_palettes
    config.theme_name = combo.currentData() or theme_palettes.DEFAULT_PALETTE

# Left-nav sections, in display order — id + label, unchanged from the old
# QTabWidget's five tab names/order so the ``settings:<tab>`` deep link and
# shipped What's New entries keep matching. id is also the _SECTION_HELP key.
#: ``(section_id, label, builder_method_name)``, in display order.
#:
#: One list, not two zipped by position. It WAS two — ``_SECTIONS`` beside a
#: parallel ``builders`` tuple in ``_setup_ui`` — which pairs correctly only
#: while both stay the same length and the same order. Adding a page to one
#: and not the other does not fail; it silently renders every later page under
#: the wrong label and the wrong help text.
_SECTIONS: tuple[tuple[str, str, str], ...] = (
    ("playback", "Playback", "_build_playback_tab"),
    ("interaction", "Interaction", "_build_interaction_tab"),
    ("content", "Content", "_build_content_tab"),
    ("recommendations", "Recommendations", "_build_recommendations_tab"),
    ("metadata", "Metadata & API Keys", "_build_metadata_tab"),
    ("interface", "Interface", "_build_interface_tab"),
    ("sidebar", "Sidebar", "_build_sidebar_tab"),
    ("alerts", "Watch Alerts", "_build_alerts_tab"),
)

# One short, plainly-written paragraph per section for the right-hand help
# panel: what it controls + the one thing worth knowing. Trivially editable.
_SECTION_HELP: dict[str, str] = {
    "playback": "Which player MetaTV uses, how aggressively it buffers, and when a movie "
                "or episode counts as \"watched\". If streams stutter or drop, the "
                "Buffering profile here is the first thing to try.",
    "interaction": "What a double-click and a middle-click do on a channel row. These are "
                   "shortcuts, not required setup — right-click any movie for a one-time "
                   "override without changing either default.",
    "content": "What the library is allowed to show you. Adult content is hidden by "
               "default; this is where that is changed. While it is hidden, a category "
               "made up entirely of flagged channels will look empty — the channel list "
               "says when that is why.",
    "recommendations": "Steering dials for the Recommendations engine: the movie/series "
                        "mix and how much weight genre, director, cast, and keywords "
                        "carry. Every dial ships at a sane default, so an untouched tab "
                        "is fine.",
    "metadata": "TMDb/OMDb API keys, how long fetched metadata is cached, and EPG guide "
                "refresh/notification timing. A TMDb key unlocks posters, cast, and plot "
                "details across your whole library.",
    "interface": "Search memory, how the channel list looks, source-refresh behavior "
                 "and update checks. Which sidebar sections show, and Watch Alerts, "
                 "now have pages of their own below.",
    "sidebar": "Which sections appear down the left, and in what order. Changes take "
               "effect as soon as you click OK or Apply. Hiding a section does not "
               "lose anything — it stops being built, and comes back exactly as it "
               "was when you show it again.",
    "alerts": "What the Watch Alerts section shows, and how often MetaTV re-checks "
              "your watch list for new episodes. That check costs one connection to "
              "the source while it runs, so on an account limited to a single "
              "connection it competes with playback — which is why it defaults to "
              "once a day rather than hourly.",
}


def _dial_or_none(value: float, default: float):
    """Return ``None`` when a dial still sits on its default, else the value.

    Storing ``None`` for an untouched dial keeps config free of numbers the user
    never chose — and lets a future change to the shipped default reach everyone
    who never overrode it.
    """
    return None if abs(float(value) - float(default)) < 1e-9 else value


class SettingsDialog(SettingsTabsMixin, QDialog):
    """Modal settings dialog: left-nav sections, center controls, right contextual help.

    Five sections — Playback, Interaction, Recommendations, Metadata & API Keys,
    Interface — same labels/order as the old tab bar; each section's widgets are
    built by the same ``_build_*_tab()`` methods as before (unchanged, now living
    in :class:`~metatv.gui.settings_dialog_tabs.SettingsTabsMixin`), hosted as
    pages of a :class:`~metatv.gui.three_panel_section_nav.ThreePanelSectionNav`
    instead of ``QTabWidget`` tabs.
    """

    # Emitted by BOTH Apply and OK. It used to be Apply-only, on the theory
    # that OK closes so the host can just re-apply afterwards — and the host
    # did, from a hand-written list that named three of the five connected
    # handlers. Row density, poster thumbnails, platform-name style and
    # collapse-variants were all saved by OK and then never applied, so the
    # setting looked dead until something else re-rendered the list.
    settings_applied = pyqtSignal()
    check_updates_requested = pyqtSignal()  # "Check for updates now" clicked (Interface → Updates)
    # Metadata tab TMDb/OMDb "Test" buttons: (provider_name, (success, message)) —
    # emitted by the executor worker (metatv/gui/settings_dialog_tabs.py), the
    # connected slot is the only code that touches the result-badge widgets
    # (Qt threading rule — signals only, main thread renders).
    _provider_test_ready = pyqtSignal(str, object)

    def __init__(self, config: Config, parent=None, executor=None):
        """Construct the dialog.

        Args:
            config: App config (read/written in place by ``_load_values``/``_save_values``).
            parent: Parent widget.
            executor: Shared ``ThreadPoolExecutor`` (``MainWindow.executor``) used by
                the TMDb/OMDb "Test" buttons (Metadata tab) to run
                ``test_connection()`` off the UI thread. ``None`` disables the Test
                buttons (they show a tooltip explaining why) rather than crashing —
                covers callers/tests that construct the dialog without one.
        """
        super().__init__(parent)
        self.config = config
        self._executor = executor
        self.setWindowTitle("Settings")
        self.setMinimumWidth(900)
        self.setModal(True)
        self._setup_ui()
        self._provider_test_ready.connect(self._on_provider_test_ready)
        self._load_values()
        self._restore_dialog_geometry()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self._nav = ThreePanelSectionNav(_SECTION_HELP)
        for section_id, label, builder_name in _SECTIONS:
            page = getattr(self, builder_name)()
            _align_label_columns(page)
            self._nav.add_section(section_id, label, page)
        layout.addWidget(self._nav, 1)

        # Restore the last-selected section with signals blocked so it doesn't
        # fire _on_section_changed (CLAUDE.md: signal blocking during UI state
        # restoration); connect() happens in a separate pass right after.
        saved_row = getattr(self.config, "settings_dialog_section", 0)
        initial_row = saved_row if 0 <= saved_row < self._nav.count() else 0
        self._nav.set_current_row(initial_row, block_signal=True)
        self._nav.sectionChanged.connect(self._on_section_changed)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel |
            QDialogButtonBox.StandardButton.Apply
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._apply)
        layout.addWidget(buttons)

    def _on_section_changed(self, row: int) -> None:
        """Section choice is UI state (like a splitter position), not a Settings
        value, so it's persisted immediately rather than gated behind Apply/OK."""
        self.config.settings_dialog_section = row
        self.config.save()

    def select_section_by_label(self, label_substring: str) -> bool:
        """Select the section whose label contains *label_substring* (case-insensitive).

        Delegates to ``ThreePanelSectionNav.select_by_label`` — kept as a
        ``SettingsDialog`` method (rather than requiring callers to reach into
        ``self._nav``) so the ``settings:<tab>`` deep link
        (``MainWindow.open_settings``) has one stable call site across the
        QTabWidget → left-nav rework.
        """
        return self._nav.select_by_label(label_substring)

    def _restore_dialog_geometry(self) -> None:
        """Resize to the last-persisted size (or the shipped default)."""
        width = getattr(self.config, "settings_dialog_width", 900)
        height = getattr(self.config, "settings_dialog_height", 600)
        self.resize(max(int(width), self.minimumWidth()), max(int(height), 1))

    def _persist_dialog_state(self) -> None:
        """Write current size + selected section to config (called on any close)."""
        self.config.settings_dialog_width = self.width()
        self.config.settings_dialog_height = self.height()
        row = self._nav.current_row()
        if row >= 0:
            self.config.settings_dialog_section = row
        self.config.save()

    def done(self, result: int) -> None:
        """Persist ephemeral dialog UI state (size + section) on any close path —
        OK, Cancel, or the window's close button — independent of whether Settings
        values themselves were saved via Apply/OK."""
        if hasattr(self, "_nav"):
            self._persist_dialog_state()
        super().done(result)

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
        adult_idx = self._adult_mode_combo.findData(
            getattr(self.config, "filter_adult_mode", "hide")
        )
        self._adult_mode_combo.setCurrentIndex(
            adult_idx if adult_idx >= 0 else self._adult_mode_combo.findData("hide")
        )

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
        _fit_list_to_rows(self._sidebar_list)

        # Appearance
        self._theme_combo.blockSignals(True)
        _load_theme_combo(self._theme_combo, c)
        self._theme_combo.blockSignals(False)

        # Channel List
        self._channel_density_combo.blockSignals(True)
        _load_channel_density(self._channel_density_combo, c)
        self._channel_density_combo.blockSignals(False)
        self._sidebar_density_combo.blockSignals(True)
        _load_sidebar_density(self._sidebar_density_combo, c)
        self._sidebar_density_combo.blockSignals(False)
        self._show_more_row_check.setChecked(
            getattr(c, "sidebar_show_more_row", False)
        )
        self._alerts_show_idle_check.setChecked(
            getattr(c, "alerts_show_idle_items", False)
        )
        self._series_interval_spin.setValue(
            int(getattr(c, "series_monitor_interval_minutes", 60) or 0)
        )
        self._platform_name_style_combo.blockSignals(True)
        _load_platform_name_style(self._platform_name_style_combo, c)
        self._platform_name_style_combo.blockSignals(False)
        self._channel_thumbnails_check.blockSignals(True)
        self._channel_thumbnails_check.setChecked(
            getattr(c, "channel_list_thumbnails", True)
        )
        self._channel_thumbnails_check.blockSignals(False)
        self._collapse_variants_check.blockSignals(True)
        self._collapse_variants_check.setChecked(
            getattr(c, "collapse_variants_in_list", False)
        )
        self._collapse_variants_check.blockSignals(False)
        self._menu_auto_hide_check.blockSignals(True)
        self._menu_auto_hide_check.setChecked(
            getattr(c, "menu_bar_auto_hide", False)
        )
        self._menu_auto_hide_check.blockSignals(False)

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
        c.filter_adult_mode = self._adult_mode_combo.currentData() or "hide"
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
        # Appearance
        _save_theme_combo(self._theme_combo, c)

        # Channel List
        _save_channel_density(self._channel_density_combo, c)
        _save_sidebar_density(self._sidebar_density_combo, c)
        c.sidebar_show_more_row = self._show_more_row_check.isChecked()
        # The same key Manage Watch Alerts writes, so the two switches are one
        # setting seen from two places rather than two that can disagree.
        c.alerts_show_idle_items = self._alerts_show_idle_check.isChecked()
        # APPLIED by the host on settings_applied: MainWindow re-arms the timer
        # via SeriesMonitorManager.start_scheduler(), which re-reads this value.
        # Written here only — a setting that saves without applying is the
        # failure this codebase has already had (see the Settings OK note).
        c.series_monitor_interval_minutes = self._series_interval_spin.value()
        _save_platform_name_style(self._platform_name_style_combo, c)
        c.channel_list_thumbnails = self._channel_thumbnails_check.isChecked()
        # Written like every other setting; APPLIED by the host on
        # settings_applied (MainWindow connects apply_menu_bar_auto_hide).
        # Reaching for self.parent() here instead would both bypass that
        # established seam and break every test that builds this dialog via
        # __new__ — PyQt raises on any QWidget method there.
        c.menu_bar_auto_hide = self._menu_auto_hide_check.isChecked()

        c.sidebar_sections = new_order
        c.sidebar_visible_sections = new_visible

        c.save()
        logger.info("Settings saved")

    def _apply(self):
        self._save_values()
        self.settings_applied.emit()

    def _accept(self):
        """OK = Apply + close. Anything less makes OK the weaker button."""
        self._apply()
        self.accept()
