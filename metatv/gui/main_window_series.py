"""Series / episode drill-down and tree mixin for :class:`MainWindow`.

This module holds :class:`_SeriesMixin` — the series/episode drill-down,
season/episode tree population, and watch-state toggling extracted verbatim
from ``main_window.py`` as part of the B10 decomposition. The PLAYBACK family
(``play_channel``, ``play_episode``, ``launch_player_for_episode``, and their
siblings) moved out to :mod:`~metatv.gui.main_window_series_playback`
(``_SeriesPlaybackMixin``, DEBT-1c) once this file reached its code-health
ratchet ceiling; the four series-monitor leftovers DEBT-1b left on
``MainWindow`` (``_monitor_series``, ``_on_details_monitor_toggled``,
``_on_mark_series_seen``, ``_backfill_series_display_titles``) moved back
in here in the same slice, now that there's room.

The methods rely on attributes and sibling methods defined on ``MainWindow``
(e.g. ``self.db``, ``self.play_media``, ``self.player_manager``); they resolve
via ``self``/MRO at runtime, so the split is behaviour-preserving.
"""

from __future__ import annotations

import dataclasses
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QTreeWidgetItem
from loguru import logger

from metatv.core.repositories import RepositoryFactory
from metatv.core.provider_loader import SeriesLoadThread
from metatv.core.repositories.dtos import EpisodeDTO
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme

