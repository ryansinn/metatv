"""DEBT-1c — the series playback family, moved verbatim.

``_SeriesPlaybackMixin`` is mixed into :class:`~metatv.gui.main_window.MainWindow`
(main_window.py's class bases, right beside ``_SeriesMixin``), same shape as
every other ``main_window_*.py`` mixin: its methods read/write ``self.*``
attributes MainWindow's ``__init__``/``setup_ui`` already establish
(``self.db``, ``self.config``, ``self.player_manager``, ``self.executor``,
``self.status_bar``, ``self.notification_manager``, ``self._watch_tracking``,
``self._episode_ready``, ``self._episode_failed``, ``self._shutting_down``).

``main_window_series.py`` (``_SeriesMixin``) held three families — drill-down/
tree population, episode/season watch-state, and playback — pinned at exactly
its code-health ratchet ceiling. This is a pure extraction of the PLAYBACK
family: every method here is the SAME body, docstring and rationale comment
it had in ``main_window_series.py``; nothing was reworded, reordered within a
function, or changed in behaviour. ``_on_episode_stream_unavailable`` reads
like a playback method but stays on ``_SeriesMixin`` — it renders the failure
toast rather than launching anything, and its "Play Anyway" action calls back
into ``self._do_launch_episode``, which resolves through the MRO the same as
any other ``self.*`` call regardless of which mixin defines it.

``_PlayAllItem`` moved here too — every use of it inside this file was in the
two methods that moved (``_play_all_items``, ``_play_all_selected_episodes``);
``main_window_channels.py``'s own Play-All action imports it from here now
(the defining module), not from ``main_window_series``.
"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QTreeWidgetItem
from loguru import logger

from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.dtos import EpisodeDTO


@dataclass(frozen=True)
class _PlayAllItem:
    """Generic play-all queue item — carries exactly what the player needs.

    Used by :meth:`_SeriesPlaybackMixin._play_all_items` to represent a channel or
    episode in an arbitrary Play-All selection, with no live ORM state.

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


