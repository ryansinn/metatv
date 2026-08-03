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
        cleared = False
        with self.db.session_scope() as session:
            current = session.get(UserRatingDB, channel_id)
            if current and current.rating == rating:
                session.delete(current)
                cleared = True
            else:
                session.merge(UserRatingDB(channel_id=channel_id, rating=rating,
                                           rated_at=datetime.utcnow()))
                # A like/dislike is mutually exclusive with "not interested" —
                # clear any suppression so the sentiment buttons stay consistent.
                RepositoryFactory(session).channels.set_rec_suppressed(channel_id, False)
        # Update the channel-list row glyph in place — mirrors update_favorite wiring.
        new_rating = 0 if cleared else rating
        if hasattr(self, 'channel_model'):
            self.channel_model.update_rating(channel_id, new_rating)
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
        """Suppress (or un-suppress) channel from recommendations only.

        Turning suppression on is mutually exclusive with a like/dislike — the
        rating is cleared so the sentiment buttons stay consistent.
        """
        from metatv.core.database import UserRatingDB
        with self.db.session_scope() as session:
            RepositoryFactory(session).channels.set_rec_suppressed(channel_id, suppressed)
            if suppressed:
                current = session.get(UserRatingDB, channel_id)
                if current:
                    session.delete(current)
        if suppressed and hasattr(self, "channel_model"):
            self.channel_model.update_rating(channel_id, 0)
        self.preferences_view.refresh()
        self._refresh_recommended_section()

    def _on_suppression_requested(self, channel_id: str, suppressed: bool) -> None:
        self._not_interested(channel_id, suppressed)

    def _on_hide_from_details_pane(self, channel_id: str) -> None:
        self._hide_channel_from_recommendations(channel_id)

    # --- VOD Mark-as-Watched helpers (channel list / history / favorites) ---

    def _mark_channel_watched(self, channel_id: str) -> None:
        """Mark a movie or series channel as watched and update the row in place.

        When the "Hide watched" filter is ON, the row is removed from the model
        immediately (no full reload).  When the filter is OFF, the row's watch
        indicator updates in place via ``update_watch_completed``.
        """
        with self.db.session_scope() as session:
            RepositoryFactory(session).channels.mark_watched(channel_id, watched=True)
        self._apply_mark_watched_ui([channel_id], watched=True)

    def _mark_channel_unwatched(self, channel_id: str) -> None:
        """Mark a movie or series channel as unwatched and update the row in place."""
        with self.db.session_scope() as session:
            RepositoryFactory(session).channels.mark_watched(channel_id, watched=False)
        self._apply_mark_watched_ui([channel_id], watched=False)

    def _on_details_watched_toggled(self, channel_id: str, watched: bool) -> None:
        """Details-pane Watched toggle — route through the shared mark-watched chokepoint.

        Reuses the same per-channel mark/unmark path the context-menu "Mark as
        Watched" action uses, so persistence + in-place row updates stay identical.

        Args:
            channel_id: The channel whose watched state changed.
            watched: True to mark watched, False to mark unwatched.
        """
        if watched:
            self._mark_channel_watched(channel_id)
        else:
            self._mark_channel_unwatched(channel_id)

    def _bulk_mark_watched(self, channel_ids: list[str]) -> None:
        """Toggle the watched state for multiple channels atomically, then update rows in place.

        If ALL selected channels are already watched, unmarks them all; otherwise
        marks them all as watched.  The decision is always re-derived from the DB
        (not from the menu context) so stale context data can never mis-toggle.

        Args:
            channel_ids: IDs of the channels whose watched state should be toggled.
        """
        from metatv.core.database import ChannelDB
        with self.db.session_scope(commit=False) as session:
            watched_count = (
                session.query(ChannelDB)
                .filter(
                    ChannelDB.id.in_(channel_ids),
                    ChannelDB.watch_completed == True,  # noqa: E712
                )
                .count()
            )
        all_watched = len(channel_ids) > 0 and watched_count == len(channel_ids)
        target_watched = not all_watched  # all watched → unmark; otherwise mark

        with self.db.session_scope() as session:
            RepositoryFactory(session).channels.mark_watched_bulk(channel_ids, watched=target_watched)
        self._apply_mark_watched_ui(channel_ids, watched=target_watched)

    def _apply_mark_watched_ui(self, channel_ids: list[str], watched: bool) -> None:
        """Update the channel model after a mark-watched DB write — no full reload.

        If "Hide watched" is ON and we're marking as watched: remove the affected
        rows from the model and decrement the watched-hidden count so the stats
        label stays accurate.  Otherwise just refresh the watch indicator in place.

        Args:
            channel_ids: The channels whose watch state changed.
            watched: True if marking watched, False if marking unwatched.
        """
        hide_watched = bool(getattr(self, '_stats_hide_watched', False))
        if not hasattr(self, 'channel_model'):
            # Fallback if model isn't set up yet
            self.load_channels()
            return

        if hide_watched and watched:
            # Filter is ON and item just became watched → remove rows from model.
            for cid in channel_ids:
                self.channel_model.remove_channel(cid)
            # Increment the watched hidden count in the stats (no DB round-trip needed).
            current_hidden = getattr(self, '_stats_watched_hidden', 0)
            self._stats_watched_hidden = current_hidden + len(channel_ids)
            self._refresh_channel_stats_label()
        else:
            # Filter is OFF (or unmarking watched) → update the watch indicator in place.
            for cid in channel_ids:
                self.channel_model.update_watch_completed(
                    cid,
                    watch_completed=watched,
                    watch_percent=100 if watched else 0,
                    watch_progress=0,
                )

    def _bulk_add_to_favorites(self, channel_ids: list[str]) -> None:
        """Add multiple channels to Favorites in one session then refresh.

        Args:
            channel_ids: IDs of the channels to favorite.
        """
        with self.db.session_scope() as session:
            repos = RepositoryFactory(session)
            for cid in channel_ids:
                ch = repos.channels.get_by_id(cid)
                if ch:
                    ch.is_favorite = True
        self.load_favorites()

    def _bulk_add_to_queue(self, channel_ids: list[str]) -> None:
        """Add multiple channels to the Watch Queue in one session then refresh.

        Args:
            channel_ids: IDs of the channels to enqueue.
        """
        from metatv.core.database import ChannelDB
        with self.db.session_scope() as session:
            repos = RepositoryFactory(session)
            for cid in channel_ids:
                ch = session.get(ChannelDB, cid)
                repos.queue.add(
                    cid,
                    channel_name=ch.name if ch else "",
                    media_type=ch.media_type if ch else "",
                    source_id=ch.source_id if ch else "",
                )
        self._refresh_queue_section()
        self._refresh_recommended_section()

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
            # Display path includes recovered "online" rows (green icon, "Back
            # online!" tooltip) so they stay visible until the user removes
            # them — get_all_pending() (checker-only) would drop them the
            # instant they recover. See StreamRetryRepository.get_all_display.
            entries = self.stream_retry_manager.get_all_display()
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

    def _on_stream_back_online(self, channel_id: str, channel_name: str, stream_url: str = "") -> None:
        """A previously-failed stream is back online — toast with a Play action.

        Wired to ``StreamRetryManager.stream_online``. The Play action routes
        through the existing retry-play seam (``_on_retry_play_requested`` —
        the same handler double-clicking the Stream Monitoring row uses) so
        it resolves the ChannelDB row when there is one, or falls back to the
        episode-launch path otherwise.
        """
        self.notification_manager.show(
            title="Stream Available",
            message=f"{channel_name} is back online.",
            type="success",
            dismissible=True,
            auto_dismiss_seconds=30,
            actions=[(
                "Play",
                lambda _cid=channel_id, _url=stream_url, _name=channel_name:
                    self._on_retry_play_requested(_cid, _url, _name)
            )],
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

    def _on_details_episode_queue_toggle(self, episode_id: str) -> None:
        """Handle queue toggle from the details pane button in EPISODE mode (Slice 2B).

        Targets the single episode shown in the pane, not its parent series — the
        channel-grain mirror of _on_details_queue_toggle above, keyed by episode_id.
        Denormalizes the series/episode identity onto the WatchQueueDB row so the
        entry survives an orphaned episode (same rationale as channel_name on
        channel-grain rows — see WatchQueueDB's docstring).
        """
        from metatv.core.database import EpisodeDB
        with self.db.session_scope() as session:
            repos = RepositoryFactory(session)
            if repos.queue.is_episode_queued(episode_id):
                repos.queue.remove_episode(episode_id)
            else:
                ep = session.get(EpisodeDB, episode_id)
                if ep is not None:
                    series = repos.channels.get_by_source_id(
                        provider_id=ep.provider_id, source_id=ep.series_id
                    )
                    repos.queue.add_episode(
                        episode_id,
                        channel_id=series.id if series else ep.series_id,
                        channel_name=(series.name if series else ep.series_name) or "",
                        season_num=ep.season_num,
                        episode_num=ep.episode_num,
                        episode_title=ep.title or "",
                        source_id=series.source_id if series else "",
                    )
        self._refresh_queue_section()

    def _on_details_episode_favorite_toggle(self, episode_id: str) -> None:
        """Toggle favorite for the single EPISODE shown in the details pane (episode mode).

        Direct session_scope() attribute write — the new status is read back INSIDE
        the block (before commit/expire), so no ORM object crosses the boundary
        (mirrors _toggle_favorite_by_id's shape for channels).
        """
        from metatv.core.database import EpisodeDB
        new_status = None
        title = ""
        with self.db.session_scope() as session:
            ep = session.get(EpisodeDB, episode_id)
            if ep is None:
                return
            ep.is_favorite = not bool(ep.is_favorite)
            new_status = ep.is_favorite
            title = ep.title or "Episode"
        status = "added to" if new_status else "removed from"
        self.status_bar.showMessage(f"{title} {status} favorites")
        self.load_favorites()

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
            resume_ep = None
            with self.db.session_scope() as session:
                resume_ep = RepositoryFactory(session).episodes.get_resume_dto(
                    series_id=channel.source_id,
                    provider_id=channel.provider_id,
                )
            if resume_ep:
                logger.info(f"Smart-resuming series from: {resume_ep.title}")
                self.play_episode(resume_ep)
            else:
                logger.info("No resume target found, opening series view")
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
        from metatv.gui.sidebar.favorites import _ROLE_GRAIN
        if item.data(_ROLE_GRAIN) == "episode":
            # Favorited-episode rows (Wave 2 Slice 2B) have no channel context menu
            # yet — channel_menu.py's registry is ChannelDB-only; Favorite/Unfavorite
            # for an episode lives in the series-tree row's own right-click menu.
            return
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        gp = list_widget.mapToGlobal(position)
        self._show_context_menu_for(channel_id, gp.x(), gp.y(), "favorites")

    def show_channel_context_menu(self, position):
        # QListView uses indexAt() instead of itemAt()
        index = self.channels_list.indexAt(position)
        if not index.isValid():
            return
        channel_id = index.data(Qt.ItemDataRole.UserRole)
        if not channel_id:
            return

        # Collect all selected channel IDs (multi-select aware)
        selected_ids = [
            idx.data(Qt.ItemDataRole.UserRole)
            for idx in self.channels_list.selectionModel().selectedIndexes()
            if idx.data(Qt.ItemDataRole.UserRole)
        ]
        if not selected_ids:
            selected_ids = [channel_id]

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
            self._category_assigned.emit(bool(exclude))

        self.executor.submit(_do_assign)

        n = len(channel_ids)
        excl_note = " (added to Global Exclusions)" if exclude else ""
        self.status_bar.showMessage(
            f"{n:,} channel{'s' if n != 1 else ''} → \"{category}\"{excl_note}"
        )

        if hasattr(self, "discover_view"):
            QTimer.singleShot(500, self.discover_view.reload)

    def _on_category_assigned(self, membership_changed: bool) -> None:
        """React to a completed user-category assignment.

        Previously this was wired straight to ``load_channels``, so EVERY
        assignment re-ran the query and reset the model — which scrolls the list
        back to the top. Adding one item to "Watch Later" from row 400 threw the
        user back to row 1, as punishment for a single action (owner report).

        A plain assignment writes ``user_category``/``category_mood`` and nothing
        else. ``ChannelListDTO`` carries neither, so no row renders differently
        and there is nothing to redraw, let alone requery.

        The one case that genuinely needs a reload is an assignment that also
        added the category to Global Exclusions: those rows must LEAVE the list,
        and that is a membership change the model cannot infer.

        Args:
            membership_changed: True when the category was added to Global
                Exclusions, so the visible set actually changed.
        """
        if membership_changed:
            self.load_channels()

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

    def play_channel_open_ended_buffer_by_id(self, channel_id: str) -> None:
        """Play channel by ID with open-ended disk-backed buffering.

        Mirrors ``play_channel_by_id`` but passes ``open_ended_buffer=True`` so
        mpv uses a large disk-backed cache (up to 2 GiB, 3600 s readahead)
        instead of the configured bounded buffer profile.  For SERIES channels
        the normal series drill-in is used — a series has no single stream to
        buffer ahead on.

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
            self.play_media(channel, open_ended_buffer=True)

    def play_channel_deep_cache_by_id(self, channel_id: str) -> None:
        """Play channel by ID with deep-cache ("Buffer without limit") mode.

        Mirrors ``play_channel_open_ended_buffer_by_id`` but passes
        ``deep_buffer=True`` so mpv also records the raw stream to disk (a
        scratch ``.ts`` file, purged when this instance stops/relaunches) on
        top of the open-ended disk-backed cache. VOD-only — the
        ``play_deep_cache`` menu action is gated to movie/series in
        ``channel_menu.py``, and for SERIES the normal drill-in is used (a
        series has no single stream to deep-buffer).

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
            self.play_media(channel, deep_buffer=True)

    def play_channel_from_beginning_by_id(self, channel_id: str) -> None:
        """Play channel by ID, forcing playback to start at position 0.

        Overrides the ``config.playback_resume_mode`` setting and any saved resume
        position for this one play — the resume position in the DB is unchanged.
        For SERIES channels the normal drill-in is used.

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
            self.play_media(channel, start_override=0)

    def play_channel_resume_by_id(self, channel_id: str) -> None:
        """Play channel by ID, forcing resume from the saved watch_progress position.

        Overrides the ``config.playback_resume_mode`` setting — used when the user
        explicitly chooses "Resume from M:SS" despite the global "Start from
        beginning" default.  For SERIES channels the normal drill-in is used.

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
            watch_progress = int(getattr(channel, "watch_progress", 0) or 0)
            self.play_media(channel, start_override=watch_progress)

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

        # Update channel list model in-place — the model emits dataChanged so
        # only that one row re-renders (no full reload needed).
        if hasattr(self, 'channel_model'):
            self.channel_model.update_favorite(channel_id, channel.is_favorite)
