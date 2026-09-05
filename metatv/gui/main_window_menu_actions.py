"""DEBT-1a — the menu bar and every handler it wires, moved verbatim.

``_MenuActionsMixin`` is mixed into :class:`~metatv.gui.main_window.MainWindow`
(main_window.py's class bases), same shape as every other ``main_window_*.py``
mixin: its methods read/write ``self.*`` attributes MainWindow's
``__init__``/``setup_ui`` already establish (``self.config``, ``self.executor``,
``self.status_bar``, ``self.notification_manager``, ``self._tools_menu``, the
per-action attributes ``create_menu_bar`` itself assigns).

``main_window.py`` is PINNED by the code-health ratchet and is the one file
that grows at every measurement — this is a pure extraction, not a rewrite.
Every method here is the SAME body, docstring and rationale comment it had in
``main_window.py``; nothing was reworded, reordered within a function, or
changed in behaviour.

Two things this mixin does NOT own, on purpose, even though it calls them:
``_sync_layout_menu`` (re-ticks the Layout menu from live splitter state) and
``_whats_new_unseen`` (the testable seam behind ``maybe_show_whats_new``) both
stayed on ``MainWindow`` itself — they were not in the moved set, and a mixin
method calling back into a sibling mixin or the host class is the same
cross-mixin pattern ``main_window_overlays.py``'s ``_OverlaysMixin`` already
uses (e.g. ``self.play_channel_by_id``). ``self.*`` attribute lookup does not
care which class in the MRO defines the name.
"""

from __future__ import annotations

from loguru import logger
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QAction, QKeySequence

from metatv.core.config import dev_mode_enabled as _dev_mode_enabled
from metatv.gui import deferred_config_save as _cfgsave
from metatv.gui import icons as _icons
from metatv.gui import settings_apply as _settings_apply
from metatv.gui.menu_bar_reveal import auto_hide_supported as menu_bar_auto_hide_supported
from metatv.gui.whats_new_dialog import WhatsNewDialog
import metatv.whats_new as _whats_new

# Auto-dialog backlog cap — above this many unseen entries, show only the
# newest release's entries (see maybe_show_whats_new).
_WHATS_NEW_AUTO_CAP = 25