class _SeriesPlaybackMixin:
    """Mixin: channel/episode/Play-All playback methods mixed into :class:`MainWindow`."""

    def play_channel(self, item):
        """Play selected channel in external player or drill down into series"""
        logger.info("=== play_channel called ===")
        logger.info(f"Item type: {type(item)}")
        logger.info(f"Item text: {item.text() if hasattr(item, 'text') else 'N/A'}")

        try:
            channel_id = item.data(Qt.ItemDataRole.UserRole)
            logger.info(f"Channel ID from item data: {channel_id}")
        except Exception as e:
            logger.error(f"Error getting channel ID: {e}")
            self.status(f"Error: Cannot get channel ID - {e}", ms=0, level="error")
            return

        if not channel_id:
            logger.warning("No channel ID found for selected item")
            self.status("Cannot play this item - no channel ID", ms=0, level="error")
            return

        # Get channel from database to check media type
        session = self.db.get_session()
        try:
            from metatv.core.models import MediaType

            repos = RepositoryFactory(session)
            channel = repos.channels.get_by_id(channel_id)

            if not channel:
                logger.error(f"Channel not found: {channel_id}")
                self.status("Error: Channel not found", ms=0, level="error")
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
            self.status(f"Error: {e}", ms=0, level="error")
        finally:
            session.close()

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

    def play_episode_by_id(self, episode_id: str) -> None:
        """Resolve an episode_id to a PlayableEpisodeDTO and route through play_episode().

        The single chokepoint for surfaces that only know an episode's DB id — the
        Watch Queue and Favorites sidebar rows (Wave 2 Slice 2B) — so episode-grain
        playback never grows a second play path (play_episode already threads
        provider_id through to player_manager for Split-Streams keying).
        """
        episode = None
        with self.db.session_scope() as session:
            episode = RepositoryFactory(session).episodes.get_playable_dto(episode_id)
        if episode is None:
            self.status("This episode is no longer available", ms=0, level="warn")
            return
        self.play_episode(episode)

    def play_episode(self, episode, queue_season: bool | None = None, start_seconds: int = 0):
        """Play an episode and optionally queue subsequent episodes.

        Args:
            episode: The :class:`~metatv.core.repositories.dtos.EpisodeDTO` to play.
            queue_season: Per-play override for season autoplay.
                ``None`` (default) → respect ``config.autoplay_season_episodes``.
                ``False`` → play this episode only, no queue regardless of config.
                ``True`` → always queue subsequent episodes regardless of config.
            start_seconds: Position (seconds) to start playback from. ``0``
                (default) plays from the beginning — every existing call site
                keeps its current behaviour unchanged. Threaded through to
                ``launch_player_for_episode`` → ``_play_checked`` so a Resume
                click on an episode picks up where it left off.
        """
        logger.info(f"Playing episode: {episode.title}")

        if not episode.stream_url:
            self.status("Error: No stream URL for episode", ms=0, level="error")
            return

        self.status(f"Playing: {episode.title}", ms=0)

        # Resolve the effective season-queue flag:
        #   explicit True/False overrides config; None defers to config.
        if queue_season is None:
            _should_queue = self.config.autoplay_season_episodes
        else:
            _should_queue = queue_season

        # Record playback.
        #
        # Bound BEFORE the try, because line 633 reads it after the block and a
        # failure inside would otherwise leave it unbound — turning one crash
        # into a different one. (It did: the guard below was added first, and
        # the tests came back with UnboundLocalError instead of the abort.)
        episodes_to_queue: list = []

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

            episodes_to_queue = []          # reset; pre-bound above
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
        except Exception as exc:
            # Degraded, not fatal: the play proceeds; what is lost is this
            # episode's play count and the season queue.
            #
            # BOOKKEEPING MUST NOT PREVENT PLAYBACK. This block was try/finally
            # with NO except, so a write that failed took the whole app down:
            #
            #   sqlalchemy.exc.OperationalError: database is locked
            #     [SQL: UPDATE episodes SET last_played=?, play_count=? ...]
            #   fish: Job 1, './run.sh' terminated by signal SIGABRT
            #
            # PyQt aborts the process when an exception escapes a slot — no
            # traceback from Qt's side, no chance to recover. The owner hit it
            # by playing an episode while a 293,468-item source refresh held
            # the write lock past the 30 s busy_timeout.
            #
            # The channel path already behaved this way (_bg_mark_played logs
            # and moves on); the episode path never got the same treatment.
            # ERROR, not WARNING: a lock held this long is a real problem even
            # though it must not be a crash.
            logger.error("Could not record episode playback: {}", exc)
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
            provider_id=episode.provider_id, start_seconds=start_seconds,
            episode_id=episode.id,
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
            self.status("No playable URLs in selection", ms=0, level="warn")
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
            provider_id=first.provider_id, episode_id=first.content_id,
        )

    def launch_player_for_episode(
        self, stream_url, title, queue_episodes=None, provider_id: str = "",
        start_seconds: int = 0, episode_id: str = "",
    ):
        """Launch media player for an episode and queue subsequent episodes.

        Pre-flight validates the stream URL in a background thread — routed
        through the shared :meth:`validate_and_failover_stream_url` chokepoint
        (same as the channel play path) so episodes get the same alternate-host
        failover, not just a validate-or-fail check — before handing off to
        mpv, so text error responses (e.g. "not available") surface as an
        in-app notification rather than a black mpv window.

        Args:
            stream_url: The episode's playback URL.
            title: Episode title used for the mpv window title and notification.
            queue_episodes: Optional list of subsequent EpisodeDTOs to append-play.
            provider_id: The episode's source provider id — threaded to
                player_manager.play() to honour Split-Streams keying, and used
                to resolve the provider's alternate URLs for failover.
            start_seconds: Position (seconds) to start playback from. ``0``
                (default) — every existing call site keeps its current
                behaviour unchanged. Carried through the ``_episode_ready``
                signal payload to ``_do_launch_episode`` → ``_play_checked``.
            episode_id: The episode's DB id. When supplied and failover
                switches to a different host than ``stream_url``, the working
                URL is written back to this episode's row so future plays
                don't retry the dead host. Empty (default) at call sites that
                don't have an episode id — write-back is skipped there.
        """
        if not self.player_manager.is_available():
            logger.error("No media player available")
            self.status("Error: No media player found. Please install mpv.", ms=0, level="error")
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
            return self.validate_and_failover_stream_url(stream_url, provider_id)

        def _on_preflight_done(future):
            if self._shutting_down:
                logger.debug("Episode preflight completed after shutdown — discarding result")
                return
            try:
                final_url, err = future.result()
            except Exception as exc:
                logger.warning(f"Episode preflight check failed: {exc}")
                final_url, err = stream_url, None   # assume valid on unexpected errors

            ok = bool(final_url)
            if not ok:
                detail = err if err else "Stream did not respond"
                logger.warning(f"Episode stream unavailable: {title!r} — {detail}")
                self._episode_failed.emit(
                    notif_id, title, detail, stream_url,
                    queue_episodes, provider_id, start_seconds,
                )
                return

            # A failover that switched hosts must stick to this episode —
            # otherwise every future play of this same episode re-starts from
            # the dead host and re-pays the validation stall. Only this
            # episode's own row is touched. Runs here (off the UI thread) —
            # correct, this is a DB write, not a widget access.
            if final_url != stream_url and episode_id:
                try:
                    with self.db.session_scope() as session:
                        RepositoryFactory(session).episodes.update_stream_url(episode_id, final_url)
                    logger.info(f"Failover stuck for episode {episode_id}")
                except Exception as e:
                    logger.warning(f"Failed to persist failover URL for episode {episode_id}: {e}")

            # Carry provider_id (and start_seconds) in the signal payload so each
            # launch threads its own source key — a shared attr would be clobbered
            # by an overlapping launch and play/track the episode under the wrong
            # mpv key (or the wrong resume position).
            self._episode_ready.emit(
                notif_id, final_url, title, queue_episodes, provider_id, start_seconds
            )

        future = self.executor.submit(_preflight)
        future.add_done_callback(_on_preflight_done)

    def _do_launch_episode(
        self, notif_id, stream_url, title, queue_episodes, provider_id="",
        start_seconds: int = 0,
    ) -> None:
        """Actually launch mpv after a successful preflight check (called on main thread).

        Threads the provider_id carried in the _episode_ready signal payload to
        player_manager.play() so Split-Streams keying works correctly — each
        launch carries its own value, so an overlapping launch can't clobber it.
        Also passes per-item titles to the queue so the mpv window title updates
        as each episode starts — not just for the first one. start_seconds (also
        carried in the signal payload, default 0) threads through to
        _play_checked so a Resume click starts from the saved position.
        """
        self.notification_manager.dismiss(notif_id)
        logger.info(f"Playing first episode: {title}")
        if self._play_checked(stream_url, title, provider_id=provider_id, start_seconds=start_seconds):
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

            QTimer.singleShot(2000, lambda: self.status(status_msg, ms=0))
        else:
            logger.error(f"Failed to play episode: {title}")
            self.status(f"Error playing: {title}", ms=0, level="error")

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
