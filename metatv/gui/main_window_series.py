"""Series / episode drill-down and playback mixin for :class:`MainWindow`.

This module holds :class:`_SeriesMixin` — the series/episode drill-down and
playback methods extracted verbatim from ``main_window.py`` as part of the B10
decomposition. It covers the full series drill-down, season/episode tree
population, episode playback (including pre-flight URL validation and mpv
queueing), and episode watched-state toggling.

The methods rely on attributes and sibling methods defined on ``MainWindow``
(e.g. ``self.db``, ``self.play_media``, ``self.player_manager``); they resolve
via ``self``/MRO at runtime, so the split is behaviour-preserving.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QAbstractItemView, QTreeWidgetItem
from loguru import logger

from metatv.core.repositories import RepositoryFactory
from metatv.core.provider_loader import SeriesLoadThread
from metatv.core.repositories.dtos import EpisodeDTO
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme

import re


@dataclass(frozen=True)
class _PlayAllItem:
    """Generic play-all queue item — carries exactly what the player needs.

    Used by :meth:`_SeriesMixin._play_all_items` to represent a channel or episode
    in an arbitrary Play-All selection, with no live ORM state.

    Attributes:
        stream_url: Direct playback URL.
        title:      Display title for the mpv window / notification.
        content_id: DB id used to register the item in ``_watch_tracking``.
        provider_id: Source provider — threaded to ``player_manager`` for
            Split-Streams instance keying.
        media_type: ``"episode"`` or ``"movie"`` / ``"live"`` — controls which
            repository write path watch-progress capture uses.
    """
    stream_url: str
    title: str
    content_id: str
    provider_id: str
    media_type: str = "live"   # most channels are live; callers override for episodes/movies

_SXXEXX = re.compile(r'[-–\s]+S(\d{1,3})E(\d{1,4})[-–\s]*(.*)$', re.IGNORECASE)


def _fmt_missing_ranges(nums: list[int]) -> str:
    """Compress a sorted int list into range labels, e.g. ``[5,6,7,8,9,12] -> "5–9, 12"``."""
    if not nums:
        return ""
    parts: list[str] = []
    start = prev = nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
            continue
        parts.append(str(start) if start == prev else f"{start}–{prev}")
        start = prev = n
    parts.append(str(start) if start == prev else f"{start}–{prev}")
    return ", ".join(parts)


def _clean_episode_title(raw: str, season_num: int, ep_num: int, series_name: str | None) -> str:
    """Strip series name and SxxExx prefix from a raw IPTV episode title."""
    m = _SXXEXX.search(raw)
    if m:
        s, e, after = int(m.group(1)), int(m.group(2)), m.group(3).strip()
        if s == season_num and e == ep_num:
            return after if after else f"Episode {ep_num}"
    if series_name and raw.startswith(series_name):
        remainder = raw[len(series_name):].lstrip(" -–").strip()
        if remainder:
            return remainder
    return raw


def _format_episode_duration(raw: str) -> str:
    """Convert 'HH:MM:SS' → '1h 21m' or '53m'."""
    parts = raw.split(":")
    if len(parts) == 3:
        try:
            h, m = int(parts[0]), int(parts[1])
            return f"{h}h {m}m" if h else f"{m}m"
        except ValueError:
            pass
    return raw


class _SeriesMixin:
    """Series / episode drill-down and playback methods mixed into :class:`MainWindow`."""

    def play_channel(self, item):
        """Play selected channel in external player or drill down into series"""
        logger.info(f"=== play_channel called ===")
        logger.info(f"Item type: {type(item)}")
        logger.info(f"Item text: {item.text() if hasattr(item, 'text') else 'N/A'}")

        try:
            channel_id = item.data(Qt.ItemDataRole.UserRole)
            logger.info(f"Channel ID from item data: {channel_id}")
        except Exception as e:
            logger.error(f"Error getting channel ID: {e}")
            self.status_bar.showMessage(f"Error: Cannot get channel ID - {e}")
            return

        if not channel_id:
            logger.warning("No channel ID found for selected item")
            self.status_bar.showMessage("Cannot play this item - no channel ID")
            return

        # Get channel from database to check media type
        session = self.db.get_session()
        try:
            from metatv.core.models import MediaType

            repos = RepositoryFactory(session)
            channel = repos.channels.get_by_id(channel_id)

            if not channel:
                logger.error(f"Channel not found: {channel_id}")
                self.status_bar.showMessage("Error: Channel not found")
                return

            # Check if this is a series - if so, drill down instead of playing
            if channel.media_type == MediaType.SERIES:
                logger.info(f"Series detected: {channel.name}, drilling down...")
                self.drill_into_series(channel)
                return

            # For live and movies, proceed with playback
            self.play_media(channel)

        except Exception as e:
            logger.error(f"Error in play_channel: {e}")
            self.status_bar.showMessage(f"Error: {e}")
        finally:
            session.close()

    def drill_into_series(self, channel):
        """Drill down into series to show seasons/episodes"""
        logger.info(f"Drilling into series: {channel.name}")
        self.current_series = channel

        # Get provider info
        from metatv.core.models import Provider
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            provider_db = repos.providers.get_by_id(channel.provider_id)

            if not provider_db:
                self.status_bar.showMessage("Error: Provider not found")
                return

            provider = repos.providers.to_model(provider_db)
        finally:
            session.close()

        # Start loading series in background
        load_thread = SeriesLoadThread(
            provider=provider,
            series_id=channel.source_id,
            series_name=channel.name,
            db=self.db
        )
        load_thread.finished.connect(self.on_series_loaded)
        load_thread.progress.connect(lambda msg: self.status_bar.showMessage(msg))

        # Store thread to prevent garbage collection
        self.active_threads.append(load_thread)
        load_thread.start()

        # Show loading notification
        notification_id = self.notification_manager.show_progress(
            title=f"Loading {channel.name}"
        )
        load_thread.notification_id = notification_id

    def on_series_loaded(self, success, message, series_data):
        """Handle series data loaded"""
        thread = self.sender()

        # Dismiss notification
        if hasattr(thread, 'notification_id'):
            if success:
                self.notification_manager.complete_progress(
                    thread.notification_id,
                    f"Loaded {message}"
                )
            else:
                from metatv.core.notifications import NotificationType
                self.notification_manager.update(
                    thread.notification_id,
                    type=NotificationType.ERROR,
                    title="Series Load Failed",
                    message=message,
                    dismissible=True,
                    auto_dismiss_seconds=5
                )

        # Remove thread
        if thread in self.active_threads:
            self.active_threads.remove(thread)

        if not success:
            logger.error(f"Failed to load series: {message}")
            self.status_bar.showMessage(f"Error: {message}")
            return

        # Store series data and switch to series view
        self.series_data = series_data
        self.switch_to_series_view()

    # ── Episode / season watch-state helpers ──────────────────────────────────

    def _partial_pct(self) -> int:
        """Return the partial-watched threshold as an integer percentage (0–100)."""
        return int(getattr(self.config, "watch_partial_threshold", 0.10) * 100)

    def _episode_display_title(self, episode: "EpisodeDTO") -> str:
        """Return the cleaned display title for an episode tree item (column 0 text)."""
        return _clean_episode_title(
            episode.title, episode.season_num, episode.episode_num, episode.series_name
        )

    def _episode_watch_icon(self, episode: "EpisodeDTO") -> "QIcon":
        """Return the watch-state QIcon for the episode's icon lane (column 0 icon).

        Graduated glyph driven by watch_percent, colored by provenance:
        - solid for manual/deliberate watch (last_played_via != 'queue')
        - muted/gray for queue-auto-advanced (last_played_via == 'queue')
        - ``episode_icon`` (plain triangle) for unwatched episodes (no glyph yet)
        - None is never returned — unwatched gets the episode_icon so the lane is
          always meaningful.

        MUST be called on the main thread (builds QIcon via QPixmap on first use).
        """
        _ep_pct = _icons.effective_watch_pct(episode.watch_percent, episode.watch_progress)
        _glyph = _icons.watch_progress_glyph(_ep_pct, episode.watch_completed, self._partial_pct())
        if _glyph:
            return _icons.watch_icon_for_channel(_glyph, episode.last_played_via)
        # Unwatched: render the plain episode_icon (play-triangle) as the lane icon.
        return _icons.watch_icon(_icons.episode_icon, muted=True)

    def _episode_icon_text(self, episode: "EpisodeDTO") -> str:
        """Return the text column-0 value for an episode tree item (title only).

        The watch indicator is no longer embedded in the text -- it is rendered
        as a QIcon via column 0's icon slot (see _episode_watch_icon).
        """
        return self._episode_display_title(episode)

    def _season_glyph(self, episode_dtos: "list[EpisodeDTO]") -> str:
        """Derive the season-level watch indicator from its episodes.

        ✓  all episodes watch_completed
        ◐  some episodes watch_completed (partial season)
        ""  none completed (no season-level glyph shown)
        """
        if not episode_dtos:
            return ""
        completed = sum(1 for ep in episode_dtos if ep.watch_completed)
        if completed == len(episode_dtos):
            return f" {_icons.watched_icon}"
        if completed > 0:
            return f" {_icons.partial_watched_icon}"
        return ""

    def _season_label(self, season_name: Optional[str], episode_dtos: "list[EpisodeDTO]") -> str:
        """Compose the season column-0 text including any watch-rollup glyph."""
        glyph = self._season_glyph(episode_dtos)
        return f"{_icons.season_icon}{glyph} {season_name or '?'}"

    def _update_episode_item_icon(self, item: "QTreeWidgetItem", episode: "EpisodeDTO") -> None:
        """Rewrite the column-0 text of an episode tree item in-place.

        The EpisodeDTO stored in UserRole is immutable (frozen dataclass).  After a
        mark_watched call we build a *new* DTO from the updated fields and store it so
        the item's UserRole data stays consistent with what's displayed.
        """
        item.setText(0, self._episode_icon_text(episode))
        item.setIcon(0, self._episode_watch_icon(episode))

    def _update_season_item_icon(self, season_item: "QTreeWidgetItem") -> None:
        """Re-derive the season-level watch glyph and rewrite column-0 in-place.

        Reads each child episode item's current UserRole EpisodeDTO to compute
        completion stats — no DB query needed.
        """
        child_dtos: list[EpisodeDTO] = []
        for i in range(season_item.childCount()):
            child = season_item.child(i)
            child_data = child.data(0, Qt.ItemDataRole.UserRole)
            if child_data and child_data.get("type") == "episode":
                child_dtos.append(child_data["data"])
        season_data = season_item.data(0, Qt.ItemDataRole.UserRole)
        season_dto = season_data.get("data") if season_data else None
        season_name = season_dto.name if season_dto is not None else None
        season_item.setText(0, self._season_label(season_name, child_dtos))

    def _find_episode_items(self) -> "list[tuple[QTreeWidgetItem, QTreeWidgetItem]]":
        """Collect all (season_item, episode_item) pairs currently in the tree."""
        pairs: list[tuple[QTreeWidgetItem, QTreeWidgetItem]] = []
        root = self.series_tree.invisibleRootItem()
        for si in range(root.childCount()):
            season_item = root.child(si)
            for ei in range(season_item.childCount()):
                ep_item = season_item.child(ei)
                pairs.append((season_item, ep_item))
        return pairs

    # ── Tree population ────────────────────────────────────────────────────────

    def populate_series_tree(self):
        """Populate the series tree widget with seasons and episodes."""
        self.series_tree.clear()

        if not self.series_data:
            logger.warning("No series data available for tree population")
            return

        # Get seasons and episodes from database.
        # Note: series_id in SeasonDB is the provider's source_id, not the database UUID.
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            # Use get_seasons_dto so no live ORM object crosses the session boundary —
            # the returned SeasonDTOs are plain frozen dataclasses, safe post-session.
            seasons = repos.seasons.get_seasons_dto(
                series_id=self.current_series.source_id,
                provider_id=self.current_series.provider_id
            )

            logger.info(f"Found {len(seasons)} seasons in database for series {self.current_series.source_id}")

            # Non-contiguous season numbers (e.g. 1-4 then jumps to 10) are genuine
            # provider catalog gaps — verified via `inspect_series --live`, not a load
            # error. Surface a muted note so the jump isn't mysterious to the user.
            _nums = sorted({s.season_num for s in seasons})
            _missing = [n for n in range(_nums[0], _nums[-1] + 1) if n not in set(_nums)] if _nums else []
            if _missing:
                gap_item = QTreeWidgetItem(self.series_tree)
                gap_item.setFirstColumnSpanned(True)
                gap_item.setText(
                    0,
                    f"{_icons.notification_warning_icon}  Seasons {_fmt_missing_ranges(_missing)} "
                    f"not provided by this source",
                )
                gap_item.setForeground(0, QColor(_theme.COLOR_MUTED))
                gap_item.setFlags(gap_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)

            total_episodes = 0

            for season in seasons:
                # Get episodes as DTOs first — they're needed for the season glyph.
                episode_dtos = repos.episodes.get_episodes_dto_by_season(season_id=season.id)
                total_episodes += len(episode_dtos)

                # Create season item with derived watch rollup glyph.
                season_item = QTreeWidgetItem(self.series_tree)
                season_item.setText(0, self._season_label(season.name, episode_dtos))
                season_item.setText(1, f"{season.episode_count} episodes")

                # Pre-extracted rating lives directly on the DTO (no raw_data access needed).
                if season.rating:
                    season_item.setText(3, f"{self.rating_star_icon} {season.rating}")

                # Store the SeasonDTO directly — no live ORM object in UserRole data.
                season_item.setData(
                    0, Qt.ItemDataRole.UserRole,
                    {"type": "season", "data": season}
                )

                logger.debug(f"Added season: {season.name} ({season.episode_count} episodes)")
                logger.debug(f"Found {len(episode_dtos)} episodes for {season.name}")

                for episode in episode_dtos:
                    episode_item = QTreeWidgetItem(season_item)
                    episode_item.setText(0, self._episode_icon_text(episode))
                    episode_item.setIcon(0, self._episode_watch_icon(episode))
                    episode_item.setToolTip(0, episode.title)
                    episode_item.setText(1, f"E{episode.episode_num}")
                    if episode.duration:
                        episode_item.setText(2, _format_episode_duration(episode.duration))
                    if episode.rating:
                        episode_item.setText(3, f"{self.rating_star_icon} {episode.rating}")
                    episode_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "episode", "data": episode})

                # Initially collapse seasons.
                season_item.setExpanded(False)

            # Update stats label with season/episode counts.
            if len(seasons) == 0:
                self.stats_label.setText("No items to display")
            else:
                season_word = "item" if len(seasons) == 1 else "items"
                episode_word = "episode" if total_episodes == 1 else "episodes"
                self.stats_label.setText(f"Showing {len(seasons)} {season_word} · {total_episodes} {episode_word}")
        finally:
            session.close()

    def on_tree_item_expanded(self, item):
        """Handle tree item expanded (no-op, using native arrows)"""
        pass

    def on_tree_item_collapsed(self, item):
        """Handle tree item collapsed (no-op, using native arrows)"""
        pass

    def play_series_item(self, item, column):
        """Handle double-click on series tree item"""
        data = item.data(0, Qt.ItemDataRole.UserRole)

        if not data:
            logger.warning("Double-click on tree item with no UserRole data")
            return

        item_type = data.get("type")
        logger.info(f"Double-clicked tree item: type={item_type}, expanded={item.isExpanded()}")

        if item_type == "season":
            # Toggle expand/collapse on double-click
            new_state = not item.isExpanded()
            item.setExpanded(new_state)
            logger.info(f"Toggled season expansion: {new_state}")
        elif item_type == "episode":
            # Play episode
            episode = data["data"]
            self.play_episode(episode)

    def play_episode(self, episode, queue_season: bool | None = None):
        """Play an episode and optionally queue subsequent episodes.

        Args:
            episode: The :class:`~metatv.core.repositories.dtos.EpisodeDTO` to play.
            queue_season: Per-play override for season autoplay.
                ``None`` (default) → respect ``config.autoplay_season_episodes``.
                ``False`` → play this episode only, no queue regardless of config.
                ``True`` → always queue subsequent episodes regardless of config.
        """
        logger.info(f"Playing episode: {episode.title}")

        if not episode.stream_url:
            self.status_bar.showMessage("Error: No stream URL for episode")
            return

        self.status_bar.showMessage(f"Playing: {episode.title}")

        # Resolve the effective season-queue flag:
        #   explicit True/False overrides config; None defers to config.
        if queue_season is None:
            _should_queue = self.config.autoplay_season_episodes
        else:
            _should_queue = queue_season

        # Record playback
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)

            repos.episodes.mark_played(episode.id)

            logger.info(f"Episode playback recorded: {episode.title}")
            logger.info(f"  Episode series_id: {episode.series_id}")
            logger.info(f"  Episode provider_id: {episode.provider_id}")

            parent_channel = repos.channels.get_by_source_id(
                provider_id=episode.provider_id,
                source_id=episode.series_id
            )

            if parent_channel:
                repos.channels.mark_played(parent_channel.id)
                logger.info(f"Updated parent series playback: {parent_channel.name} (play count: {parent_channel.play_count})")
            else:
                logger.warning(f"Could not find parent channel for episode. series_id={episode.series_id}, provider_id={episode.provider_id}")

            episodes_to_queue = []
            if _should_queue and episode.season_id:
                # Use DTOs — no ORM objects escape the session boundary
                all_episode_dtos = repos.episodes.get_episodes_dto_by_season(season_id=episode.season_id)
                episodes_to_queue = [
                    ep for ep in all_episode_dtos
                    if ep.episode_num > episode.episode_num
                ]
                episodes_to_queue.sort(key=lambda ep: ep.episode_num)
                if episodes_to_queue:
                    episode_range = f"E{episodes_to_queue[0].episode_num}-E{episodes_to_queue[-1].episode_num}"
                    logger.info(f"Will queue {len(episodes_to_queue)} subsequent episodes: {episode_range}")
                    logger.debug(f"Queue list: {[f'E{ep.episode_num}: {ep.title}' for ep in episodes_to_queue]}")
        finally:
            session.close()

        # Register this episode for watch-progress capture (same seam as movies, Slice 3a).
        # When subsequent episodes are queued, the tracking entry holds the full ordered
        # queue so _bg_capture_watch can follow mpv's playlist-pos and record progress
        # against the episode that is *actually* playing — not always the started one.
        if not hasattr(self, "_watch_tracking"):
            self._watch_tracking = {}
        _watch_key = self.player_manager.resolve_key(episode.provider_id)
        if episodes_to_queue:
            # Multi-episode queue: store full playlist in order (started ep first).
            _queue = [{"content_id": episode.id}] + [
                {"content_id": ep.id} for ep in episodes_to_queue
            ]
            self._watch_tracking[_watch_key] = {
                "media_type": "episode",
                "played_via": "manual",     # for the started episode (playlist index 0)
                "queue": _queue,
                "last_seen_pos": 0,         # mpv playlist-pos last finalized through
            }
        else:
            # Single episode: flat dict (unchanged from Slice 3a).
            self._watch_tracking[_watch_key] = {
                "content_id": episode.id,
                "media_type": "episode",
                "played_via": "manual",
            }
        self._start_watch_capture()

        # Update UI lists in real-time
        self.load_history()
        self.load_favorites()

        # Launch player with first episode
        self.launch_player_for_episode(
            episode.stream_url, episode.title, episodes_to_queue,
            provider_id=episode.provider_id,
        )

    def _play_all_items(self, items: "list[_PlayAllItem]") -> None:
        """Play the first item and queue the rest — generalized Play-All helper.

        This is the single implementation of "play first + queue the rest" shared
        by both the channel-list multi-select action and the episode-tree multi-select
        action.  The episode ``autoplay_season_episodes`` path in
        :meth:`play_episode` uses the same ``_watch_tracking`` queue shape and the
        same ``launch_player_for_episode`` launcher so that watch-progress capture
        (Slice 3b-1) correctly follows mpv's playlist position for all queued items.

        Single-item list: plays normally (no queue registered).

        Args:
            items: Ordered list of :class:`_PlayAllItem` instances.  The first is
                played immediately; the rest are appended to mpv's playlist.
                Items without a ``stream_url`` are silently skipped.
        """
        if not items:
            return

        # Filter items with no stream URL before indexing.
        playable = [it for it in items if it.stream_url]
        if not playable:
            self.status_bar.showMessage("No playable URLs in selection")
            return

        first = playable[0]
        rest = playable[1:]

        logger.info(
            f"Play All: playing {first.title!r}, queuing {len(rest)} item(s)"
        )

        # Register watch-tracking BEFORE launching so the checkpoint timer starts
        # immediately — same pattern as play_episode.
        if not hasattr(self, "_watch_tracking"):
            self._watch_tracking = {}
        _watch_key = self.player_manager.resolve_key(first.provider_id)
        if rest:
            # Multi-item queue: the _bg_capture_watch queued-branch follows
            # playlist-pos and writes progress against the *current* item.
            _queue = [{"content_id": first.content_id}] + [
                {"content_id": it.content_id} for it in rest
            ]
            self._watch_tracking[_watch_key] = {
                "media_type": first.media_type,
                "played_via": "manual",
                "queue": _queue,
                "last_seen_pos": 0,
            }
        else:
            # Single-item selection: flat dict (same as play_episode single-ep branch).
            self._watch_tracking[_watch_key] = {
                "content_id": first.content_id,
                "media_type": first.media_type,
                "played_via": "manual",
            }
        self._start_watch_capture()

        # Update UI sidebar lists so history reflects the play immediately.
        self.load_history()
        self.load_favorites()

        # Delegate the actual launch to the existing episode launcher which already
        # handles pre-flight URL validation, the "Loading" notification, Split-Streams
        # keying, and the playback-health readout.  The queue_episodes list is typed
        # as EpisodeDTOs in the launcher's signature but _do_launch_episode only reads
        # .stream_url and .title — any object with those attributes works.
        self.launch_player_for_episode(
            first.stream_url, first.title, rest,
            provider_id=first.provider_id,
        )

    def launch_player_for_episode(self, stream_url, title, queue_episodes=None, provider_id: str = ""):
        """Launch media player for an episode and queue subsequent episodes.

        Pre-flight validates the stream URL in a background thread before handing
        off to mpv, so text error responses (e.g. "not available") surface as an
        in-app notification rather than a black mpv window.

        Args:
            stream_url: The episode's playback URL.
            title: Episode title used for the mpv window title and notification.
            queue_episodes: Optional list of subsequent EpisodeDTOs to append-play.
            provider_id: The episode's source provider id — threaded to
                player_manager.play() to honour Split-Streams keying.
        """
        if not self.player_manager.is_available():
            logger.error("No media player available")
            self.status_bar.showMessage("Error: No media player found. Please install mpv.")
            return

        safe_title = title if not title.startswith("http") else "…"
        display_title = (safe_title[:55] + "…") if len(safe_title) > 55 else safe_title
        notif_id = self.notification_manager.show(
            title="Loading Episode",
            message=display_title,
            type="info",
            auto_dismiss_ms=6000,
        )

        def _preflight():
            ok, err = self.validate_stream_url(stream_url, timeout=6)
            return ok, err

        def _on_preflight_done(future):
            try:
                ok, err = future.result()
            except Exception as exc:
                logger.warning(f"Episode preflight check failed: {exc}")
                ok, err = True, None   # assume valid on unexpected errors

            if not ok:
                detail = err if err else "Stream did not respond"
                logger.warning(f"Episode stream unavailable: {title!r} — {detail}")
                self._episode_failed.emit(notif_id, title, detail, stream_url)
                return

            # Carry provider_id in the signal payload so each launch threads its
            # own source key — a shared attr would be clobbered by an overlapping
            # launch and play/track the episode under the wrong mpv key.
            self._episode_ready.emit(notif_id, stream_url, title, queue_episodes, provider_id)

        future = self.executor.submit(_preflight)
        future.add_done_callback(_on_preflight_done)

    def _on_episode_stream_unavailable(self, notif_id: str, title: str, detail: str, stream_url: str = "") -> None:
        from PyQt6.QtWidgets import QApplication
        from metatv.core.channel_name_utils import parse_channel_name
        # Dismiss the old "Checking stream" notif — safe even if it already auto-dismissed
        self.notification_manager.dismiss(notif_id)
        if title and not title.startswith("http"):
            p = parse_channel_name(title)
            safe_title = p.bare_name or title
        else:
            safe_title = ""
        _msg = f"{safe_title}\n{detail}".strip() if safe_title else detail
        self.notification_manager.show(
            title="Stream Unavailable",
            message=_msg,
            type="error",
            dismissible=True,
            auto_dismiss_seconds=None,
            actions=[("Copy Error", lambda t=title, u=stream_url, d=detail:
                QApplication.clipboard().setText(f"{t}\nURL: {u}\nError: {d}"))],
        )
        self.status_bar.showMessage(f"Stream unavailable: {title}")
        if stream_url and hasattr(self, "stream_retry_manager"):
            # Use stream_url as a stable ID for the retry entry
            self.stream_retry_manager.add_failure(stream_url, title, stream_url, detail)

    def _do_launch_episode(self, notif_id, stream_url, title, queue_episodes, provider_id="") -> None:
        """Actually launch mpv after a successful preflight check (called on main thread).

        Threads the provider_id carried in the _episode_ready signal payload to
        player_manager.play() so Split-Streams keying works correctly — each
        launch carries its own value, so an overlapping launch can't clobber it.
        Also passes per-item titles to the queue so the mpv window title updates
        as each episode starts — not just for the first one.
        """
        self.notification_manager.dismiss(notif_id)
        logger.info(f"Playing first episode: {title}")
        if self.player_manager.play(stream_url, title, provider_id=provider_id):
            # Begin polling mpv for the live playback-health readout (the episode
            # path doesn't go through play_media, so it must arm the readout too).
            self._start_playback_health()

            # Queue subsequent episodes if provided
            if queue_episodes:
                from metatv.core.players.base import QueueMode
                queued_count = 0

                logger.info(f"Queueing {len(queue_episodes)} subsequent episodes...")
                for ep in queue_episodes:
                    if ep.stream_url:
                        if self.player_manager.queue(
                            ep.stream_url, ep.title, QueueMode.APPEND,
                            provider_id=provider_id,
                        ):
                            queued_count += 1
                            logger.debug(f"Queued E{getattr(ep, 'episode_num', '?')}: {ep.title}")
                        else:
                            logger.warning(f"Failed to queue E{getattr(ep, 'episode_num', '?')}: {ep.title}")

                if queued_count > 0:
                    status_msg = f"Playing: {title} (+{queued_count} queued)"
                    logger.info(f"Successfully queued {queued_count}/{len(queue_episodes)} episodes")
                else:
                    status_msg = f"Playing: {title}"
            else:
                status_msg = f"Playing: {title}"

            QTimer.singleShot(2000, lambda: self.status_bar.showMessage(status_msg))
        else:
            logger.error(f"Failed to play episode: {title}")
            self.status_bar.showMessage(f"Error playing: {title}")


    def show_series_context_menu(self, position):
        """Show context menu for series tree items.

        Supports multi-select for episode items — if more than one episode is
        selected when the menu is triggered the Mark actions apply to all of them.
        The right-clicked item is always included even if it was not previously
        part of the selection.
        """
        item = self.series_tree.itemAt(position)
        if not item:
            return

        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return

        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QAction

        menu = QMenu(self)

        if data["type"] == "episode":
            # Collect all selected episode items (multi-select aware).
            selected_items = self.series_tree.selectedItems()
            selected_episode_items = [
                it for it in selected_items
                if (it.data(0, Qt.ItemDataRole.UserRole) or {}).get("type") == "episode"
            ]
            # The right-clicked item must always be in scope.
            if item not in selected_episode_items:
                selected_episode_items = [item]

            # Determine the effective target state from the triggered item.
            episode = data["data"]
            target_watched = not episode.is_watched

            label_suffix = f" ({len(selected_episode_items)} episodes)" if len(selected_episode_items) > 1 else ""
            if target_watched:
                mark_action = QAction(f"{_icons.watched_icon} Mark as Watched{label_suffix}", self)
            else:
                mark_action = QAction(f"{_icons.episode_icon} Mark as Unwatched{label_suffix}", self)

            mark_action.triggered.connect(
                lambda: self._toggle_episodes_watched(selected_episode_items, target_watched)
            )
            menu.addAction(mark_action)

            if len(selected_episode_items) == 1:
                # Single selection — offer Play at the top.
                menu.insertAction(mark_action, self._make_play_episode_action(menu, episode))
                # "Play this episode only" appears below "Play Episode" when
                # autoplay_season_episodes is on — it's the per-play opt-out of
                # the autoqueue.  When autoplay is off, the primary action already
                # plays a single episode so the extra action would be redundant.
                if self.config.autoplay_season_episodes:
                    menu.insertAction(
                        mark_action,
                        self._make_play_episode_only_action(menu, episode),
                    )
                menu.insertSeparator(mark_action)
            else:
                # Multi-select: offer Play All Selected above the mark action.
                n = len(selected_episode_items)
                play_all_action = QAction(
                    f"{_icons.play_all_icon} Play All Selected ({n})", self
                )
                play_all_action.setToolTip(
                    "Play first selected episode, queue the rest in tree order"
                )
                play_all_action.triggered.connect(
                    lambda: self._play_all_selected_episodes(selected_episode_items)
                )
                menu.insertAction(mark_action, play_all_action)
                menu.insertSeparator(mark_action)

        elif data["type"] == "season":
            # Determine the season watched state from its children.
            child_dtos: list[EpisodeDTO] = []
            for i in range(item.childCount()):
                child = item.child(i)
                cd = child.data(0, Qt.ItemDataRole.UserRole)
                if cd and cd.get("type") == "episode":
                    child_dtos.append(cd["data"])

            all_completed = child_dtos and all(ep.watch_completed for ep in child_dtos)

            if all_completed:
                mark_season_action = QAction(
                    f"{_icons.episode_icon} Mark Season as Unwatched", self
                )
                mark_season_action.triggered.connect(
                    lambda: self._mark_season_watched(item, watched=False)
                )
            else:
                mark_season_action = QAction(
                    f"{_icons.watched_icon} Mark Season as Watched", self
                )
                mark_season_action.triggered.connect(
                    lambda: self._mark_season_watched(item, watched=True)
                )
            menu.addAction(mark_season_action)
            menu.addSeparator()

            expand_action = QAction("Expand All Episodes", self)
            expand_action.triggered.connect(lambda: item.setExpanded(True))
            menu.addAction(expand_action)

            collapse_action = QAction("Collapse", self)
            collapse_action.triggered.connect(lambda: item.setExpanded(False))
            menu.addAction(collapse_action)

        menu.exec(self.series_tree.viewport().mapToGlobal(position))

    def _make_play_episode_action(self, parent_menu, episode: "EpisodeDTO"):
        """Create a Play Episode action for the context menu."""
        from PyQt6.QtGui import QAction
        play_action = QAction(f"{_icons.play_icon} Play Episode", parent_menu)
        play_action.triggered.connect(lambda: self.play_episode(episode))
        return play_action

    def _make_play_episode_only_action(self, parent_menu, episode: "EpisodeDTO"):
        """Create a 'Play this episode only' action — per-play autoqueue opt-out.

        Calls :meth:`play_episode` with ``queue_season=False`` so the rest of the
        season is NOT queued regardless of the ``autoplay_season_episodes`` setting.
        """
        from PyQt6.QtGui import QAction
        action = QAction(f"{_icons.play_icon} Play This Episode Only", parent_menu)
        action.setToolTip("Play just this episode without queuing the rest of the season")
        action.triggered.connect(lambda: self.play_episode(episode, queue_season=False))
        return action

    def _play_all_selected_episodes(
        self,
        episode_items: "list[QTreeWidgetItem]",
    ) -> None:
        """Play all selected episode tree items via :meth:`_play_all_items`.

        Converts the selected ``QTreeWidgetItem`` list (in tree order as returned
        by ``selectedItems()``) to :class:`_PlayAllItem` values and delegates to
        the generic helper.  Items whose ``EpisodeDTO`` has no ``stream_url`` are
        skipped silently.

        Args:
            episode_items: Selected episode tree-widget items.  Each must carry a
                ``UserRole`` dict ``{"type": "episode", "data": EpisodeDTO}``.
        """
        play_items: list[_PlayAllItem] = []
        for tree_item in episode_items:
            d = tree_item.data(0, Qt.ItemDataRole.UserRole)
            if not d or d.get("type") != "episode":
                continue
            ep: EpisodeDTO = d["data"]
            if not ep.stream_url:
                continue
            play_items.append(_PlayAllItem(
                stream_url=ep.stream_url,
                title=ep.title or f"Episode {ep.episode_num}",
                content_id=ep.id,
                provider_id=ep.provider_id,
                media_type="episode",
            ))
        self._play_all_items(play_items)

    def toggle_episode_watched(self, episode: "EpisodeDTO") -> None:
        """Toggle a single episode's watched status.

        Kept for backwards compatibility; delegates to _toggle_episodes_watched.
        """
        item_pair = next(
            ((si, ei) for si, ei in self._find_episode_items()
             if (ei.data(0, Qt.ItemDataRole.UserRole) or {}).get("data", None) is episode),
            None,
        )
        if item_pair:
            self._toggle_episodes_watched([item_pair[1]], not episode.is_watched)
        else:
            # Fallback: no tree item found — just write to DB (should not happen).
            with self.db.session_scope() as session:
                RepositoryFactory(session).episodes.mark_watched(episode.id, not episode.is_watched)

    def _toggle_episodes_watched(
        self,
        episode_items: "list[QTreeWidgetItem]",
        watched: bool,
    ) -> None:
        """Mark the given episode tree items as watched/unwatched in-place.

        Writes all watch fields coherently (Bug 1 fix), then updates just the
        affected tree item icon(s) without rebuilding the whole tree (Bug 3 fix).
        Also refreshes any parent season node's rollup glyph.
        """
        if not episode_items:
            return

        episode_ids = []
        for ep_item in episode_items:
            d = ep_item.data(0, Qt.ItemDataRole.UserRole)
            if d and d.get("type") == "episode":
                episode_ids.append(d["data"].id)

        if not episode_ids:
            return

        # Persist to DB.
        with self.db.session_scope() as session:
            RepositoryFactory(session).episodes.mark_watched_bulk(episode_ids, watched)

        # Re-read each affected episode as a fresh DTO and update its tree item in-place.
        season_items_to_refresh: set[int] = set()  # id() of QTreeWidgetItem to refresh
        with self.db.session_scope() as session:
            repo = RepositoryFactory(session).episodes
            for ep_item in episode_items:
                d = ep_item.data(0, Qt.ItemDataRole.UserRole)
                if not d or d.get("type") != "episode":
                    continue
                old_dto: EpisodeDTO = d["data"]
                # Build an updated DTO from the new state (no ORM object escapes the session).
                new_dto = EpisodeDTO(
                    id=old_dto.id,
                    episode_num=old_dto.episode_num,
                    season_num=old_dto.season_num,
                    title=old_dto.title,
                    series_name=old_dto.series_name,
                    stream_url=old_dto.stream_url,
                    duration=old_dto.duration,
                    is_watched=watched,
                    rating=old_dto.rating,
                    series_id=old_dto.series_id,
                    provider_id=old_dto.provider_id,
                    season_id=old_dto.season_id,
                    watch_progress=0 if not watched else old_dto.watch_progress,
                    watch_completed=watched,
                    watch_percent=100 if watched else 0,
                    # Manual toggle = deliberate action → SOLID icon (not muted/gray).
                    # Must match EpisodeRepository.mark_watched_bulk which also sets
                    # last_played_via="manual" — the in-place DTO must not disagree.
                    last_played_via="manual" if watched else None,
                )
                ep_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "episode", "data": new_dto})
                self._update_episode_item_icon(ep_item, new_dto)

                # Mark the parent season for rollup refresh.
                parent = ep_item.parent()
                if parent is not None:
                    season_items_to_refresh.add(id(parent))
                    # Store the actual object keyed by id().
                    if not hasattr(self, "_season_item_map"):
                        self._season_item_map: dict[int, QTreeWidgetItem] = {}
                    self._season_item_map[id(parent)] = parent

        # Refresh affected season rollup glyphs.
        for sid in season_items_to_refresh:
            season_item = getattr(self, "_season_item_map", {}).get(sid)
            if season_item is not None:
                self._update_season_item_icon(season_item)
        self._season_item_map = {}  # clear after use

        logger.info(
            f"Toggled {len(episode_ids)} episode(s) as {'watched' if watched else 'unwatched'} in-place"
        )

    def _mark_season_watched(self, season_item: "QTreeWidgetItem", watched: bool) -> None:
        """Mark all episodes in a season as watched/unwatched.

        Updates the season node's rollup glyph and each episode item in-place.
        """
        episode_items: list[QTreeWidgetItem] = []
        for i in range(season_item.childCount()):
            child = season_item.child(i)
            if (child.data(0, Qt.ItemDataRole.UserRole) or {}).get("type") == "episode":
                episode_items.append(child)
        self._toggle_episodes_watched(episode_items, watched)