class _MenuActionsMixin:
    """The menu bar (File/View/Style/Layout/Buffer/Tools/Help) and its handlers."""

    def create_menu_bar(self):
        """Create application menu bar"""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("&File")
        file_menu.addAction("&Add Source...", self.add_provider)
        file_menu.addSeparator()
        settings_action = QAction("&Settings", self)
        settings_action.setShortcut(QKeySequence("Ctrl+,"))
        settings_action.triggered.connect(self.open_settings)
        file_menu.addAction(settings_action)
        file_menu.addSeparator()
        file_menu.addAction("E&xit", self.close)
        
        # View menu
        view_menu = menubar.addMenu("&View")
        view_menu.addAction("&Refresh", self.refresh_channels)
        view_menu.addAction("&Operations", self.show_operations)

        # Style menu — look-and-feel without digging through Settings (owner
        # request). Both groups drive the SAME live-apply seams Settings uses
        # (apply_theme / _apply_channel_list_density), so the two surfaces can
        # never disagree; this is a shortcut to existing behaviour, not a
        # parallel implementation of it.
        self._build_style_menu(menubar)
        self._build_layout_menu(menubar)
        self._build_buffer_menu(menubar)
        
        # Tools menu
        tools_menu = self._tools_menu = menubar.addMenu("&Tools")
        # Stream-quality diagnosis of the SELECTED channel. It had its own
        # permanent button in the bottom bar, which put a niche action on
        # screen beside the primary navigation forever; the header's Tools
        # button opens this menu instead (R5).
        #
        # This sat under a SECOND entry called "Diagnostics" whose handler
        # logged one line and returned — two diagnostics items, one dead. The
        # dead one is gone; the real one carries the name, matching its dialog.
        diagnose_action = QAction(f"{_icons.diagnose_icon}  Stream &diagnostics", self)
        diagnose_action.setToolTip(
            "Measure the selected channel's stream: reachability, time to first "
            "byte, throughput, and whether a bigger buffer would help"
        )
        diagnose_action.triggered.connect(self.on_diagnose_clicked)
        tools_menu.addAction(diagnose_action)
        # "Global Exclusions", never "Filters" — the app's one name for this.
        # Its handler was a stub too, and had a LIVE trigger beyond the menu:
        # the details pane emits manage_filters_requested straight into it.
        exclusions_action = QAction(
            f"{_icons.global_exclusion_icon}  Global &Exclusions", self
        )
        exclusions_action.setToolTip(
            "Choose which prefixes, categories and keywords are hidden across "
            "the whole app"
        )
        exclusions_action.triggered.connect(self.manage_filters)
        tools_menu.addAction(exclusions_action)
        missing_tmdb_action = QAction(
            f"{_icons.missing_data_icon}  Missing TMDb Data", self
        )
        missing_tmdb_action.setToolTip(
            "Diagnose TMDb-id coverage and drive on-demand enrichment"
        )
        missing_tmdb_action.triggered.connect(self.enter_missing_tmdb_mode)
        tools_menu.addAction(missing_tmdb_action)
        reconnect_action = QAction(
            f"{_icons.reconnect_icon}  Reconnect Engaged Content", self
        )
        reconnect_action.setToolTip(
            "Recover favorites/history/queue rows stranded by a removed source "
            "onto a live copy"
        )
        reconnect_action.triggered.connect(self.enter_reconnect_engaged_mode)
        tools_menu.addAction(reconnect_action)
        metadata_enrich_action = QAction(
            f"{_icons.metadata_enrich_icon}  Background Metadata Enrichment", self
        )
        metadata_enrich_action.setToolTip(
            "View progress and start/pause/cancel the background metadata fill"
        )
        metadata_enrich_action.triggered.connect(self.enter_metadata_enrichment_mode)
        tools_menu.addAction(metadata_enrich_action)
        open_config_action = QAction(
            f"{_icons.config_folder_icon}  Open config folder", self
        )
        open_config_action.setToolTip(
            "Reveal the folder holding config.yaml and the logs, for support "
            "and manual edits"
        )
        open_config_action.triggered.connect(self.open_config_folder)
        tools_menu.addAction(open_config_action)
        log_viewer_action = QAction(
            f"{_icons.log_viewer_icon}  Log viewer", self
        )
        log_viewer_action.setToolTip(
            "Watch the log as it happens, in a window you can move aside — "
            "with save, filter and diagnostics for a bug report"
        )
        log_viewer_action.triggered.connect(self.show_log_viewer)
        tools_menu.addAction(log_viewer_action)
        clear_log_action = QAction(
            f"{_icons.clear_log_icon}  Clear log files", self
        )
        clear_log_action.setToolTip(
            "Delete every log file, rotated copies included, to reclaim disk"
        )
        clear_log_action.triggered.connect(self.clear_log_files)
        tools_menu.addAction(clear_log_action)

        # Help menu
        # The way BACK. The header's Tools button opens this same menu, so
        # this entry is reachable with the menu bar hidden — which is precisely
        # when someone needs it. Without it the only off-switch for auto-hide
        # would be behind the thing auto-hide just hid.
        tools_menu.addSeparator()
        self._menu_always_visible_action = QAction(
            "Menu &bar always visible", self, checkable=True
        )
        self._menu_always_visible_action.setToolTip(
            "When unticked, the menu bar hides until you press Alt. "
            "Untick only if you want the chrome gone — File, View, Layout, "
            "Style and Buffer all go behind that Alt press; the header's "
            "Tools button (this menu) stays reachable either way."
        )
        if not menu_bar_auto_hide_supported():
            self._menu_always_visible_action.setEnabled(False)
            self._menu_always_visible_action.setToolTip(
                "On macOS the menu bar is the system bar at the top of the "
                "screen, not part of this window — there is nothing to hide."
            )
        self._menu_always_visible_action.toggled.connect(
            lambda visible: self.set_menu_bar_auto_hide(not visible)
        )
        tools_menu.addAction(self._menu_always_visible_action)
        tools_menu.aboutToShow.connect(self.sync_menu_bar_actions)

        # Alt-to-reveal, if the user has asked for it. Applied here rather than
        # at the end of __init__ so the bar is never briefly visible first.
        self._alt_pressed_alone = False
        self.apply_menu_bar_auto_hide()
        self.sync_menu_bar_actions()

        help_menu = menubar.addMenu("&Help")
        whats_new_action = QAction(f"{_icons.whats_new_icon}  What's New", self)
        whats_new_action.setToolTip("See what changed in recent updates")
        whats_new_action.triggered.connect(self.show_whats_new)
        help_menu.addAction(whats_new_action)

        if _dev_mode_enabled():
            qa_action = QAction(f"{_icons.qa_checklist_icon}  Testing Checklist", self)
            qa_action.setToolTip("Open the dev QA testing checklist (METATV_DEV mode)")
            qa_action.triggered.connect(self._open_qa_checklist)
            help_menu.addAction(qa_action)

        help_menu.addSeparator()
        help_menu.addAction("&About", self.show_about)

    def show_test_notification(self):
        """Show a test notification (for development)"""
        notif_id = self.notification_manager.show_progress(
            title="Loading Example TV",
            total=150000
        )
        
        # Simulate progress
        progress = 0
        def update_progress():
            nonlocal progress
            progress += 5000
            self.notification_manager.update_progress(notif_id, progress, 150000)
            if progress >= 150000:
                self.notification_manager.complete_progress(
                    notif_id, 
                    "150,000 channels loaded"
                )
        
        timer = QTimer(self)
        timer.timeout.connect(update_progress)
        timer.start(500)

    def show_operations(self):
        """Show operations panel"""
        logger.info("Show operations panel")
    
    def show_log_viewer(self) -> None:
        """Open (or re-raise) the floating log window.

        One window, kept on the instance: opening it twice would attach a
        second loguru sink and show every line twice, and the second window
        would keep streaming after the first was closed.
        """
        from metatv.gui.log_viewer_window import LogViewerWindow

        existing = self.__dict__.get("_log_viewer")
        if existing is not None:
            try:
                existing.show()
                existing.raise_()
                existing.activateWindow()
                return
            except RuntimeError:  # silent: the previous window's C++ object is
                # gone (the user closed it and Qt collected it); fall through
                # and build a new one, which is what they asked for anyway.
                pass
        viewer = LogViewerWindow(self.config, self)
        self._log_viewer = viewer
        viewer.show()
        viewer.raise_()

    def clear_log_files(self) -> None:
        """Delete every log file after confirming, and report what was freed.

        Confirmed because it is not reversible and the logs are the evidence
        for whatever the user is about to report. Routed through the viewer
        module's helper so this and the viewer's own button cannot become two
        answers to "which files count as the log".
        """
        from PyQt6.QtWidgets import QMessageBox

        from metatv.core.log_paths import all_log_files
        from metatv.gui.log_viewer_window import clear_log_files

        files = all_log_files(self.config)
        if not files:
            self.status_bar.showMessage("No log files to clear", 4000)
            return
        total = 0
        for path in files:
            try:
                total += path.stat().st_size
            except OSError:  # silent: a file that vanished cannot be offered
                # for deletion, and excluding it from the total is correct.
                continue
        answer = QMessageBox.question(
            self,
            "Clear log files",
            f"Delete {len(files)} log file(s), freeing "
            f"{total / 1_048_576:.1f} MB?\n\n"
            "This cannot be undone. Save anything you still need first.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        removed, freed = clear_log_files(self.config)
        self.status_bar.showMessage(
            f"Cleared {removed} log file(s), freeing {freed / 1_048_576:.1f} MB",
            6000,
        )

    def open_config_folder(self) -> None:
        """Reveal the config directory in the system file manager.

        The folder, not ``config.yaml`` itself. Three reasons: a ``.yaml`` file
        has no registered handler on many systems, so opening it can silently do
        nothing or launch something unhelpful; the logs live in the same folder
        and someone fetching one usually needs the other; and revealing a
        directory cannot put an editor in front of a file the user did not mean
        to change.

        Uses ``QDesktopServices`` so each platform's own file manager opens —
        Finder, Explorer, or whatever the desktop registers.
        """
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices

        path = self.config.config_dir
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.exception("Could not create the config folder at {}", path)

        if QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            logger.info("Opened config folder: {}", path)
            return

        # No file manager, or the desktop refused. Say where it is rather than
        # failing silently — the path is the useful half of this action.
        logger.warning("Could not open a file manager for {}", path)
        self.notification_manager.show(
            f"Config folder: {path}",
            duration_ms=12000,
        )

    def open_settings(self, tab: str | None = None):
        """Open settings dialog.

        Args:
            tab: Optional tab label substring (case-insensitive). When given and
                matched, the dialog opens with that tab selected — used by QA
                deep-links (``settings:<tab>``).  Unmatched/None opens the first
                tab as before (backward-compatible).
        """
        from metatv.gui.settings_dialog import SettingsDialog
        dialog = SettingsDialog(self.config, self, executor=self.executor)
        # ONE slot, not eleven connections. The list itself lives in
        # gui/settings_apply.HANDLERS — same single enumeration, moved to where
        # it can be ordered, timed and guarded. It also coalesces the list
        # reload: two handlers called load_channels() independently, so one OK
        # re-ran the whole 785k-row filter twice.
        dialog.settings_applied.connect(lambda: _settings_apply.run(self))
        dialog.check_updates_requested.connect(self._manual_update_check)
        if tab:
            dialog.select_section_by_label(tab)
        dialog.exec()
        # NOTHING is re-run here. There used to be a hand-written tail repeating
        # some of the handlers above, because OK saved without emitting
        # settings_applied — and it listed three of the five, so OK silently
        # dropped row density, thumbnails, platform-name style and
        # collapse-variants. OK emits now, so the connections ARE the list;
        # re-running them here would only let the two drift apart again.

    def _apply_menu_bar_setting(self) -> None:
        """Settings changed the menu-bar option — apply it and re-tick Tools."""
        self.apply_menu_bar_auto_hide()
        self.sync_menu_bar_actions()

    def _build_layout_menu(self, menubar) -> None:
        """Build the Layout menu — which panels are on screen.

        Separate from Style because they answer different questions. Style is
        what things LOOK like (theme, density, posters); Layout is what is
        *present*. Keeping them apart is what makes either menu predictable —
        a user reaching for "hide the sidebar" should not have to consider
        whether that counts as styling.

        The filter-panel toggle moved here from Style for that reason: it is
        the third of the three panels, and grouping it with the other two beats
        having one panel toggle live somewhere else.

        Every entry drives the SAME path the panel's own control uses
        (``CollapsibleSplitter.collapse_panel``/``expand_panel``, and
        ``toggle_filters``), so a menu tick can never disagree with the screen.
        """
        layout_menu = menubar.addMenu("&Layout")
        layout_menu.aboutToShow.connect(self._sync_layout_menu)

        self._sidebar_visible_action = QAction("&Sidebar", self, checkable=True)
        self._sidebar_visible_action.setToolTip(
            "Show or hide the left sidebar. Its width is remembered."
        )
        self._sidebar_visible_action.triggered.connect(self._toggle_sidebar_from_menu)
        layout_menu.addAction(self._sidebar_visible_action)

        self._details_visible_action = QAction("&Details pane", self, checkable=True)
        self._details_visible_action.setToolTip(
            "Show or hide the details pane on the right. Its width is remembered."
        )
        self._details_visible_action.triggered.connect(self._toggle_details_from_menu)
        layout_menu.addAction(self._details_visible_action)

        self._filters_visible_action = QAction("&Filter panel", self, checkable=True)
        self._filters_visible_action.setToolTip(
            "Show or hide the filter panel beside the results list."
        )
        self._filters_visible_action.triggered.connect(self._toggle_filters_from_menu)
        layout_menu.addAction(self._filters_visible_action)

        layout_menu.addSeparator()
        self._filter_chips_action = QAction("Filters as &chips", self, checkable=True)
        self._filter_chips_action.setToolTip(
            "Show active filters as a line of removable chips above the results, "
            "opening the full panel on demand. Unticked, the Includes column is "
            "always present instead."
        )
        self._filter_chips_action.triggered.connect(self.toggle_filter_ui_mode)
        layout_menu.addAction(self._filter_chips_action)

        self._sync_layout_menu()

    def _toggle_sidebar_from_menu(self) -> None:
        """Collapse or restore the sidebar from the Layout menu."""
        self._toggle_main_panel(self._SIDEBAR_PANEL, self._sidebar_visible_action)

    def _toggle_details_from_menu(self) -> None:
        """Collapse or restore the details pane from the Layout menu."""
        self._toggle_main_panel(self._DETAILS_PANEL, self._details_visible_action)

    def _toggle_main_panel(self, index: int, action) -> None:
        """Toggle one ``main_splitter`` panel and re-sync *action* from reality.

        Args:
            index: Panel index in ``main_splitter``.
            action: The menu entry whose tick mirrors that panel.
        """
        splitter = self.__dict__.get("main_splitter")
        if splitter is None:
            return
        splitter.toggle_panel(index)
        # Re-read rather than assume: expand_panel restores a remembered size
        # and a minimum width can clamp the result, so the splitter is the only
        # authority on what actually happened.
        action.setChecked(not splitter.is_panel_collapsed(index))
        self.save_splitter_sizes()

    def _set_theme_from_menu(self, name: str) -> None:
        """Apply and persist a theme chosen from the Style menu.

        Routes through the same ``refresh_theme()`` the Settings dialog uses
        rather than calling ``apply_theme`` directly — that is where the
        registered-style re-apply and widget repolish happen (#277/#278), and
        skipping it would reproduce the half-switched rendering those fixed.

        Args:
            name: A palette name from ``theme.available_themes()``.
        """
        if getattr(self.config, "theme_name", None) == name:
            return
        self.config.theme_name = name
        _cfgsave.save_soon(self)
        self.refresh_theme()

    def _build_buffer_menu(self, menubar) -> None:
        """Build the Buffer menu — how much mpv reads ahead while playing.

        Its own top-level menu rather than a Style entry, deliberately: Style is
        appearance, and this is playback tuning with no visual result. It earns
        a menu because it is the setting you reach for WHILE a stream is
        stuttering, which is exactly when opening Settings is most annoying.

        Labels mirror Settings → Playback verbatim so the two read as one
        setting rather than two similar ones. The "deep" profile is deliberately
        absent — Settings exposes it through its own control, and a second
        entry point for it here would be a third way to say the same thing.

        Args:
            menubar: The window's ``QMenuBar``.
        """
        from PyQt6.QtGui import QActionGroup

        buffer_menu = menubar.addMenu("&Buffer")
        self._buffer_action_group = QActionGroup(self)
        self._buffer_action_group.setExclusive(True)
        current = getattr(self.config, "buffer_profile", "modest")
        for value, label in (
            ("reconnect_only", "&Reconnect only (no extra buffer)"),
            ("modest", "&Modest (~10s buffer)"),
            ("large", "&Large (~30s buffer)"),
            ("open_ended", "&Open-ended (disk-backed, max buffer)"),
        ):
            action = QAction(label, self, checkable=True)
            action.setChecked(value == current)
            # Says plainly that it is not retroactive — mpv flags are composed
            # when a stream launches, so the change lands on the NEXT play.
            action.setToolTip("Applies to the next stream you start")
            action.triggered.connect(lambda _c, v=value: self._set_buffer_from_menu(v))
            self._buffer_action_group.addAction(action)
            buffer_menu.addAction(action)
        buffer_menu.setToolTipsVisible(True)

    def _set_buffer_from_menu(self, value: str) -> None:
        """Persist a buffer profile chosen from the Buffer menu.

        No live re-apply: mpv's buffer flags are composed at launch
        (``MPVPlayer._compose_extra_args``), so this takes effect on the next
        stream. Restarting playback to apply it would be a destructive surprise
        from a menu click.

        Args:
            value: One of ``"reconnect_only"``/``"modest"``/``"large"``/
                ``"open_ended"``.
        """
        if getattr(self.config, "buffer_profile", None) == value:
            return
        self.config.buffer_profile = value
        _cfgsave.save_soon(self)
        self.status_bar.showMessage(
            "Buffer setting saved — applies to the next stream you start", 4000
        )

    def _toggle_filters_from_menu(self) -> None:
        """Show/hide the filter panel from the Style menu.

        Delegates to :meth:`toggle_filters` — the existing splitter-collapse
        path that also persists ``filter_section_visible`` — rather than setting
        the flag here, so the menu and the panel's own toggle stay one
        behaviour. Re-reads the resulting state instead of assuming it, since
        the toggle is what decides.
        """
        self.toggle_filters()
        self._filters_visible_action.setChecked(
            bool(getattr(self.config, "filter_section_visible", True))
        )

    def _open_adult_settings(self) -> None:
        """Open Settings → Content — the adult segment's click target.

        The section LABEL: ``open_settings`` forwards it to
        ``select_section_by_label``.
        """
        self.open_settings("Content")

    def show_about(self):
        """Open the About dialog.

        This logged "Show about" and returned for as long as the menu item has
        existed — a discoverable entry point that did nothing, and nothing
        tested it, so nothing said so.
        """
        from metatv.gui.about_dialog import AboutDialog

        AboutDialog(self).exec()

    def show_whats_new(self) -> None:
        """Open the What's New dialog with the full changelog (on-demand viewer).

        Also advances the seen cursor to the latest entry and saves config,
        so the auto-show guard treats it as seen.
        """
        entries = sorted(_whats_new.WHATS_NEW, key=lambda e: e.id, reverse=True)
        dlg = WhatsNewDialog(entries, self)
        dlg.exec()
        self.config.last_seen_whats_new_id = _whats_new.latest_id()
        self.config.save()

    def maybe_show_whats_new(self) -> None:
        """Show the What's New dialog once if there are unseen entries.

        Idempotent: guarded by ``_whats_new_checked`` so it cannot fire twice
        even if called from multiple code paths.  After showing, advances the
        cursor and saves config so it will not appear again until new entries
        are added.
        """
        if self._whats_new_checked:
            return
        self._whats_new_checked = True

        # In dev/QA mode the app is launched to exercise features, not to greet the
        # user — and the harness routinely runs a fresh isolated config (last_seen=0)
        # that would replay the ENTIRE historical changelog every launch. Skip the
        # auto-dialog under METATV_DEV (the Help ▸ What's New menu still works).
        if _dev_mode_enabled():
            return

        # First launch on a fresh config (cursor 0): don't replay the entire
        # historical changelog — fast-forward silently. A cursor of 0 in normal
        # mode can only mean a just-created config, because dismissing the dialog
        # always advances the cursor. Upgrades keep showing their delta as before.
        if self.config.last_seen_whats_new_id == 0:
            self.config.last_seen_whats_new_id = _whats_new.latest_id()
            self.config.save()
            return

        unseen = self._whats_new_unseen()
        if not unseen:
            return

        # Backlog cap: a stale cursor must never replay a wall of history — cap
        # the AUTO dialog to the newest release's entries and say what was
        # skipped (Help ▸ What's New still has everything). The cursor still
        # advances past the skipped entries: they are old news by definition.
        footnote = None
        if len(unseen) > _WHATS_NEW_AUTO_CAP:
            newest_version = unseen[0].version  # entries_since is newest-first
            capped = [e for e in unseen if e.version == newest_version]
            if capped and len(capped) < len(unseen):
                footnote = (
                    f"{len(unseen) - len(capped)} earlier entries from older "
                    "releases — browse them anytime in Help ▸ What's New"
                )
                unseen = capped

        dlg = WhatsNewDialog(unseen, self, footnote=footnote)
        dlg.exec()
        self.config.last_seen_whats_new_id = _whats_new.latest_id()
        self.config.save()

    def _open_qa_checklist(self) -> None:
        """Open (or focus) the floating QA Testing Checklist window.

        Constructs lazily on first call; subsequent calls bring the existing
        window to the front.  No-op when not in dev mode.
        """
        if not _dev_mode_enabled():
            return
        from metatv.gui.qa_checklist_window import QAChecklistWindow  # local import — dev only
        if self._qa_checklist_window is None:
            self._qa_checklist_window = QAChecklistWindow(
                self.config, _whats_new.WHATS_NEW, parent=self
            )
        win = self._qa_checklist_window
        win.show()
        win.raise_()
        win.activateWindow()

    def _maybe_show_qa_checklist(self) -> None:
        """Auto-show the QA checklist on startup if there are open test items.

        Only fires when METATV_DEV is set.  An "open" item is an entry with
        test_steps, id > qa_verified_id, and at least one step that is not yet
        marked ``pass`` in ``qa_step_results`` (untested OR failed).
        """
        if not _dev_mode_enabled():
            return
        verified = self.config.qa_verified_id
        results = self.config.qa_step_results or {}
        for entry in _whats_new.WHATS_NEW:
            if not entry.test_steps or entry.id <= verified:
                continue
            ent = results.get(str(entry.id), {})
            n_pass = sum(
                1 for i in range(len(entry.test_steps))
                if (ent.get(str(i)) or {}).get("state") == "pass"
            )
            if n_pass < len(entry.test_steps):
                # At least one open item — show the window
                logger.debug(
                    "QA checklist: open items found (entry id={}), auto-showing", entry.id
                )
                self._open_qa_checklist()
                return
