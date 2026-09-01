"""Downloads: the MainWindow half of saving a VOD for offline watching.

Its own module rather than a few more methods on ``_FavoritesMixin`` because
downloads are not a favourites concern — they share only the fact that both
are reached from the channel menu. Sibling of ``main_window_updates.py`` and
``main_window_history.py``: one mixin per concern, folded into ``MainWindow``.

The transfer itself lives in :mod:`metatv.core.download_manager`, which holds
no Qt at all — this module is the wiring and the two sentences the user reads.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from loguru import logger
from PyQt6.QtCore import QTimer

from metatv.core.download_manager import DownloadManager, library_dir
from metatv.core.recording_manager import RecordingManager, recordings_dir
from metatv.gui.file_reveal import open_folder, reveal_file

#: How often the two transfer sections re-read their manager. Two seconds
#: matches the download scheduler's own POLL_SECONDS, so a row never lags the
#: thing it describes by more than one of its ticks.
_TRANSFER_TICK_MS = 2000
from metatv.core.epg_utils import to_local
from metatv.core.models import MediaType
from metatv.core.repositories import RepositoryFactory


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
        logger.debug("Download and recording managers ready")

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
                downloads.refresh_progress(self.download_manager.progress())
            except Exception:
                logger.exception("could not refresh the Downloads section")
        recordings = sections.get("recordings")
        if recordings is not None:
            try:
                recordings.refresh_progress(self.recording_manager.progress())
            except Exception:
                logger.exception("could not refresh the Recordings section")

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
        with self.db.session_scope() as session:
            channel = RepositoryFactory(session).channels.get_playable_dto(channel_id)
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

        outcome = self.recording_manager.schedule(
            channel_id=channel.id, provider_id=channel.provider_id,
            channel_name=channel.name, source_url=channel.stream_url,
            starts_at=starts_at, ends_at=ends_at, programme_title=title,
            **({} if pad else {"pad_start_seconds": 0, "pad_end_seconds": 0}))

        if not outcome.scheduled:
            self.notification_manager.show(
                title=f"{title or channel.name} is already being recorded",
                message="", type="info", dismissible=True)
            return

        # The EFFECTIVE window, not the guide's — the offsets move it, and a
        # message promising a stop fifteen minutes before the recorder actually
        # stops is the kind of small lie that teaches people to distrust the app.
        window = self.recording_manager.window_of(outcome.recording_id)
        ends_local = to_local(window[1] if window else ends_at)

        if outcome.conflicts:
            # Surfaced now rather than at start time, which is the whole point
            # of detecting it here: the user can still drop one.
            others = ", ".join(name for _rid, name in outcome.conflicts)
            self.notification_manager.show(
                title=f"Recording {title or channel.name} — but it clashes",
                message=(f"This source allows one connection and {others} "
                         f"already wants it at the same time. One of them will "
                         f"not record."),
                type="warning", dismissible=True)
            return

        self.notification_manager.show(
            title=f"Recording {title or channel.name}",
            message=(f"Until {ends_local:%H:%M}. MetaTV has to be running, and "
                     f"it will take this source's connection off whatever you "
                     f"are watching — with a countdown you can cancel."),
            type="info", dismissible=True)

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