import re

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
    """Series / episode drill-down, tree, and watch-state methods mixed into :class:`MainWindow`.

    ``play_channel`` also drills into a series (via :meth:`drill_into_series`),
    but the method itself — and the rest of the playback family — now lives on
    :class:`~metatv.gui.main_window_series_playback._SeriesPlaybackMixin`.
    """

    def drill_into_series(self, channel):
        """Drill down into series to show seasons/episodes"""
        logger.info(f"Drilling into series: {channel.name}")
        self.current_series = channel

        # Get provider info
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            provider_db = repos.providers.get_by_id(channel.provider_id)

            if not provider_db:
                self.status("Error: Source not found", ms=0, level="error")
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
        load_thread.progress.connect(lambda msg: self.status(msg, ms=0))

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
            self.status(f"Error: {message}", ms=0, level="error")
            return

        # Store series data and switch to series view
        self.series_data = series_data

        # Opening a monitored series' season/episode tree is itself an
        # acknowledgment — clear its sticky "unseen" badge the same as the
        # explicit "Mark seen" action (config.clear_unseen).  Gated on
        # is_series_monitored so a non-monitored series drill-in is a no-op, and
        # placed on the SUCCESS path only (a failed load never shows the tree, so
        # it must not clear the badge).  The toast itself already auto-dismissed
        # on its own timer — this only clears the persistent sidebar badge.
        # Uses the composite _refresh_alert_visibility chokepoint (not the
        # narrower _refresh_vod_alerts_section) so a drill-in reached via the
        # Watch Queue's own "Alerts Matched" matched-series row also clears
        # that row's badge, not just the separate Watch Alerts section's list.
        series_id = getattr(self.current_series, "id", None)
        if series_id and self.config.is_series_monitored(series_id):
            self.config.clear_unseen(series_id)
            self._refresh_alert_visibility()

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

    def on_tree_item_collapsed(self, item):
        """Handle tree item collapsed (no-op, using native arrows)"""

    def _on_series_tree_selection(self, item, previous=None):
        """Single-click / keyboard selection in the series tree → fill the details pane.

        Episode rows show episode details (series poster/plot as fallback); season or
        header/gap rows revert the pane to the series' own details.  Rows without a
        ``dict`` UserRole (the season-gap note) never crash — they fall through to the
        revert branch.  Double-click still plays (``play_series_item``); this only
        ADDS single-click-to-details.

        Args:
            item: The now-current ``QTreeWidgetItem`` (or ``None`` when cleared).
            previous: The previously-current item (unused; ``currentItemChanged`` arg).
        """
        series = getattr(self, "current_series", None)
        if item is None or series is None:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        item_type = data.get("type") if isinstance(data, dict) else None

        if item_type == "episode":
            # Pass the CLEANED title (same as the tree row shows) so the byline never
            # reads the raw "Series - SxxExx -" form next to a clean tree row.
            episode = data["data"]
            self.details_pane.show_episode(
                episode, series, self._episode_display_title(episode)
            )
            return

        # Season, header/gap, or anything else → show the series root details, but
        # only if the pane has drifted (episode mode or a different channel) so we
        # don't redundantly re-render + re-fetch when it already shows the series.
        pane = self.details_pane
        already_series = (
            getattr(pane, "current_episode", None) is None
            and pane.current_channel is not None
            and getattr(pane.current_channel, "id", None) == getattr(series, "id", None)
        )
        if not already_series:
            pane.show_channel(series)

    def _on_details_play_episode(self) -> None:
        """Play the episode currently shown in the details pane (its Play Episode button).

        Reads the DTO the pane stored in :attr:`DetailsPaneWidget.current_episode`
        and routes it through the existing :meth:`play_episode` chokepoint.  No-op
        when nothing is stored (defensive — the button only shows in episode mode).
        """
        episode = getattr(self.details_pane, "current_episode", None)
        if episode is not None:
            self.play_episode(episode)

    def _on_details_resume_episode(self) -> None:
        """Resume the episode currently shown in the details pane (its Resume button).

        Mirrors :meth:`_on_details_play_episode` but threads the episode's own
        stored ``watch_progress`` through as the launch start position, so
        playback picks up where the user left off instead of from the
        beginning.  No-op when nothing is stored (defensive — the button only
        shows in episode mode with a saved position).
        """
        episode = getattr(self.details_pane, "current_episode", None)
        if episode is not None:
            start_seconds = int(getattr(episode, "watch_progress", 0) or 0)
            self.play_episode(episode, start_seconds=start_seconds)

    def _on_episode_stream_unavailable(
        self,
        notif_id: str,
        title: str,
        detail: str,
        stream_url: str = "",
        queue_episodes=None,
        provider_id: str = "",
        start_seconds: int = 0,
        episode_id: str = "",
        series_id: str = "",
        media_type: str = "",
    ) -> None:
        """Main-thread slot: show the episode failure toast.

        Mirrors the channel path's failure toast (``main_window_streaming.py``
        ``_on_stream_ready``) as it actually behaves today, on both counts:

        * **"Play Anyway" is offered unconditionally**, not just for advisory
          auth/gating codes — it is a general escape hatch over the pre-flight
          check. mpv negotiates differently from ``requests`` and routinely
          plays a stream the pre-flight rejected, so the user always gets the
          override.
        * **Every failure is recorded** with ``stream_retry_manager``, advisory
          codes included. That gate was deliberately removed on the channel
          path (roadmap S3, #227): channels that return 511 forever never
          graduated to "dead" while advisory errors were skipped, so the
          ledger never learned about the very streams it existed to track.

        ``episode_id``/``series_id`` (PLAY-13) are carried through only so
        "Play Anyway" can pass them straight to ``_do_launch_episode`` — the
        preflight failure itself is never recorded as a play. ``media_type``
        (D53) rides the same way — a failed Play-All item that the user
        overrides with "Play Anyway" still needs it so the eventual launch
        records through the right seam (``_record_play`` vs
        ``_record_episode_play``) instead of silently skipping recording.
        """
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

        # Play Anyway first, always — the pre-flight check is advisory in
        # practice (mpv often plays what it rejects), so the override is never
        # withheld. Same ordering and rationale as the channel path.
        actions = []
        actions.append((
            "Play Anyway",
            lambda _nid=notif_id, _u=stream_url, _t=title, _q=queue_episodes,
                   _p=provider_id, _s=start_seconds, _eid=episode_id, _sid=series_id,
                   _mt=media_type:
                self._do_launch_episode(_nid, _u, _t, _q, _p, _s, _eid, _sid, _mt)
        ))
        actions.append(
            ("Copy Error", lambda t=title, u=stream_url, d=detail:
                QApplication.clipboard().setText(f"{t}\nURL: {u}\nError: {d}"))
        )

        self.notification_manager.show(
            title="Stream Unavailable",
            message=_msg,
            type="error",
            dismissible=True,
            auto_dismiss_seconds=None,
            actions=actions,
        )
        self.status(f"Stream unavailable: {title}", ms=0, level="warn")

        # Record EVERY failure — advisory (401/403/511) included — matching the
        # channel path (roadmap S3, #227). Skipping advisory codes here is what
        # kept permanently-gated streams out of the ledger that exists to
        # surface them.
        if stream_url and hasattr(self, "stream_retry_manager"):
            # Use stream_url as a stable ID for the retry entry
            self.stream_retry_manager.add_failure(stream_url, title, stream_url, detail)

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
                # Favorite/Unfavorite — episode-grain (Slice 2B). Single-selection
                # only, mirroring the Play Episode action's single-select scoping;
                # this tree builds its own QMenu rather than routing through
                # channel_menu.py (that registry is ChannelDB-only today).
                menu.insertAction(
                    mark_action, self._make_favorite_episode_action(menu, item, episode)
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

    def _make_favorite_episode_action(self, parent_menu, item: "QTreeWidgetItem", episode: "EpisodeDTO"):
        """Create a Favorite/Unfavorite Episode action for the context menu (Slice 2B).

        Episode-grain favorite — independent of the parent series' own favorite
        star (that stays reachable via the details-pane rail in series/browse mode).
        """
        from PyQt6.QtGui import QAction
        is_fav = bool(getattr(episode, "is_favorite", False))
        label = "Unfavorite Episode" if is_fav else "Favorite Episode"
        glyph = _icons.favorite_icon if is_fav else _icons.unfavorite_icon
        action = QAction(f"{glyph} {label}", parent_menu)
        action.triggered.connect(lambda: self._toggle_episode_favorite(item, episode))
        return action

    def _toggle_episode_favorite(self, item: "QTreeWidgetItem", episode: "EpisodeDTO") -> None:
        """Flip a single episode's favorite flag; patch the tree UserRole in-place
        (so a re-opened context menu shows the correct label) and refresh Favorites.

        Direct session_scope() attribute write — the new status is read back INSIDE
        the block (before commit/expire), so no ORM object crosses the boundary
        (mirrors _FavoritesMixin._toggle_favorite_by_id's shape for channels).
        """
        from dataclasses import replace as _replace
        from metatv.core.database import EpisodeDB

        new_status = None
        with self.db.session_scope() as session:
            ep = session.get(EpisodeDB, episode.id)
            if ep is None:
                return
            ep.is_favorite = not bool(ep.is_favorite)
            new_status = ep.is_favorite
        if new_status is None:
            return

        new_dto = _replace(episode, is_favorite=new_status)
        item.setData(0, Qt.ItemDataRole.UserRole, {"type": "episode", "data": new_dto})

        status = "added to" if new_status else "removed from"
        self.status(f"{episode.title} {status} favorites", ms=0)
        self.load_favorites()

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

        # Persist to DB, then repaint from what was actually stored — the tree
        # is never told what it "should" now show, it re-reads (see
        # refresh_episode_watch_state).  The DTO this used to hand-build from
        # the toggle's own arguments could disagree with the row (its unwatched
        # branch cleared last_played_via while mark_watched_bulk left it), and a
        # freshly constructed EpisodeDTO silently defaulted any field nobody
        # remembered to carry across.
        with self.db.session_scope() as session:
            RepositoryFactory(session).episodes.mark_watched_bulk(episode_ids, watched)
        # Repaint the very items handed in — not whatever the tree can be
        # searched for. The context menu already holds them, and a re-find would
        # silently skip an item that is not currently under the tree's root.
        self._repaint_episode_items([(it.parent(), it) for it in episode_items])
        logger.info(
            f"Toggled {len(episode_ids)} episode(s) as {'watched' if watched else 'unwatched'} in-place"
        )

    def refresh_episode_watch_state(self, episode_ids: "list[str]") -> None:
        """Re-read *episode_ids* watch state from the DB and repaint their rows.

        **The one refresh path for episode watch state.**  Every writer — the
        context menu's mark watched/unwatched, the queue's auto-mark as the
        playlist advances, and both answers to the "Still watching?" prompt —
        ends here rather than telling the tree what to display, so a write that
        happened off-thread while the tree was already on screen cannot leave a
        stale glyph behind (#836).

        A no-op when the series tree was never built or holds none of these
        episodes, so an off-thread writer can call it unconditionally.

        Args:
            episode_ids: Episode DB ids whose stored watch state to re-read.
        """
        if not episode_ids or "series_tree" not in self.__dict__:
            return
        wanted = set(episode_ids)
        matched = []
        for season_item, ep_item in self._find_episode_items():
            d = ep_item.data(0, Qt.ItemDataRole.UserRole)
            if d and d.get("type") == "episode" and d["data"].id in wanted:
                matched.append((season_item, ep_item))
        if not matched:
            return

        self._repaint_episode_items(matched)

    def _repaint_episode_items(self, pairs) -> None:
        """Re-read each ``(season_item, episode_item)`` pair's row and repaint it.

        The shared tail of both refresh entry points — ``refresh_episode_watch_state``
        (which finds the pairs by id) and ``_toggle_episodes_watched`` (which was
        handed them). Reads the STORED state rather than being told what to show,
        so neither caller can paint a glyph the database disagrees with.

        Args:
            pairs: ``(season_item_or_None, episode_item)`` tuples to repaint.
        """
        touched_seasons: list[QTreeWidgetItem] = []
        with self.db.session_scope() as session:
            repo = RepositoryFactory(session).episodes
            for season_item, ep_item in pairs:
                data = ep_item.data(0, Qt.ItemDataRole.UserRole)
                if not data or data.get("type") != "episode":
                    continue
                old_dto: EpisodeDTO = data["data"]
                row = repo.get_by_id(old_dto.id)
                if row is None:
                    continue
                # dataclasses.replace carries every field the row does not own
                # (title, rating, favorite, …) across untouched by construction.
                new_dto = dataclasses.replace(
                    old_dto,
                    is_watched=bool(row.is_watched),
                    watch_completed=bool(row.watch_completed),
                    watch_percent=int(row.watch_percent or 0),
                    watch_progress=int(row.watch_progress or 0),
                    last_played_via=row.last_played_via,
                )
                ep_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "episode", "data": new_dto})
                self._update_episode_item_icon(ep_item, new_dto)
                touched_seasons.append(season_item)

        # Season rollup glyphs are derived from the child items just rewritten.
        for season_item in {id(s): s for s in touched_seasons if s is not None}.values():
            self._update_season_item_icon(season_item)

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

    # ------------------------------------------------------------------
    # Series monitor helpers (DEBT-1b left these on MainWindow; DEBT-1c
    # folds them into _SeriesMixin now that this file has room)
    # ------------------------------------------------------------------

    def _backfill_series_display_titles(self) -> None:
        """Backfill cleaned ``display_title`` + identity fields for monitored series.

        New monitors persist ``display_title``, ``region``, ``language`` (the
        ingestion-computed ``detected_*``) and ``source`` (provider name) at add
        time; this one-time startup backfill covers entries created before that (a
        bounded off-thread lookup for just the incomplete ids — never a large-table
        scan, never an ORM object across the session boundary).  The identity
        fields disambiguate two series that share a cleaned title.  Always ends by
        refreshing the Movies & Series list.
        """
        # An entry needs a top-up when it lacks a display_title OR any identity key
        # is absent.  Key-presence (not truthiness) is the test so a legitimately
        # empty region/language does not re-query on every launch.
        def _needs_backfill(e: dict) -> bool:
            if not e.get("display_title"):
                return True
            return any(k not in e for k in ("region", "language", "source"))

        missing = [
            e.get("series_channel_id")
            for e in self.config.get_monitored_series()
            if _needs_backfill(e) and e.get("series_channel_id")
        ]
        if not missing:
            self._refresh_vod_alerts_section()
            return

        def _query(repos) -> dict:
            # Plain-string fields only (no ORM escapes the session boundary).
            out: dict[str, dict] = {}
            for cid in missing:
                ch = repos.channels.get_by_id(cid)
                if ch is None:
                    continue
                provider = repos.providers.get_by_id(ch.provider_id) if ch.provider_id else None
                out[cid] = {
                    "display_title": ch.detected_title or ch.name or "",
                    "region": ch.detected_region or "",
                    "language": ch.detected_prefix or "",
                    "source": (provider.name if provider else "") or "",
                }
            return out

        def _apply(rows) -> None:
            updates: dict[str, dict] = {}   # ONE save; see ..._many's docstring
            for cid, f in (rows or {}).items():
                updates[cid] = {"region": f["region"], "language": f["language"],
                                "source": f["source"]}
                if f["display_title"]:
                    updates[cid]["display_title"] = f["display_title"]
            self.config.update_monitored_series_many(updates)
            self._refresh_vod_alerts_section()

        self._run_query(_query, _apply, on_error=lambda _e: self._refresh_vod_alerts_section())

    def _monitor_series(self, channel_id: str) -> None:
        """Start a new-episode alert for a series.

        Reads the channel from the DB to populate the config entry, then
        tells SeriesMonitorManager to compute and store the baseline episode count.
        """
        with self.db.session_scope(commit=False) as session:
            from metatv.core.repositories import RepositoryFactory
            repos = RepositoryFactory(session)
            channel = repos.channels.get_by_id(channel_id)
            if not channel:
                logger.warning(f"_monitor_series: channel {channel_id} not found")
                return
            provider = (
                repos.providers.get_by_id(channel.provider_id)
                if channel.provider_id else None
            )
            entry = {
                "series_channel_id": channel_id,
                "source_id": channel.source_id or "",
                "provider_id": channel.provider_id or "",
                "title": channel.name or "",
                # Cleaned title read from the ingestion-computed detected_title, stored
                # so the sidebar/manage-dialog render never re-parses the raw name.
                "display_title": channel.detected_title or channel.name or "",
                # Identity fields (also ingestion-computed) — disambiguate two series
                # that share a cleaned title; read at render, never re-parsed.
                "region": channel.detected_region or "",
                "language": channel.detected_prefix or "",
                "source": (provider.name if provider else "") or "",
                # {} = no provider baseline established yet; set_baseline() below
                # fills in this (primary) provider's entry. Any OTHER provider
                # mirroring this series gets baselined silently on its first
                # check_all()/timer pass.
                "baselines": {},
                "unseen_new": 0,
                "unseen_by_mirror": {},
                "growth_providers": [],
                "last_checked": None,
            }

        self.config.add_monitored_series(entry)
        self.series_monitor.set_baseline(channel_id)
        # Composite: the Watch Queue's matched-series group reads the same
        # monitored-series list this just grew.
        self._refresh_alert_visibility()

    def _on_details_monitor_toggled(self, channel_id: str) -> None:
        """Toggle the new-episode alert from the details-pane Alert button."""
        if self.config.is_series_monitored(channel_id):
            self._unmonitor_series(channel_id)
        else:
            self._monitor_series(channel_id)

    def _on_mark_series_seen(self, channel_id: str) -> None:
        """Clear unseen count for the given series (main thread).

        Uses the composite ``_refresh_alert_visibility`` chokepoint (not the
        narrower ``_refresh_vod_alerts_section``) so the Watch Queue sidebar's
        own "Alerts Matched" matched-series rows clear their badge too — not
        just the separate Watch Alerts section's monitored-series list.
        """
        self.config.clear_unseen(channel_id)
        self._refresh_alert_visibility()
