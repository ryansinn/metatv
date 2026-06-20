"""Favorites / queue / history / rating mixin for MainWindow.

Extracted from MainWindow; mixed in via:
    class MainWindow(_FavoritesMixin, ..., QMainWindow): ...

All methods access state set in MainWindow.__init__ via ``self.*``.
"""

from __future__ import annotations

from dataclasses import replace

from loguru import logger
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QMessageBox

from metatv.core.repositories import RepositoryFactory


class _FavoritesMixin:
    """Mixin: favorites, queue, history, ratings, and sidebar alert helpers."""

    def _toggle_rating(self, channel_id: str, rating: int) -> None:
        """Toggle a like (+1) or dislike (-1) rating; clicking the active rating clears it."""
        from datetime import datetime
        from metatv.core.database import UserRatingDB
        with self.db.session_scope() as session:
            current = session.get(UserRatingDB, channel_id)
            if current and current.rating == rating:
                session.delete(current)
            else:
                session.merge(UserRatingDB(channel_id=channel_id, rating=rating,
                                           rated_at=datetime.utcnow()))
        if self.view_mode == "preferences":
            self.preferences_view.refresh()
        self._refresh_recommended_section()

    def _toggle_favorite_by_id(self, channel_id: str, make_favorite: bool) -> None:
        with self.db.session_scope() as session:
            channel = RepositoryFactory(session).channels.get_by_id(channel_id)
            if not channel:
                return
            channel.is_favorite = make_favorite
        self.load_favorites()

    def _hide_channel_from_alerts(self, channel_id: str) -> None:
        with self.db.session_scope() as session:
            RepositoryFactory(session).channels.set_hidden(channel_id, True)
        self._refresh_watch_alerts()
        self.load_history()
        self.load_channels()

    def _not_interested(self, channel_id: str, suppressed: bool = True) -> None:
        """Suppress (or un-suppress) channel from recommendations only."""
        with self.db.session_scope() as session:
            RepositoryFactory(session).channels.set_rec_suppressed(channel_id, suppressed)
        self.preferences_view.refresh()
        self._refresh_recommended_section()

    def _on_suppression_requested(self, channel_id: str, suppressed: bool) -> None:
        self._not_interested(channel_id, suppressed)

    def _on_hide_from_details_pane(self, channel_id: str) -> None:
        self._hide_channel_from_recommendations(channel_id)

    # --- Watch Queue helpers ---

    def _add_to_queue(self, channel_id: str) -> None:
        from metatv.core.database import ChannelDB
        with self.db.session_scope() as session:
            repos = RepositoryFactory(session)
            ch = session.get(ChannelDB, channel_id)
            repos.queue.add(
                channel_id,
                channel_name=ch.name if ch else "",
                media_type=ch.media_type if ch else "",
                source_id=ch.source_id if ch else "",
            )
        self._refresh_queue_section()
        self._refresh_recommended_section()

    def _remove_from_queue(self, channel_id: str) -> None:
        with self.db.session_scope() as session:
            RepositoryFactory(session).queue.remove(channel_id)
        self._refresh_queue_section()
        self._refresh_recommended_section()

    def _refresh_queue_section(self) -> None:
        section = self.sidebar_sections.get("queue")
        if section:
            section.refresh()

    def _refresh_alerts_retry_section(self) -> None:
        section = self.sidebar_sections.get("alerts")
        if section and hasattr(section, "refresh_retry"):
            entries = self.stream_retry_manager.get_all_pending()
            section.refresh_retry(entries)

    def _on_retry_play_requested(self, channel_id: str, stream_url: str, channel_name: str) -> None:
        """Double-click on a Stream Monitoring item — try launching the stream again."""
        channel = None
        with self.db.session_scope() as session:
            channel = RepositoryFactory(session).channels.get_playable_dto(channel_id)
        if channel:
            self.play_media(channel)
        else:
            # Episode path — no ChannelDB entry; validate and play directly
            self.launch_player_for_episode(stream_url, channel_name or stream_url, [])

    def _on_retry_context_menu_requested(self, entry_id: str, channel_id: str, x: int, y: int) -> None:
        """Thin wrapper → unified channel menu (retry surface)."""
        ids = [channel_id] if channel_id else []
        self._show_channel_menu(ids, "retry", x, y, entry_id=entry_id)

    def _on_stream_back_online(self, channel_id: str, channel_name: str) -> None:
        from PyQt6.QtWidgets import QApplication
        self.notification_manager.show(
            title="Stream Available",
            message=f"{channel_name} is back online.",
            type="success",
            dismissible=True,
            auto_dismiss_seconds=30,
        )
        self._refresh_alerts_retry_section()

    def search_for_title(self, title: str) -> None:
        """Activate the Search view and pre-fill the search box with *title*.

        Called when the user double-clicks an unavailable queue or favorites entry
        to find a replacement on an active source.
        """
        # Ensure the Search chip is active and the channel-list view is actually
        # shown (the user may be in EPG/Discover) — mirrors on_search_view_toggle,
        # which switches the view via switch_to_list_view(). Without this the query
        # would run but the results stay hidden behind the current view.
        if not self.search_chip.is_enabled():
            self.search_chip.blockSignals(True)
            self.search_chip.set_enabled(True)
            self.search_chip.blockSignals(False)
        self.switch_to_list_view()
        self.search_input.setText(title)

    def _clear_unavailable_queue(self, section) -> None:
        """Confirm then remove all unavailable entries from the watch queue."""
        from PyQt6.QtWidgets import QMessageBox
        # Count without modifying; get hidden ids on a read-only pass.
        count = 0
        hidden: set[str] = set()
        with self.db.session_scope() as session:
            repos = RepositoryFactory(session)
            hidden = set(repos.providers.get_hidden_provider_ids())
            entries = repos.queue.get_all(hidden_provider_ids=hidden)
            count = sum(1 for e in entries if not e.available)

        if count == 0:
            return

        reply = QMessageBox.question(
            self,
            "Clear Unavailable",
            f"Remove {count} unavailable item{'s' if count != 1 else ''} from your watch queue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        with self.db.session_scope() as session:
            repos = RepositoryFactory(session)
            hidden = set(repos.providers.get_hidden_provider_ids())
            repos.queue.clear_unavailable(hidden)

        section.refresh()
        self.status_bar.showMessage(
            f"Removed {count} unavailable item{'s' if count != 1 else ''} from watch queue"
        )

    def _clear_unavailable_favorites(self, section) -> None:
        """Confirm then un-favorite all channels on unavailable sources."""
        from PyQt6.QtWidgets import QMessageBox
        count = 0
        hidden: set[str] = set()
        with self.db.session_scope() as session:
            repos = RepositoryFactory(session)
            hidden = set(repos.providers.get_hidden_provider_ids())
            dtos = repos.channels.get_favorites_dto(hidden_provider_ids=hidden)
            count = sum(1 for d in dtos if not d.available)

        if count == 0:
            return

        reply = QMessageBox.question(
            self,
            "Clear Unavailable",
            f"Remove {count} unavailable item{'s' if count != 1 else ''} from your favorites?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        with self.db.session_scope() as session:
            repos = RepositoryFactory(session)
            hidden = set(repos.providers.get_hidden_provider_ids())
            repos.channels.clear_unavailable_favorites(hidden)

        section.refresh()
        self.status_bar.showMessage(
            f"Removed {count} unavailable item{'s' if count != 1 else ''} from favorites"
        )

    def _clear_queue(self) -> None:
        from PyQt6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, "Clear Queue",
            "Are you sure you want to clear the watch queue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            with self.db.session_scope() as session:
                RepositoryFactory(session).queue.clear()
            self._refresh_queue_section()

    def _clear_watched_queue(self) -> None:
        count = 0
        with self.db.session_scope() as session:
            count = RepositoryFactory(session).queue.clear_watched()
        self._refresh_queue_section()
        if count:
            self.status_bar.showMessage(f"Removed {count} watched item(s) from queue")

    def play_queue_item_id(self, channel_id: str) -> None:
        """Play a queue item — series opens the season view, others play directly."""
        from metatv.core.models import MediaType
        channel = None
        with self.db.session_scope() as session:
            channel = RepositoryFactory(session).channels.get_playable_dto(channel_id)
        if not channel:
            return
        if channel.media_type == MediaType.SERIES:
            self.drill_into_series(channel)
        else:
            self.play_media(channel)

    def _on_details_queue_toggle(self, channel_id: str) -> None:
        """Handle queue toggle from the details pane button."""
        from metatv.core.database import ChannelDB
        with self.db.session_scope() as session:
            repos = RepositoryFactory(session)
            if repos.queue.is_queued(channel_id):
                repos.queue.remove(channel_id)
            else:
                ch = session.get(ChannelDB, channel_id)
                repos.queue.add(
                    channel_id,
                    channel_name=ch.name if ch else "",
                    media_type=ch.media_type if ch else "",
                    source_id=ch.source_id if ch else "",
                )
        self._refresh_queue_section()

    def _on_queue_channel_context_menu(self, channel_id: str, gx: int, gy: int) -> None:
        """Thin wrapper → unified channel menu (queue surface)."""
        self._show_channel_menu([channel_id], "queue", gx, gy)

    def _on_rec_channel_context_menu(self, channel_id: str, gx: int, gy: int) -> None:
        """Thin wrapper → unified channel menu (recommended surface)."""
        self._show_channel_menu([channel_id], "recommended", gx, gy)

    def _on_alert_channel_context_menu(self, channel_id: str, gx: int, gy: int) -> None:
        """Thin wrapper → unified channel menu (alerts surface)."""
        self._show_channel_menu([channel_id], "alerts", gx, gy)

    def _on_alert_clicked(self, channel_db_id: str) -> None:
        """Play the channel immediately when a sidebar watch alert is double-clicked."""
        if channel_db_id:
            self.play_channel_by_id(channel_db_id)

    def _on_alert_channel_details(self, channel_db_id: str) -> None:
        """Show channel details in the right pane when a watch alert row is single-clicked."""
        if not channel_db_id:
            return
        channel = None
        with self.db.session_scope() as session:
            channel = RepositoryFactory(session).channels.get_playable_dto(channel_db_id)
        if channel:
            self.details_pane.show_channel(channel)

    def load_history(self):
        """Load playback history into sidebar"""
        if "history" in self.sidebar_sections:
            self.sidebar_sections["history"].refresh()

    def load_favorites(self):
        """Load favorites into sidebar"""
        if "favorites" in self.sidebar_sections:
            self.sidebar_sections["favorites"].refresh()

    def show_history_context_menu(self, position, list_widget=None):
        if list_widget is None:
            if "history" in self.sidebar_sections:
                list_widget = self.sidebar_sections["history"].history_list
            else:
                return
        item = list_widget.itemAt(position)
        if not item or not item.data(Qt.ItemDataRole.UserRole):
            return
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        gp = list_widget.mapToGlobal(position)
        self._show_context_menu_for(channel_id, gp.x(), gp.y(), "history")

    def _hide_channel_from_history(self, channel_id: str) -> None:
        with self.db.session_scope() as session:
            RepositoryFactory(session).channels.set_hidden(channel_id, True)
        self.load_history()
        self.load_channels()

    def play_from_history(self, item):
        """Play a channel from history"""
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        if not channel_id:
            return
        self.play_channel(item)

    def play_from_history_id(self, channel_id: str):
        """Play a channel from history by ID"""
        from metatv.core.models import MediaType
        channel = None
        with self.db.session_scope() as session:
            channel = RepositoryFactory(session).channels.get_playable_dto(channel_id)
        if not channel:
            return
        if channel.media_type == MediaType.SERIES:
            last_episode = None
            with self.db.session_scope() as session:
                last_episode = RepositoryFactory(session).episodes.get_last_played_dto(
                    series_id=channel.source_id,
                    provider_id=channel.provider_id,
                )
            if last_episode:
                logger.info(f"Playing last watched episode from history: {last_episode.title}")
                self.play_episode(last_episode)
            else:
                logger.info("No episode history found, opening series view")
                self.drill_into_series(channel)
        else:
            self.play_media(channel)

    def remove_from_history(self, channel_id: str):
        """Remove a single channel from history"""
        channel_name = None
        with self.db.session_scope() as session:
            repos = RepositoryFactory(session)
            channel = repos.channels.get_by_id(channel_id)
            if channel:
                channel_name = channel.name
                repos.channels.remove_from_history(channel_id)
        if channel_name:
            self.status_bar.showMessage(f"Removed {channel_name} from history")
            logger.info(f"Removed {channel_name} from history")
            self.load_history()

    def clear_history(self):
        """Clear all history"""
        from PyQt6.QtWidgets import QMessageBox

        reply = QMessageBox.question(
            self,
            "Clear History",
            "Are you sure you want to clear all playback history?\n\nThis will not remove favorites.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            try:
                with self.db.session_scope() as session:
                    RepositoryFactory(session).channels.clear_history()
                self.status_bar.showMessage("History cleared")
                logger.info("Cleared all playback history")
                self.load_history()
                self.load_favorites()
            except Exception as e:
                logger.error(f"Failed to clear history: {e}")
                self.status_bar.showMessage(f"Error clearing history: {e}")

    def show_favorites_context_menu(self, position, list_widget=None):
        if list_widget is None:
            if hasattr(self, 'favorites_list'):
                list_widget = self.favorites_list
            else:
                return
        item = list_widget.itemAt(position)
        if not item or not item.data(Qt.ItemDataRole.UserRole):
            return
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        gp = list_widget.mapToGlobal(position)
        self._show_context_menu_for(channel_id, gp.x(), gp.y(), "favorites")

    def show_channel_context_menu(self, position):
        item = self.channels_list.itemAt(position)
        if not item or not item.data(Qt.ItemDataRole.UserRole):
            return

        # Collect all selected channel IDs (multi-select aware)
        selected_ids = [
            i.data(Qt.ItemDataRole.UserRole)
            for i in self.channels_list.selectedItems()
            if i.data(Qt.ItemDataRole.UserRole)
        ]
        if not selected_ids:
            selected_ids = [item.data(Qt.ItemDataRole.UserRole)]

        channel_id = item.data(Qt.ItemDataRole.UserRole)
        gp = self.channels_list.mapToGlobal(position)

        if len(selected_ids) > 1:
            # Multi-select context menu — only show bulk actions
            self._show_multi_select_context_menu(selected_ids, gp)
        else:
            self._show_context_menu_for(channel_id, gp.x(), gp.y(), "channel")

    def _quick_assign_category(
        self,
        channel_ids: list[str],
        category: str,
        mood: str | None,
        exclude: bool,
    ) -> None:
        """Assign channel_ids to category immediately, no dialog."""
        # Update config on main thread first so the signal-triggered reload sees the exclusion.
        if exclude and category not in self.config.global_filter_excluded_user_categories:
            self.config.global_filter_excluded_user_categories.append(category)
            self.config.save()
            self._update_filter_btn_state()

        def _do_assign():
            with self.db.session_scope() as session:
                RepositoryFactory(session).channels.assign_user_category(channel_ids, category, mood)
            self._category_assigned.emit()

        self.executor.submit(_do_assign)

        n = len(channel_ids)
        excl_note = " (added to Global Exclusions)" if exclude else ""
        self.status_bar.showMessage(
            f"{n:,} channel{'s' if n != 1 else ''} → \"{category}\"{excl_note}"
        )

        if hasattr(self, "discover_view"):
            QTimer.singleShot(500, self.discover_view.reload)

    def _show_multi_select_context_menu(self, channel_ids: list[str], gp) -> None:
        """Thin wrapper → unified channel menu (multi-select on channel surface)."""
        self._show_channel_menu(channel_ids, "channel", gp.x(), gp.y())

    def play_favorite(self, item):
        """Play a favorite channel"""
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        if not channel_id:
            return
        self.play_channel(item)

    def play_favorite_id(self, channel_id: str):
        """Play a favorite channel by ID"""
        from metatv.core.models import MediaType
        channel = None
        with self.db.session_scope() as session:
            channel = RepositoryFactory(session).channels.get_playable_dto(channel_id)
        if not channel:
            return
        if channel.media_type == MediaType.SERIES:
            self.drill_into_series(channel)
        else:
            self.play_media(channel)

    def _apply_favorite_toggle(self, channel_id: str):
        """Toggle favorite in DB, show status bar message, refresh sidebar.

        Returns (channel, new_status) on success, or None if channel not found.

        Uses legacy try/finally (not session_scope) because toggle_favorite() commits
        internally, expiring all column attributes via expire_on_commit=True.
        session.refresh() reloads them; session.close() then detaches the object with
        its __dict__ intact. session_scope()'s auto-commit on exit would expire again
        after the refresh, causing DetachedInstanceError when callers access
        channel.name / channel.is_favorite.
        """
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            channel = repos.channels.get_by_id(channel_id)
            if not channel:
                return None
            new_status = repos.channels.toggle_favorite(channel_id)
            # toggle_favorite() commits, which expires every column on `channel`
            # (expire_on_commit defaults True). Repopulate now so callers can read
            # attributes (name, media_type, provider_id, ...) after the session is
            # closed without triggering a DetachedInstanceError.
            session.refresh(channel)
        finally:
            session.close()

        status = "added to" if channel.is_favorite else "removed from"
        self.status_bar.showMessage(f"{channel.name} {status} favorites")
        logger.info(f"Toggled favorite for {channel.name}: {channel.is_favorite}")
        self.load_favorites()
        return channel, new_status

    def toggle_favorite(self, item):
        """Toggle favorite status of a channel"""
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        if not channel_id:
            return

        result = self._apply_favorite_toggle(channel_id)
        if not result:
            return
        channel, _ = result

        # Update the icon on the current item only (fast, no database query)
        current_text = item.text()
        if channel.is_favorite:
            updated_text = current_text.replace(self.unfavorite_icon, self.favorite_icon)
        else:
            updated_text = current_text.replace(self.favorite_icon, self.unfavorite_icon)
        item.setText(updated_text)

        # Also update in all_channels cache for filtering. The cached entries are
        # frozen ChannelListDTOs, so build a new one with the flipped flag rather
        # than mutating in place (a frozen dataclass would raise on assignment).
        for i, (text, ch) in enumerate(self.all_channels):
            if ch.id == channel_id:
                new_ch = replace(ch, is_favorite=channel.is_favorite)
                media_icon = self.get_media_type_icon(new_ch.media_type)
                fav_icon = self.favorite_icon if new_ch.is_favorite else self.unfavorite_icon
                display_text = f"{media_icon}{fav_icon} {new_ch.name}"
                if new_ch.category:
                    display_text += f" [{new_ch.category}]"
                if new_ch.quality and new_ch.quality != "unknown":
                    display_text += f" ({new_ch.quality})"
                self.all_channels[i] = (display_text, new_ch)
                break

    def play_channel_by_id(self, channel_id: str):
        """Play channel by ID (for details pane Play button)"""
        from metatv.core.models import MediaType
        channel = None
        with self.db.session_scope() as session:
            channel = RepositoryFactory(session).channels.get_playable_dto(channel_id)
        if not channel:
            return
        if channel.media_type == MediaType.SERIES:
            self.drill_into_series(channel)
        else:
            self.play_media(channel)

    def play_channel_new_window_by_id(self, channel_id: str) -> None:
        """Play channel by ID, forcing a separate per-source player window.

        Mirrors ``play_channel_by_id`` but passes ``force_new_window=True`` so
        the stream is keyed by ``provider_id`` regardless of the global
        ``split_streams_by_source`` toggle.  For SERIES channels the normal
        series drill-in is used — a series has no single stream to target.

        Args:
            channel_id: The channel's unique ID string.
        """
        from metatv.core.models import MediaType
        channel = None
        with self.db.session_scope() as session:
            channel = RepositoryFactory(session).channels.get_playable_dto(channel_id)
        if not channel:
            return
        if channel.media_type == MediaType.SERIES:
            self.drill_into_series(channel)
        else:
            self.play_media(channel, force_new_window=True)

    def diagnose_channel_by_id(self, channel_id: str) -> None:
        """Open the stream-diagnostics dialog for a channel (bottom-nav Diagnose button).

        Extracts primitives inside the session block (no ORM object crosses the
        boundary), then hands the URL/name to a modal dialog that runs the headless
        diagnostic off the main thread on the shared executor.
        """
        from metatv.gui.diagnostics_dialog import StreamDiagnosticsDialog

        stream_url = None
        name = ""
        with self.db.session_scope() as session:
            channel = RepositoryFactory(session).channels.get_by_id(channel_id)
            if channel:
                stream_url = channel.stream_url
                name = channel.name
        if not stream_url:
            return

        player_active = self.player_manager.is_running()
        dialog = StreamDiagnosticsDialog(
            channel_name=name,
            stream_url=stream_url,
            config=self.config,
            executor=self.executor,
            player_active=player_active,
            parent=self,
        )
        dialog.exec()

    def toggle_favorite_by_id(self, channel_id: str):
        """Toggle favorite by ID (for details pane Favorite button)"""
        result = self._apply_favorite_toggle(channel_id)
        if not result:
            return
        channel, _ = result

        # Update details pane — but not while the lightbox has focus (D6)
        if not (hasattr(self, '_lightbox') and self._lightbox.isVisible()):
            self.update_details_pane_for_channel(channel)

        # Update channel list display if visible
        for i in range(self.channels_list.count()):
            item = self.channels_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == channel_id:
                current_text = item.text()
                if channel.is_favorite:
                    updated_text = current_text.replace(self.unfavorite_icon, self.favorite_icon)
                else:
                    updated_text = current_text.replace(self.favorite_icon, self.unfavorite_icon)
                item.setText(updated_text)
                break
