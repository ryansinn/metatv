"""Downloads: the MainWindow half of saving a VOD for offline watching.

Its own module rather than a few more methods on ``_FavoritesMixin`` because
downloads are not a favourites concern — they share only the fact that both
are reached from the channel menu. Sibling of ``main_window_updates.py`` and
``main_window_history.py``: one mixin per concern, folded into ``MainWindow``.

The transfer itself lives in :mod:`metatv.core.download_manager`, which holds
no Qt at all — this module is the wiring and the two sentences the user reads.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMenu, QMessageBox

from metatv.core.download_manager import DownloadManager, library_dir
from metatv.core.epg_utils import now_utc, to_local
from metatv.core.models import MediaType
from metatv.core.recording_manager import RecordingManager, recordings_dir
from metatv.core.repositories.channel_downloads import _file_exists
from metatv.core.signal_check_manager import SignalCheckManager
from metatv.gui import icon_utils as _icon_utils
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.core.repositories import RepositoryFactory
from metatv.gui.file_reveal import open_folder, reveal_file
from metatv.gui.sidebar.transfer_rows import ROLE_ITEM_ID

if TYPE_CHECKING:                                    # pragma: no cover
    from metatv.core.recording_manager import RecordingProgress, ScheduleOutcome
    from metatv.core.repositories.dtos import PlayableChannelDTO

#: How often the two transfer sections re-read their manager. Two seconds
#: matches the download scheduler's own POLL_SECONDS, so a row never lags the
#: thing it describes by more than one of its ticks.
_TRANSFER_TICK_MS = 2000
from metatv.core.epg_utils import to_local, to_utc_naive
from metatv.core.history_buckets import BUCKETS_BY_KEY, bucket_range
from metatv.core.models import MediaType
from metatv.core.repositories import RepositoryFactory


def _hms(total_seconds: float) -> str:
    """Elapsed as ``H:MM:SS`` — always shows the hour, even ``0``, unlike the
    playback-position formatters elsewhere that hide it under an hour: a
    recording's persistent notice (Catch, Keep, Record Q1) reads that as
    "still going", not "barely started"."""
    total = max(0, int(total_seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def _hm(total_seconds: float) -> str:
    """Remaining as ``H:MM`` — the caller's leading "~" says it is approximate."""
    total = max(0, int(total_seconds))
    h, rem = divmod(total, 3600)
    m = rem // 60
    return f"{h}:{m:02d}"


