"""Provider/source lifecycle mixin for :class:`MainWindow`.

This module holds :class:`_ProviderMixin` — the provider/source lifecycle
methods extracted verbatim from ``main_window.py`` as part of the B10
decomposition. It covers the full add / edit / delete / refresh / toggle /
test surface plus the canonical ``_refresh_provider_dependent_views``
chokepoint that every provider mutation must funnel through.

The methods rely on attributes and sibling methods defined on ``MainWindow``
(e.g. ``self.db``, ``self.load_channels``); they resolve via ``self``/MRO at
runtime, so the split is behaviour-preserving.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from loguru import logger

from metatv.core.repositories import RepositoryFactory
from metatv.gui.dialogs import AddProviderDialog


class _ProviderMixin:
    """Provider/source lifecycle methods mixed into :class:`MainWindow`."""

    def add_provider(self):
        """Show add provider dialog"""
        dialog = AddProviderDialog(self, self.config, self.db, self.notification_manager)
        if dialog.exec():
            self.load_providers()

    def enter_provider_edit_mode(self, provider_id: str):
        """Switch center panel to provider editor for the given provider."""
        self._hide_all_content_views()
        self.provider_editor.setVisible(True)
        self.provider_editor.load_provider(provider_id)
        self.stats_label.setText("Editing provider — click a source to switch")
        self._in_provider_edit_mode = True
        self._deactivate_view_chips()

    def exit_provider_edit_mode(self):
        """Return to the normal channel list view."""
        self._in_provider_edit_mode = False
        self.switch_to_list_view()
        self.load_providers()

    def enter_provider_analytics_mode(self, provider_id: str):
        """Switch center panel to source analytics for the given provider."""
        self._hide_all_content_views()
        self.source_analytics.setVisible(True)
        self.source_analytics.on_activate(provider_id)
        self.stats_label.setText("Analyzing source — click a source to switch")
        self._deactivate_view_chips()

    def exit_provider_analytics_mode(self):
        """Return to the normal channel list view."""
        self.source_analytics.on_deactivate()
        self.switch_to_list_view()

    def toggle_provider_active(self, provider_id: str):
        """Flip the is_active flag for a provider and refresh all affected views."""
        sources = self.sidebar_sections.get("sources")
        # Re-entrancy guard: the canonical refresh below can take many seconds
        # (recommendations recompute over the whole library), so ignore repeat
        # clicks while one is in flight rather than stacking them.
        if sources is not None and sources.is_provider_busy(provider_id):
            self.status_bar.showMessage("Source update already in progress…", 2000)
            return
        if sources is not None:
            sources.set_provider_busy(provider_id, True)
        self.status_bar.showMessage("Updating views…")

        session = self.db.get_session()
        try:
            from metatv.core.database import ProviderDB as _PDB
            db_prov = session.query(_PDB).filter_by(id=provider_id).first()
            if db_prov:
                db_prov.is_active = not db_prov.is_active
                session.commit()
                logger.info(f"Provider '{db_prov.name}' is_active → {db_prov.is_active}")
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to toggle provider: {e}")
            self._clear_provider_busy()   # early-return cleanup (CLAUDE.md rule)
            return
        finally:
            session.close()
        # Refresh every view derived from provider/channel data (canonical).
        # Busy state is cleared when the channel reload completes (_on_channels_loaded);
        # the timer is a safety net in case that signal never fires.
        self._refresh_provider_dependent_views()
        QTimer.singleShot(30_000, self._clear_provider_busy)

    def _clear_provider_busy(self) -> None:
        """Clear any in-flight provider busy/spinner state and the status message.

        Called when a provider-triggered refresh completes (via _on_channels_loaded)
        and as a safety timeout from toggle_provider_active."""
        sources = self.sidebar_sections.get("sources")
        had_busy = sources is not None and sources.has_busy()
        if sources is not None:
            sources.clear_busy()
        if had_busy:
            self.status_bar.clearMessage()

    def _on_provider_epg_refresh(self, provider_id: str) -> None:
        """Sidebar EPG indicator clicked — refresh that source's EPG feed."""
        sources = self.sidebar_sections.get("sources")
        if sources is not None:
            sources.set_provider_epg_refreshing(provider_id, True)
            # Safety net: clear the spinner if the fetch never signals back (e.g. the
            # provider has no usable EPG URL, so force_refresh_provider no-ops).
            QTimer.singleShot(
                90_000,
                lambda pid=provider_id: self._epg_refresh_spinner_off(pid),
            )
        self.status_bar.showMessage("Refreshing EPG…", 3000)
        self.epg_manager.force_refresh_provider(provider_id)

    def _epg_refresh_spinner_off(self, provider_id: str) -> None:
        sources = self.sidebar_sections.get("sources")
        if sources is not None:
            sources.set_provider_epg_refreshing(provider_id, False)

    def _on_provider_epg_refreshed(self, provider_id: str, *_args) -> None:
        """EPG fetch finished/errored — rebuild Sources so the indicator recolors with
        the new date range and the spinner clears."""
        sources = self.sidebar_sections.get("sources")
        if sources is not None:
            sources.refresh()

    def _on_provider_saved(self, provider_id: str):
        """Refresh dependent views after a provider is saved in the editor.

        Goes through the canonical refresh so an icon/name/credential edit
        reflects everywhere (sidebar AND the main list's provider badges), not
        just the sidebar.
        """
        self._refresh_provider_dependent_views()
        self.status_bar.showMessage("Provider saved.", 3000)

    def _on_provider_deleted(self, provider_id: str):
        """Clean up after a provider is deleted from the editor."""
        self.exit_provider_edit_mode()
        self._refresh_provider_dependent_views()
        self.status_bar.showMessage("Provider deleted.", 3000)

    def _on_account_info_updated(self, provider_id: str):
        """Refresh sources sidebar when account info is updated.

        Called when account info is refreshed in the provider editor so the
        sidebar color/display reflects the updated expiration date.
        """
        sources_section = self.sidebar_sections.get("sources")
        if sources_section:
            sources_section.refresh()

    def _refresh_provider_dependent_views(self) -> None:
        """Canonical refresh for everything derived from provider/channel data.

        ALL provider/source mutations — add, edit, delete, refresh-complete,
        toggle active/visibility — must funnel through this one method instead
        of hand-picking a subset of views at each call site. Hand-picking is
        what repeatedly left views stale (e.g. the sidebar icon updated but the
        main list's ``provider_icon_map`` did not, so new sources showed content
        with no icon). Keep this list complete; do not re-implement partial
        refreshes elsewhere.
        """
        # Sidebar sections fed by the channel/provider corpus
        self.load_providers()
        self.load_favorites()
        self.load_history()
        self._refresh_queue_section()
        self._refresh_recommended_section()
        # Main channel list / search results — also rebuilds provider_icon_map
        self.load_channels()
        # Center overlay views — lazily constructed, refresh only if present
        if hasattr(self, "discover_view"):
            self.discover_view.reload()
        if hasattr(self, "preferences_view"):
            self.preferences_view.refresh()

    def edit_provider(self):
        """Legacy hook — no longer used (edit triggers from sidebar widget)."""
        pass

    def load_providers(self):
        """Load providers from database into sidebar"""
        if "sources" in self.sidebar_sections:
            self.sidebar_sections["sources"].refresh()
        self._refresh_details_provider_map()

    def _refresh_details_provider_map(self):
        """Push current provider icon/name map to the details pane."""
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            providers = repos.providers.get_all()
            provider_map = {
                p.id: {"icon": getattr(p, "icon", "") or "", "name": p.name}
                for p in providers
            }
            self.details_pane.set_provider_map(provider_map)
        except Exception as e:
            logger.warning(f"Could not refresh provider map: {e}")
        finally:
            session.close()

    def refresh_provider(self, provider_id: str):
        """Refresh channels from a specific provider"""
        # Prevent duplicate refresh calls
        if provider_id in self.refreshing_providers:
            logger.warning(f"Provider {provider_id} is already being refreshed, ignoring duplicate call")
            return

        self.refreshing_providers.add(provider_id)
        logger.info(f"Refreshing provider: {provider_id}")

        session = self.db.get_session()
        try:
            from metatv.core.models import Provider
            from metatv.core.provider_loader import ProviderLoadThread

            repos = RepositoryFactory(session)
            db_provider = repos.providers.get_by_id(provider_id)
            if not db_provider:
                logger.error(f"Provider not found: {provider_id}")
                self.refreshing_providers.discard(provider_id)
                return

            # Convert to model
            provider = repos.providers.to_model(db_provider)

            # Show progress notification
            notif_id = self.notification_manager.show_progress(
                title=f"Refreshing {provider.name}",
                total=100
            )

            # Start loading in background thread
            load_thread = ProviderLoadThread(
                provider, self.db,
                separators=self.config.prefix_separators,
                language_groups=self.config.filter_language_groups,
                quality_groups=self.config.filter_quality_groups,
                platform_groups=self.config.filter_platform_groups,
                regional_groups=self.config.filter_regional_groups,
            )
            load_thread.provider_id = provider.id  # Store for cleanup
            load_thread.progress.connect(
                lambda cur, tot, msg: self.notification_manager.update_progress(notif_id, cur, tot, msg)
            )
            load_thread.finished.connect(
                lambda success, msg: self.on_provider_refresh_finished(notif_id, success, msg, load_thread)
            )

            # Keep thread alive
            self.active_threads.append(load_thread)
            load_thread.start()

        finally:
            session.close()

    def on_provider_refresh_finished(self, notif_id: str, success: bool, message: str, thread):
        """Handle provider refresh completion"""
        # Remove thread from active list
        if thread in self.active_threads:
            self.active_threads.remove(thread)

        # Remove provider from refreshing set
        provider_id = getattr(thread, 'provider_id', None)
        if provider_id:
            if provider_id in self.refreshing_providers:
                self.refreshing_providers.discard(provider_id)
                logger.info(f"Provider {provider_id} refresh completed")
            else:
                logger.warning(f"Provider {provider_id} was not in refreshing set")
        else:
            logger.warning("Provider refresh finished but no provider_id found on thread")

        if success:
            self.notification_manager.complete_progress(notif_id, message)

            # Prefix stats were computed in the worker thread — just apply them
            stats = getattr(thread, 'prefix_stats', None)
            if stats:
                self._filter_unmapped_prefixes = stats.get('unmapped_prefixes', [])
                if hasattr(self, 'filter_panel'):
                    self.filter_panel.update_data(stats)
                logger.info(f"Filter stats: {stats['channels_with_prefix']:,} channels have prefixes")

            # Refresh every view derived from provider/channel data (canonical)
            self._refresh_provider_dependent_views()
            # Re-check any failed streams now that content is fresh
            if hasattr(self, "stream_retry_manager"):
                self.stream_retry_manager.check_all_now()

            # Relink EPG rows against the freshly-loaded channel corpus.
            # This is a DB-only pass (no network fetch) that fixes the partial-match
            # case: channels whose EPG rows were stored with channel_db_id=NULL
            # because they weren't loaded at XMLTV fetch time get linked now.
            # Safe here because channels just finished loading, and relink_all uses
            # the EPG manager's existing executor (no new pool / no SQLite lock race).
            if getattr(self, "epg_manager", None):
                self.epg_manager.relink_all()

            # Freshly-added provider with EPG enabled → kick off its first EPG pull
            # now (alongside the channel data), so the user never has to open Source
            # Settings to get the initial guide. force_refresh_provider bypasses the
            # throttle and no-ops if a fetch is already running.
            if provider_id and provider_id in self._epg_fetch_after_add:
                self._epg_fetch_after_add.discard(provider_id)
                if getattr(self, "epg_manager", None):
                    logger.info(f"First EPG fetch for newly-added provider {provider_id}")
                    self.epg_manager.force_refresh_provider(provider_id)
        else:
            # Channel load failed — drop any pending add-time EPG flag.
            if provider_id:
                self._epg_fetch_after_add.discard(provider_id)
            from metatv.core.notifications import NotificationType
            self.notification_manager.update(
                notif_id,
                type=NotificationType.ERROR,
                title="Refresh Failed",
                message=message,
                dismissible=True,
                auto_dismiss_seconds=5
            )

    def refresh_all_providers(self) -> None:
        """Refresh channels from every active provider."""
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            provider_ids = [p.id for p in repos.providers.get_all(active_only=True)]
        finally:
            session.close()
        for pid in provider_ids:
            self.refresh_provider(pid)

    def on_provider_selected(self, item, column):
        """Handle provider selection in tree"""
        provider_id = item.data(0, Qt.ItemDataRole.UserRole)
        if provider_id:
            self.selected_provider_id = provider_id
            logger.info(f"Selected provider: {provider_id}")
            self.load_channels(provider_id)

    def on_provider_selected_new(self, provider_id: str):
        """Handle provider selection from modular sidebar.

        In provider edit mode, clicking a source switches the editor instead of
        filtering the channel list.  Otherwise clicking the already-active source
        toggles the per-source filter OFF; clicking a different source switches to it.
        """
        if self._in_provider_edit_mode:
            self.provider_editor.load_provider(provider_id)
            return
        if provider_id and provider_id == self.selected_provider_id:
            # Toggle OFF — clicking the active source again clears the filter.
            self.selected_provider_id = None
            self.load_channels(None)
            src = self.sidebar_sections.get("sources")
            if src is not None and hasattr(src, "clear_selection"):
                src.clear_selection()
            logger.info("Cleared source filter (toggled off)")
        else:
            self.selected_provider_id = provider_id
            logger.info(f"Selected provider: {provider_id}")
            self.load_channels(provider_id)

    def toggle_provider_visibility(self, provider_id: str):
        """Toggle provider visibility (active/disabled)"""
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            provider = repos.providers.get_by_id(provider_id)
            if provider:
                # Toggle active state
                provider.is_active = not provider.is_active
                session.commit()

                logger.info(f"Provider {provider.name} is now {'active' if provider.is_active else 'disabled'}")

                # Update status button
                self.update_provider_status(provider_id, "testing" if provider.is_active else "disabled")

                # Refresh every view derived from provider/channel data (canonical)
                self._refresh_provider_dependent_views()

                # Test connection if enabled
                if provider.is_active:
                    self.test_provider_connection(provider_id)
        finally:
            session.close()

    def update_provider_status(self, provider_id: str, status: str):
        """Update provider status indicator in sidebar

        Args:
            provider_id: Provider ID
            status: 'disabled', 'testing', 'online', 'offline'
        """
        if "sources" in self.sidebar_sections:
            self.sidebar_sections["sources"].update_provider_status(provider_id, status)

    def test_all_providers(self):
        """Test connection for all active providers on startup"""
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            providers = repos.providers.get_all(active_only=True)

            for provider in providers:
                self.update_provider_status(provider.id, "testing")
                self.test_provider_connection(provider.id)
        finally:
            session.close()

    def test_provider_connection(self, provider_id: str):
        """Test connection to a specific provider"""
        session = self.db.get_session()
        try:
            from metatv.core.provider_loader import ProviderTestThread

            repos = RepositoryFactory(session)
            db_provider = repos.providers.get_by_id(provider_id)
            if not db_provider:
                return

            # Start test in background
            test_thread = ProviderTestThread(
                db_provider.type,
                db_provider.url,
                db_provider.username,
                db_provider.password
            )
            test_thread.result.connect(
                lambda success, msg, pid=provider_id: self.on_connection_test_result(pid, success, msg)
            )

            # Keep thread alive
            self.active_threads.append(test_thread)
            test_thread.finished.connect(
                lambda: self.active_threads.remove(test_thread) if test_thread in self.active_threads else None
            )

            test_thread.start()
        finally:
            session.close()

    def on_connection_test_result(self, provider_id: str, success: bool, message: str):
        """Handle connection test result"""
        logger.info(f"Provider {provider_id} test result: {'online' if success else 'offline'} - {message}")
        self.update_provider_status(provider_id, "online" if success else "offline")