class _DownloadsMixin:
    """Construct the download manager and start a download from the menu."""

    def _setup_downloads(self) -> None:
        """Build the manager and give it the accountant the player already uses.

        One accountant, so a download and a play on the same source can never
        both believe they hold that provider's single connection. The preempt
        callback is what makes a click on Play win: the manager parks its
        transfer at the byte it reached and resumes when the slot comes back.

        Registered through ``add_preempt_listener``, never by assigning
        ``accountant._on_preempt``. That assignment gave THIS manager the hook
        outright, and the accountant had only the one — so the enrichment
        backfill and the series-monitor poll, which are evicted by the very
        same rule, were never told and kept their HTTP calls running on the
        provider's one connection. mpv was refused and quit seconds after
        opening. ``tests/test_preempt_listener_fanout.py`` fails the suite on
        any re-assignment.
        """
        accountant = self.player_manager.connection_accountant

        # The fan-out lives in the ACCOUNTANT, not here. This branch grew its
        # own `_preempt_listeners` list plus a `_dispatch_preempt` closure
        # assigned onto `accountant._on_preempt`, because at the time the
        # accountant had a single callback slot and a second assignment silently
        # replaced the first. Main has since put `add_preempt_listener` on the
        # accountant, which solves the same hazard one layer down and for every
        # caller — so keeping both would be two mechanisms doing one job, with
        # the local one re-introducing the very single-slot assignment the
        # docstring above forbids.
        self.download_manager = DownloadManager(self.db, self.config, accountant)
        accountant.add_preempt_listener(self.download_manager.on_preempted)
        self.download_manager.start()
        self._register_cleanable("downloads", self.download_manager.shutdown)

        # Recordings share the accountant but not the priority rule: they evict
        # downloads and are evicted by nothing. See core/recording_manager.py.
        self.recording_manager = RecordingManager(
            self.db, self.config, accountant,
            on_conflict=self._on_recording_blocked,
            on_countdown=self._on_recording_countdown)
        self.recording_manager.start()
        self._register_cleanable("recordings", self.recording_manager.shutdown)
        #: recording_id -> the persistent "recording in progress" notification
        #: id showing it, so each tick UPDATES the same card (Q1) instead of
        #: stacking a fresh one — see _refresh_recording_notifications.
        self._recording_notif_ids: dict[str, str] = {}

        # Both sections are PUSHED their rows on a tick — the managers are
        # plain classes with no Qt signals, and giving a widget a manager
        # reference would make the widget's lifetime the manager's problem.
        # Same shape as refresh_retry: the host owns the manager, the section
        # renders what it is handed.
        #
        # The tick is cheap by construction: progress() is an in-memory read,
        # and ProgressBar.set_pct repaints only past a 0.5% move — so an idle
        # app with nothing transferring does no work beyond two empty lists.
        self._transfer_tick = QTimer(self)
        self._transfer_tick.setInterval(_TRANSFER_TICK_MS)
        self._transfer_tick.timeout.connect(self._refresh_transfer_sections)
        self._transfer_tick.start()
        self._register_cleanable("transfer_tick", self._transfer_tick.stop)

        # Signal checks: the lowest-priority holder in the app. It evicts
        # nobody and everybody evicts it, and being evicted KILLS the probe
        # rather than letting it finish — a Play press waits milliseconds
        # instead of the ~18 s a full sample plus timeout would cost.
        #
        # Registered through accountant.add_preempt_listener, not the
        # _preempt_listeners list this branch was written against: main
        # replaced that list with a method on the accountant while this sat
        # open, and the list no longer exists.
        self.signal_check_manager = SignalCheckManager(
            self.db, self.config, accountant)
        accountant.add_preempt_listener(self.signal_check_manager.on_preempted)
        self.signal_check_manager.start()
        self._register_cleanable(
            "signal_check", self.signal_check_manager.shutdown)
        logger.debug("Download, recording and signal-check managers ready")

    # ── the transfer sections ──────────────────────────────────────────────

    def _refresh_transfer_sections(self) -> None:
        """Push each manager's progress into its sidebar section, if shown.

        Guarded on the section being present rather than on hasattr: a section
        the user hid is simply not built, and this runs on a timer that starts
        before the sidebar finishes assembling.
        """
        sections = self.__dict__.get("sidebar_sections") or {}
        downloads = sections.get("downloads")
        if downloads is not None:
            try:
                downloads.refresh_progress(
                    self.download_manager.progress(),
                    gate_lines=self.download_manager.connection_gate_lines(),
                )
            except Exception:
                logger.exception("could not refresh the Downloads section")

        # One read for every recording-derived consumer this tick (REC-2):
        # the Recordings sidebar section, the Watch Alerts row indicators, the
        # On Now/Browse Rec columns, and the persistent recording notice.
        recording_rows = self.recording_manager.progress()
        recordings = sections.get("recordings")
        if recordings is not None:
            try:
                recordings.refresh_progress(recording_rows)
            except Exception:
                logger.exception("could not refresh the Recordings section")
        alerts = sections.get("alerts")
        if alerts is not None:
            try:
                alerts.refresh_recording_indicators(recording_rows)
            except Exception:
                logger.exception("could not refresh Watch Alerts recording indicators")
        epg_view = self.__dict__.get("epg_view")
        if epg_view is not None:
            try:
                epg_view.refresh_recording_indicators(recording_rows)
            except Exception:
                logger.exception("could not refresh EPG recording indicators")
        try:
            self._refresh_recording_notifications(recording_rows)
        except Exception:
            logger.exception("could not refresh the persistent recording notice")

    def _refresh_recording_notifications(
            self, rows: "list[RecordingProgress]",
            *, now: "datetime | None" = None) -> None:
        """One persistent notice per ACTIVELY recording row (Q1, settled 2026-08-30).

        "One persistent notification carries elapsed, remaining, disk used
        and free, the programme, and a Watch button" — updated in PLACE each
        tick via ``notification_manager.update`` (never re-``show``n), so the
        same card survives from the first tick it starts recording to the one
        where it stops. Dismissed the moment its row leaves the recording
        state (finishes, is cancelled, or fails).

        Args:
            rows: A ``RecordingManager.progress()`` snapshot.
            now: The instant to measure elapsed/remaining against; defaults to
                ``now_utc()``. Takes it rather than reaching for the real
                clock underneath, so a test can pin one.
        """
        now = now or now_utc()
        active_ids = set()
        for r in rows:
            if r.state != "recording":
                continue
            active_ids.add(r.recording_id)
            elapsed = _hms((now - r.starts_at).total_seconds())
            remaining = _hm(max(0.0, (r.ends_at - now).total_seconds()))
            used_gb = r.recorded_bytes / (1024 ** 3)
            try:
                free_gb = shutil.disk_usage(
                    recordings_dir(self.config)).free / (1024 ** 3)
            except OSError:
                free_gb = 0.0
            post_roll = 0
            if r.programme_end is not None:
                post_roll = max(0, round(
                    (r.ends_at - r.programme_end).total_seconds() / 60))
            name = r.programme_title or r.channel_name
            source = self._recording_source_name(r.provider_id)
            title = f"{_icons.recording_active_icon} RECORDING {name}"
            message = (
                f"{elapsed} / ~{remaining} · {used_gb:.1f} GB used, "
                f"{free_gb:.1f} GB free · ends {to_local(r.ends_at):%H:%M} "
                f"(+{post_roll} min post-roll) · playback on {source} is "
                f"unavailable until it finishes"
            )
            notif_id = self._recording_notif_ids.get(r.recording_id)
            if notif_id is None:
                notif_id = self.notification_manager.show(
                    title=title, message=message, type="warning",
                    dismissible=False,
                    actions=[
                        # Watch does NOT close the card — the recording keeps
                        # running — so it carries the keep_open flag the
                        # generic action-button chokepoint reads
                        # (notification_widget.NotificationCard).
                        ("Watch", lambda rid=r.recording_id:
                            self._watch_recording(rid), True),
                        ("Stop", lambda rid=r.recording_id:
                            self._cancel_recording(rid)),
                    ],
                )
                self._recording_notif_ids[r.recording_id] = notif_id
            else:
                self.notification_manager.update(
                    notif_id, title=title, message=message)

        for rid in list(self._recording_notif_ids):
            if rid not in active_ids:
                self.notification_manager.dismiss(
                    self._recording_notif_ids.pop(rid))

    def _recording_source_name(self, provider_id: str) -> str:
        """The provider's display name, for "playback on <source> is unavailable"."""
        with self.db.session_scope(commit=False) as session:
            provider = RepositoryFactory(session).providers.get_by_id(provider_id)
            return provider.name if provider is not None else "this source"

    # ── folder actions ─────────────────────────────────────────────────────

    def _open_downloads_folder(self) -> None:
        if not open_folder(library_dir(self.config)):
            self.status_bar.showMessage("No downloads folder yet.", 4000)

    def _open_recordings_folder(self) -> None:
        if not open_folder(recordings_dir(self.config)):
            self.status_bar.showMessage("No recordings folder yet.", 4000)

    def _reveal_in_file_manager(self, dest_path: str) -> None:
        """Reveal one transfer's file. Says so when the file is gone.

        Files are deleted outside the app, so "it is downloaded" is only ever
        true of the filesystem — silently opening an empty folder would make a
        claim this cannot check any other way.
        """
        if not reveal_file(dest_path):
            self.status_bar.showMessage(
                "That file is no longer on disk.", 4000)

    # ── row actions ────────────────────────────────────────────────────────

    def _pause_download(self, download_id: str) -> None:
        self.download_manager.pause(download_id)
        self._refresh_transfer_sections()

    def _resume_download(self, download_id: str) -> None:
        self.download_manager.resume(download_id)
        self._refresh_transfer_sections()

    def _cancel_download(self, download_id: str) -> None:
        self.download_manager.cancel(download_id)
        self._refresh_transfer_sections()

    # ── playback of a finished download (DL-4) ─────────────────────────────

    def play_downloaded(self, download_id: str) -> None:
        """Play a finished download's file.

        Claims no accountant slot and runs no URL probe:
        ``PlayerManager.play_local_file`` is the local-file counterpart to
        ``play()`` and neither concern applies to a file already on disk. Own
        window vs. shared follows Split Streams, so a live stream elsewhere
        keeps playing when it is on. Records the play into History through the
        same seam ``_bg_mark_played`` gives every other play path, with
        ``key=None`` — deliberately skipping watch-progress-capture
        registration, which is out of scope for local playback this slice.
        """
        rows = [r for r in self.download_manager.progress() if r.id == download_id]
        if not rows or rows[0].state != "completed":
            return
        row = rows[0]
        if not _file_exists(row.dest_path):
            self.status_bar.showMessage("That file is no longer on disk.", 4000)
            return

        own_window = bool(getattr(self.config, "split_streams_by_source", False))
        if not self.player_manager.play_local_file(
                row.dest_path, row.channel_name, own_window=own_window):
            self.status_bar.showMessage(f"Could not play {row.channel_name}.", 4000)
            return

        self.executor.submit(self._bg_mark_played, row.channel_id, None)

    def _delete_download_file(self, download_id: str) -> None:
        """Delete a finished download's FILE only — the ledger row stays.

        Confirmed and named, per the deletion grammar (destructive + confirm,
        never the ghost-row Undo a history CLEAR gets): this cannot be undone
        the way a history-group clear can, because the bytes are gone, not
        just the row. The row's meta flips to "file removed" on the next
        render — ``channel_downloads._file_exists`` is read fresh every time,
        never cached.
        """
        rows = [r for r in self.download_manager.progress() if r.id == download_id]
        if not rows:
            return
        path = Path(rows[0].dest_path)
        reply = QMessageBox.question(
            self, "Delete File",
            f'Delete "{path.name}" from disk?\n\n'
            "This only removes the file — it stays in your download history.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning(f"Could not delete download file {path}: {exc}")
            self.status_bar.showMessage(f"Could not delete {path.name}: {exc}", 5000)
            return
        self.status_bar.showMessage(f"Deleted {path.name}", 4000)
        self._refresh_transfer_sections()

    # ── download history (terminal rows) ───────────────────────────────────

    def _clear_download_history_group(self, bucket_key: str) -> None:
        """Forget one Downloads time group at once, offering Undo instead of
        asking first — mirrors ``_HistoryMixin.clear_history_group`` in shape,
        except a cleared download's row is only HIDDEN (``history_cleared``),
        never deleted: the Downloaded scope reads the same rows' ``state``, so
        deleting would drop a still-present file out of that scope. Undo
        clears the flag rather than re-inserting a row. Files are never
        touched either way.
        """
        bucket = BUCKETS_BY_KEY.get(bucket_key)
        if bucket is None:
            logger.warning(f"Unknown history bucket: {bucket_key!r}")
            return
        # bucket_range works in LOCAL time (it shares History's boundaries);
        # DownloadDB.updated_at is stored UTC-naive, so the window is
        # converted before it is used to filter that column.
        not_before_local, not_after_local = bucket_range(bucket_key)
        not_before = to_utc_naive(not_before_local) if not_before_local else None
        not_after = to_utc_naive(not_after_local) if not_after_local else None

        try:
            count, snapshot = self.download_manager.clear_history_group(
                not_before, not_after)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to clear download history group {bucket.label!r}: {e}")
            self.status_bar.showMessage(f"Error clearing download history: {e}")
            return

        self._refresh_transfer_sections()
        if not count:
            self.status_bar.showMessage(f"Nothing to forget under {bucket.label}")
            return

        self.status_bar.showMessage(f"Cleared {count} download(s) from {bucket.label}")
        self.notification_manager.show(
            title="Download history cleared",
            message=(f"Forgot {count} download(s) under {bucket.label}. "
                     "Files were not deleted."),
            type="info",
            auto_dismiss_ms=8000,
            actions=[("Undo", lambda: self._undo_download_history_group_clear(snapshot))],
        )

    def _undo_download_history_group_clear(self, snapshot) -> None:
        """Restore a per-group clear's snapshot — the Undo toast's callback."""
        try:
            restored = self.download_manager.restore_history_snapshot(snapshot)
            self._refresh_transfer_sections()
            self.status_bar.showMessage(f"Restored {restored} download(s)")
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to undo download history clear: {e}")
            self.status_bar.showMessage(f"Error restoring download history: {e}")

    def _clear_download_history(self) -> None:
        """The ⋯ menu's "Clear download history" — every group at once.

        Broad enough to confirm rather than offer Undo for, the same way
        History's own "Clear all history" does; the per-GROUP clear above is
        cheap enough to skip the dialog and offer Undo instead. Files are
        never touched — only the ``DownloadDB`` ledger.
        """
        reply = QMessageBox.question(
            self, "Clear Download History",
            "Forget every finished or failed download?\n\n"
            "This only clears your history list — files already saved to "
            "disk are never deleted, and anything still queued, "
            "downloading or paused is untouched.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        count, _snapshot = self.download_manager.clear_history_group(None, None)
        self._refresh_transfer_sections()
        self.status_bar.showMessage(
            f"Cleared {count} item(s) from your download history" if count
            else "Nothing to clear", 4000)

    # ── row context menu ────────────────────────────────────────────────────

    def show_downloads_context_menu(self, position) -> None:
        """The Downloads row menu — Play / Pause / Resume / Cancel / Reveal /
        Delete file.

        Built here rather than through ``channel_menu.py``'s registry: these
        are TRANSFER verbs (pause/resume/cancel/delete-file) keyed on
        ``download_id`` and file-on-disk state, not the ``ChannelDB``-keyed
        actions that registry composes.
        """
        sections = self.__dict__.get("sidebar_sections") or {}
        section = sections.get("downloads")
        if section is None:
            return
        lst = section.downloads_list
        item = lst.itemAt(position)
        if item is None or not item.data(ROLE_ITEM_ID):
            return
        lst.setCurrentItem(item)
        selected = section.selected_download()
        if selected is None:
            return
        download_id, state, dest_path = selected
        file_exists = _file_exists(dest_path)

        menu = QMenu(self)

        if state == "completed" and file_exists:
            act = menu.addAction(_icons.glyph_icon(_icons.play_icon), "Play")
            act.triggered.connect(lambda: self.play_downloaded(download_id))

        if state in ("queued", "running"):
            act = menu.addAction(_icons.glyph_icon(_icons.enrich_pause_icon), "Pause")
            act.triggered.connect(lambda: self._pause_download(download_id))
        elif state == "paused":
            act = menu.addAction(_icons.glyph_icon(_icons.play_icon), "Resume")
            act.triggered.connect(lambda: self._resume_download(download_id))

        if state in ("queued", "running", "paused"):
            act = menu.addAction(
                _icons.glyph_icon(_icons.enrich_cancel_icon), "Cancel download")
            act.triggered.connect(lambda: self._cancel_download(download_id))

        if dest_path:
            if menu.actions():
                menu.addSeparator()
            act = menu.addAction(
                _icon_utils.resolve_icon(
                    _icons.vector_key("folder_open"), _theme.COLOR_MUTED),
                "Reveal in file manager")
            act.triggered.connect(lambda: self._reveal_in_file_manager(dest_path))

        if state == "completed" and file_exists:
            act = menu.addAction(_icons.glyph_icon(_icons.delete_icon), "Delete file…")
            act.triggered.connect(lambda: self._delete_download_file(download_id))

        if not menu.actions():
            return
        menu.exec(lst.mapToGlobal(position))

    def _cancel_recording(self, recording_id: str) -> None:
        self.recording_manager.cancel(recording_id)
        self._refresh_transfer_sections()

    def _extend_recording(self, recording_id: str) -> None:
        """Push a running recording's stop time out by the configured step.

        The stop time is read at each tick rather than computed once at the
        start, which is what makes extending a RUNNING recording possible —
        the spec's reason for that shape: "the live extend is the one that
        saves an event".
        """
        minutes = int(getattr(self.config, "recording_extend_minutes", 15) or 15)
        new_end = self.recording_manager.extend(recording_id, minutes * 60)
        if new_end is not None:
            self.status_bar.showMessage(
                f"Recording extended to {to_local(new_end):%H:%M}.", 4000)
        self._refresh_transfer_sections()

    def _watch_recording(self, recording_id: str) -> None:
        """Play the file a recording is still writing.

        Costs no second connection, which is the whole point on a
        one-connection account: the recorder already has the stream open and
        is appending to disk, so the player opens THAT file. A few seconds
        behind live is the correct trade.
        """
        rows = [r for r in self.recording_manager.progress()
                if r.recording_id == recording_id]
        if not rows or not rows[0].dest_path:
            self.status_bar.showMessage("That recording has no file yet.", 4000)
            return
        path = Path(rows[0].dest_path)
        if not path.exists():
            self.status_bar.showMessage("That recording has no file yet.", 4000)
            return
        self.player_manager.play(str(path), rows[0].programme_title
                                 or rows[0].channel_name)

    def _resolve_playable_channel(
            self, channel_id: str) -> "PlayableChannelDTO | None":
        """Open a session, resolve the playable DTO, close it. Nothing else.

        The one-session-one-query body ``download_channel_by_id`` and
        ``schedule_recording_from_programme`` both opened verbatim before this
        was pulled out — same two lines, two copies. A caller that needs more
        than the DTO in the SAME session (``record_channel_by_id``'s EPG
        peek, ``record_channel_window``'s provider-name lookup) opens its own
        block instead, since there is nothing generic to share there.

        Args:
            channel_id: The channel's unique ID string.

        Returns:
            The DTO, or ``None`` if the channel no longer exists.
        """
        with self.db.session_scope() as session:
            return RepositoryFactory(session).channels.get_playable_dto(channel_id)

    def download_channel_by_id(self, channel_id: str) -> None:
        """Queue a VOD for download to the local library.

        Sibling of ``play_channel_deep_cache_by_id`` and gated the same way —
        VOD only. The difference is persistence: the deep cache is a scratch
        file purged when playback stops, this one stays. For a SERIES the
        normal drill-in is used, because a series has no single stream to save.

        The transfer itself is the ``DownloadManager``'s problem, including
        waiting for a free connection slot on this source — the click only
        enqueues, so it never blocks the UI thread on the network.

        Args:
            channel_id: The channel's unique ID string.
        """
        channel = self._resolve_playable_channel(channel_id)
        if not channel:
            return
        if channel.media_type == MediaType.SERIES:
            self.drill_into_series(channel)
            return

        queued = self.download_manager.enqueue(
            channel_id=channel.id,
            provider_id=channel.provider_id,
            channel_name=channel.name,
            source_url=channel.stream_url,
        )
        if queued:
            self.notification_manager.show(
                title=f"Downloading {channel.name}",
                message="It pauses by itself while you watch anything on this source.",
                type="info",
                dismissible=True,
            )
        else:
            # Already queued or already saved. Silence would read as a click
            # that did nothing, which is the same complaint as a dead button.
            self.notification_manager.show(
                title=f"{channel.name} is already in your downloads",
                message="",
                type="info",
                dismissible=True,
            )

    def record_channel_by_id(self, channel_id: str) -> None:
        """Record what is on this live channel now.

        Window comes from the EPG programme currently airing when there is one —
        that is the whole reason to prefer it over a fixed duration: "record
        what's on" should end when the programme ends, not after an arbitrary
        hour. With no EPG (and a third of this catalogue has none) it falls back
        to ``config.recording_default_minutes``, which is a guess the user can
        see and cancel rather than a silent failure.

        Args:
            channel_id: The channel's unique ID string.
        """
        from metatv.core.epg_utils import now_utc
        from metatv.core.models import MediaType

        with self.db.session_scope() as session:
            repos = RepositoryFactory(session)
            channel = repos.channels.get_playable_dto(channel_id)
            # Read the programme's fields INSIDE the session. get_now_for_channel
            # hands back an ORM row, and session_scope expires on commit, so the
            # first attribute touched outside this block would raise
            # DetachedInstanceError (CLAUDE.md: cross the boundary with plain data).
            airing = None
            if channel and channel.media_type == MediaType.LIVE:
                row = repos.epg.get_now_for_channel(channel_id)
                if row is not None:
                    airing = (row.start_time, row.stop_time, row.title or "")
        if not channel:
            return

        now = now_utc()
        if airing is not None:
            starts_at, ends_at, title = airing
            pad = True
        else:
            minutes = int(self.config.recording_default_minutes)
            starts_at, ends_at, title, pad = (
                now, now + timedelta(minutes=minutes), "", False)

        self._schedule_and_announce(channel, starts_at, ends_at, title, pad=pad)

    def record_channel_window(self, channel_id: str) -> None:
        """Record a live channel for a user-picked start/end window.

        *Catch, Keep, Record* Feature 3 Option B: needs no guide data at
        all, unlike ``record_channel_by_id`` (falls back to a guessed
        duration when there is no EPG entry) — this is what makes recording
        work at all on a source with no EPG, the owner's own live source
        among them. ``RecordWindowDialog`` owns the default window, the
        validity rule, and its own explicit padding; this method only
        resolves the channel + provider name it needs and hands the
        dialog's answer to the shared ``_schedule_and_announce`` chokepoint.

        Args:
            channel_id: The channel's unique ID string.
        """
        from PyQt6.QtWidgets import QDialog

        from metatv.gui.record_window_dialog import RecordWindowDialog

        with self.db.session_scope() as session:
            repos = RepositoryFactory(session)
            channel = repos.channels.get_playable_dto(channel_id)
            provider_db = (repos.providers.get_by_id(channel.provider_id)
                          if channel else None)
            provider_name = provider_db.name if provider_db else "This source"
        if not channel or channel.media_type != MediaType.LIVE:
            return

        dlg = RecordWindowDialog(channel.name, provider_name, self.config, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        starts_at, ends_at, pad_start_seconds, pad_end_seconds = dlg.result_window()
        self._schedule_and_announce(
            channel, starts_at, ends_at, title=channel.name, pad=True,
            pad_start_seconds=pad_start_seconds, pad_end_seconds=pad_end_seconds)

    def schedule_recording_from_programme(
            self, channel_id: str, starts_at: datetime, ends_at: datetime,
            title: str) -> None:
        """Record a SPECIFIC guide programme (REC-3), not "what's on now".

        Reached from the "record_programme" channel-menu action, which carries
        the row's own window on three surfaces — Watch Alerts, On Now, and
        Browse (future programmes) — so unlike ``record_channel_by_id`` this
        is correct on a row that has not started yet.

        Args:
            channel_id: The channel's unique ID string.
            starts_at: The programme's start, UTC-naive, unpadded.
            ends_at: The programme's end, UTC-naive, unpadded.
            title: The programme title.
        """
        channel = self._resolve_playable_channel(channel_id)
        if not channel:
            return
        self._schedule_and_announce(channel, starts_at, ends_at, title, pad=True)

    def _on_alert_programme_context_menu(
            self, channel_db_id: str, starts_at: datetime, ends_at: datetime,
            title: str, gx: int, gy: int) -> None:
        """Thin wrapper → unified channel menu (alerts surface, programme row).

        ``WatchAlertsSection.programmeContextMenuRequested`` fires this INSTEAD
        of ``channelContextMenuRequested`` when the row under the cursor
        carries a programme identity, so the menu offers "Record this
        programme" against the row's own window (REC-3) rather than "now".
        """
        self._show_channel_menu(
            [channel_db_id], "alerts", gx, gy,
            programme=(starts_at, ends_at, title))

    def _schedule_and_announce(
            self, channel: "PlayableChannelDTO", starts_at: datetime,
            ends_at: datetime, title: str, *, pad: bool,
            pad_start_seconds: "int | None" = None,
            pad_end_seconds: "int | None" = None) -> None:
        """Schedule a recording and tell the user what happened.

        The one chokepoint ``record_channel_by_id`` (a live channel's "now"),
        ``schedule_recording_from_programme`` (REC-3, a specific guide row)
        and ``record_channel_window`` (Option B, a picked window) all end in,
        so the notification copy — and the conflict handling — exists once
        rather than three times.

        Args:
            channel: The playable DTO already resolved by the caller.
            starts_at: Programme start, UTC-naive, unpadded.
            ends_at: Programme end, UTC-naive, unpadded.
            title: Programme title, or "" for the no-EPG "record now for N
                minutes" fallback (every message below falls back to the
                channel name).
            pad: Whether the configured default padding applies — False only
                for the no-EPG fallback, which has no real guide window to pad.
                Ignored when either padding override below is given.
            pad_start_seconds: Explicit start padding, overriding both `pad`
                and the config default — ``RecordWindowDialog``'s own spin
                value. ``None`` (the default) falls back to `pad`'s behaviour.
            pad_end_seconds: Same, for the end offset.
        """
        if pad_start_seconds is None and pad_end_seconds is None:
            pad_kwargs = {} if pad else {"pad_start_seconds": 0, "pad_end_seconds": 0}
        else:
            pad_kwargs = {}
            if pad_start_seconds is not None:
                pad_kwargs["pad_start_seconds"] = pad_start_seconds
            if pad_end_seconds is not None:
                pad_kwargs["pad_end_seconds"] = pad_end_seconds

        outcome = self.recording_manager.schedule(
            channel_id=channel.id, provider_id=channel.provider_id,
            channel_name=channel.name, source_url=channel.stream_url,
            starts_at=starts_at, ends_at=ends_at, programme_title=title,
            **pad_kwargs)

        if not outcome.scheduled:
            self.notification_manager.show(
                title=f"{title or channel.name} is already being recorded",
                message="", type="info", dismissible=True)
            return

        if outcome.conflicts:
            # Surfaced now rather than at start time, which is the whole point
            # of detecting it here: the user can still drop one (settled).
            others = ", ".join(name for _rid, name in outcome.conflicts)
            choice = self._resolve_recording_conflict(
                outcome, title or channel.name, others)
            if choice == "drop_this":
                self.recording_manager.cancel(outcome.recording_id)
                return
            if choice == "drop_other":
                for rid, _name in outcome.conflicts:
                    self.recording_manager.cancel(rid)
                # Falls through — this recording now stands alone, so it gets
                # the normal success notification below.
            else:
                self.notification_manager.show(
                    title=f"Recording {title or channel.name} — but it clashes",
                    message=(f"This source allows one connection and {others} "
                             f"already wants it at the same time. One of them "
                             f"will not record."),
                    type="warning", dismissible=True)
                return

        # The EFFECTIVE window, not the guide's — the offsets move it, and a
        # message promising a stop fifteen minutes before the recorder actually
        # stops is the kind of small lie that teaches people to distrust the app.
        window = self.recording_manager.window_of(outcome.recording_id)
        ends_local = to_local(window[1] if window else ends_at)

        self.notification_manager.show(
            title=f"Recording {title or channel.name}",
            message=(f"Until {ends_local:%H:%M}. MetaTV has to be running, and "
                     f"it will take this source's connection off whatever you "
                     f"are watching — with a countdown you can cancel."),
            type="info", dismissible=True)

    def _resolve_recording_conflict(
            self, outcome: "ScheduleOutcome", title: str,
            others_label: str) -> str:
        """Ask what to do about a same-source recording clash (settled).

        Its own seam, separate from ``_schedule_and_announce``, so a test can
        monkeypatch the decision without driving a live ``QMessageBox``. The
        caller applies whatever cancel(s) the answer implies and decides what
        to notify — this method only asks and reports back.

        Returns:
            ``"keep_both"``, ``"drop_other"`` (cancel every id in
            ``outcome.conflicts``), or ``"drop_this"`` (cancel
            ``outcome.recording_id``).
        """
        from PyQt6.QtWidgets import QMessageBox

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Recording clash")
        box.setText(
            f"Recording {title} clashes with {others_label} — this source "
            f"allows only one connection at a time.")
        keep_btn = box.addButton("Keep both", QMessageBox.ButtonRole.RejectRole)
        drop_other_btn = box.addButton(
            "Drop the other", QMessageBox.ButtonRole.DestructiveRole)
        drop_this_btn = box.addButton(
            "Drop this one", QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(keep_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is drop_other_btn:
            return "drop_other"
        if clicked is drop_this_btn:
            return "drop_this"
        return "keep_both"

    def _confirm_quit_with_due_recordings(self) -> bool:
        """Whether it is safe to quit right now (settled Q4).

        ``recording_manager.progress()`` already omits terminal rows, so its
        length IS "recordings that still need the app running" — nothing else
        to count.
        """
        count = len(self.recording_manager.progress())
        if count == 0:
            return True
        return self._ask_quit_with_recordings(count)

    def _ask_quit_with_recordings(self, count: int) -> bool:
        """Seam wrapping the actual confirmation dialog, so a test can
        monkeypatch the answer without driving a live ``QMessageBox``."""
        from PyQt6.QtWidgets import QMessageBox

        noun = "recording" if count == 1 else "recordings"
        reply = QMessageBox.question(
            self, "Quit MetaTV?",
            f"{count} {noun} scheduled or running — MetaTV must stay open to "
            f"record. Quit anyway?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        return reply == QMessageBox.StandardButton.Yes

    def _on_epg_refreshed_resync_recordings(
            self, provider_id: str, count: int) -> None:
        """REC-5: after every completed EPG refresh, re-check the guide.

        ``resync_from_guide`` opens its own DB session, so it must not run on
        the UI thread — routed through the ``_run_query`` async seam like any
        other background DB work, even though this one writes rather than
        reads (``RecordingManager`` manages its own session and commit; the
        outer read-only session ``_run_query`` opens is simply unused).

        Args:
            provider_id: Unused — every scheduled recording is re-checked
                regardless of which provider's guide just refreshed, since a
                recording's own channel may belong to a different provider
                than the one that triggered this refresh.
            count: Unused — signature matched to
                ``EpgManager.refresh_finished``.
        """
        def _query(_repos):
            return self.recording_manager.resync_from_guide()

        self._run_query(_query, self._on_recordings_resynced)

    def _on_recordings_resynced(self, moved: list) -> None:
        """Main-thread slot for :meth:`_on_epg_refreshed_resync_recordings`.

        One notification per moved row — a recording is a promise ("this will
        be there when you look for it"), and a silently-moved window breaks
        that promise if nothing says so.
        """
        if not moved:
            return
        for _recording_id, title, new_start in moved:
            self.notification_manager.show(
                title=f"{title} moved to {to_local(new_start):%H:%M}",
                message="", type="info", dismissible=True)
        self._refresh_transfer_sections()

    def _on_recording_countdown(self, recording_id: str, title: str,
                                seconds: int) -> None:
        """Warn that a recording is about to take the stream you are watching.

        Fires at 10 min / 5 / 1 / 30 s, once each, and only while something is
        actually playing on that source — an idle app is never interrupted.
        Every one of these is a chance to cancel, which is what makes taking
        the connection acceptable rather than hostile.

        Called from the worker thread, so it hops to the main thread before
        touching the notification manager.
        """
        when = (f"{seconds // 60} minutes" if seconds >= 60
                else f"{seconds} seconds")
        QTimer.singleShot(0, lambda: self.notification_manager.show(
            title=f"Recording {title} in {when}",
            message=("It needs this source's only connection, so your stream "
                     "will stop. Cancel the recording if you would rather keep "
                     "watching."),
            type="warning", dismissible=True))

    def _on_recording_blocked(self, recording_id: str, channel_name: str) -> None:
        """Say once that a recording is waiting on the source's only connection.

        Called from the recording worker thread, so it hops to the main thread
        before touching the notification manager — Qt widgets are main-thread
        only (CLAUDE.md: workers emit, only the main thread touches widgets).

        A warning rather than an error: the recording has not failed, it is
        retrying for its whole window, and stopping playback rescues it.
        """
        QTimer.singleShot(0, lambda: self.notification_manager.show(
            title=f"Waiting to record {channel_name}",
            message=("This source allows one connection and it is in use. The "
                     "recording starts by itself as soon as you stop watching "
                     "this source — whatever is left of the programme."),
            type="warning", dismissible=True))
