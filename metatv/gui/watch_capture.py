"""Watch-progress capture — resume position + completion, extracted from
``main_window_streaming.py`` (its own module because that file is baselined
at its current line count in ``tests/code_health_baseline.json``, and a
pinned file may only shrink).

Mixed in via::

    class _StreamingMixin(_WatchCaptureMixin): ...

All methods access state set on the host (``MainWindow``) — ``self.db``,
``self.executor``, ``self.config``, ``self.player_manager``,
``self._watch_tracking``, ``self.load_history``, ``self.channel_state_bus``.

A periodic checkpoint persists each active play's position/completion via the
repository chokepoint, independent of the playback-health readout so it stays
correct under Split Streams (each window captured against the content IT
plays).

HIST-1 (2026-09-03): a play never appeared in History because the old
``_record_play`` called ``self.load_history()`` synchronously, immediately
after submitting the DB write to the executor — the refresh ran before the
write committed. ``_WatchNotifier.history_changed`` closes that race:
``_bg_mark_played`` emits it only AFTER its ``session_scope()`` block commits,
and the signal is delivered to the main thread's ``_on_history_changed`` slot
via Qt's normal queued-connection delivery, which also drives the details
pane's Resume state via ``channel_state_bus.publish``.
"""

from __future__ import annotations

from loguru import logger
from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from metatv.core.repositories import RepositoryFactory


class _WatchNotifier(QObject):
    """Tiny QObject carrying the signal watch-capture workers emit on.

    PyQt signals cannot live on a plain mixin (``_WatchCaptureMixin`` is not
    a ``QObject``) — this class exists solely so an off-thread worker can
    safely notify the main thread that a play/progress write committed.
    ``_start_watch_capture`` constructs it on the main thread (never a
    worker), so the cross-thread ``emit`` below is Qt's normal queued
    connection, not a race.
    """

    history_changed = pyqtSignal(object)  # channel_id (str), or None


class _WatchCaptureMixin:
    """Mixin providing watch-progress capture (resume position + completion)."""

    # ---- Watch-progress capture (resume position + completion) ----------------
    # A periodic checkpoint persists each active play's position/completion via the
    # repository chokepoint, independent of the playback-health readout so it stays
    # correct under Split Streams (each window captured against the content IT plays).

    def _start_watch_capture(self) -> None:
        """Start (or resume) the periodic watch-progress checkpoint timer."""
        if "_watch_notifier" not in self.__dict__:
            self._watch_notifier = _WatchNotifier(self)
            self._watch_notifier.history_changed.connect(self._on_history_changed)
        if not hasattr(self, "_watch_tracking"):
            self._watch_tracking = {}
        if getattr(self, "_watch_checkpoint_timer", None) is None:
            self._watch_checkpoint_timer = QTimer(self)
            self._watch_checkpoint_timer.setInterval(20_000)  # 20s checkpoint
            self._watch_checkpoint_timer.timeout.connect(self._watch_checkpoint_tick)
            self._register_cleanable(
                "watch_checkpoint_timer", self._watch_checkpoint_timer.stop
            )
        if not self._watch_checkpoint_timer.isActive():
            self._watch_checkpoint_timer.start()

    def _on_history_changed(self, channel_id) -> None:
        """Main-thread slot: a play/progress write committed — refresh dependents.

        Connected (queued, cross-thread-safe) to ``_WatchNotifier.history_changed``,
        emitted by ``_bg_mark_played`` only after its DB write commits — this is
        what closes the HIST-1 race, where the old synchronous ``load_history()``
        call in ``_record_play`` ran before the write it was supposed to reflect.
        Also republishes the channel on ``channel_state_bus`` so the details
        pane's Play/Resume state (frozen after playback ends otherwise) re-reads
        authoritatively.
        """
        self.load_history()
        if channel_id:
            self.channel_state_bus.publish(channel_id)

    def _watch_checkpoint_tick(self) -> None:
        """Timer tick (main thread): sample + persist each active play's progress.

        For queued episode plays, passes a *snapshot* of the mutable tracking
        dict to the worker — the worker may increment ``last_seen_pos`` in-place
        via ``_update_last_seen_pos``; the snapshot lets the worker reason about
        the queue without racing against future ticks.  Non-episode and
        single-episode tracks continue to pass ``dict(info)`` as before.
        """
        keys = self.player_manager.active_keys()
        tracking = getattr(self, "_watch_tracking", {})
        # Finalise + drop tracking for windows that have closed between ticks.
        for k in list(tracking.keys()):
            if k not in keys:
                info = tracking.pop(k, None)
                if info and info.get("media_type") == "episode" and info.get("queue"):
                    # Instance disappeared — finalise the episode that was playing
                    # at last_seen_pos so its progress isn't lost between ticks.
                    pos = info.get("last_seen_pos", 0)
                    queue = info["queue"]
                    if 0 <= pos < len(queue):
                        self.executor.submit(
                            self._bg_finalise_episode,
                            queue[pos]["content_id"],
                            "queue" if pos > 0 else info.get("played_via", "manual"),
                        )
                    # If the queue advanced past the first episode, emit the
                    # queue-end signal so the main thread can show "Still here?".
                    # Episodes at indices 1..pos (inclusive) were auto-advanced;
                    # index 0 is the user-started episode (last_played_via="manual").
                    if pos > 0 and getattr(self.config, "prompt_after_autoplay", True):
                        auto_ids = [
                            queue[i]["content_id"]
                            for i in range(1, min(pos + 1, len(queue)))
                        ]
                        if auto_ids:
                            self._queue_end_detected.emit(auto_ids)
        if not keys:
            self._watch_checkpoint_timer.stop()
            return
        for key in keys:
            info = tracking.get(key)
            if info:
                self.executor.submit(self._bg_capture_watch, key, dict(info))

    def _bg_finalise_episode(self, content_id: str, played_via: str) -> None:
        """Worker: mark an episode 100% complete when it is auto-advanced past.

        Called when mpv's playlist-pos advances beyond an episode (meaning mpv
        played it to the end) or when the player window closes with a queued
        episode in flight.  Using ``record_watch_progress`` at 100% honours the
        sticky-completion rule in the repository — a later rewatch can still
        update the resume point without un-completing.

        Args:
            content_id: The episode DB id to finalise.
            played_via: ``"manual"`` for the user-started episode, ``"queue"``
                for every auto-advanced one.
        """
        try:
            threshold = getattr(self.config, "watch_complete_threshold", 0.9)
            with self.db.session_scope() as session:
                repos = RepositoryFactory(session)
                # Synthesise a 100%-complete read so record_watch_progress sets
                # watch_completed=True (any dur > 0 with pos==dur crosses threshold).
                repos.episodes.record_watch_progress(
                    content_id, 1.0, 1.0, threshold, played_via
                )
        except Exception as exc:
            logger.debug(f"Episode finalise failed for {content_id!r}: {exc}")

    def _bg_capture_watch(self, key: str, info: dict) -> None:
        """Worker: read mpv position for *key* and persist watch progress.

        For queued episode plays (``info["queue"]`` present) the worker:
        1. Reads ``playlist-pos`` alongside ``time-pos`` / ``duration``.
        2. Finalises every episode the playlist has auto-advanced past since
           the previous tick (``last_seen_pos`` < current pos) by calling
           ``_bg_finalise_episode`` — those episodes played to the end.
        3. Records live progress for the *current* episode (at ``playlist-pos``)
           via ``record_watch_progress`` so partial state is not lost.

        For single-episode and movie tracks the behaviour is unchanged.

        Args:
            key: Player instance key (from ``player_manager.resolve_key``).
            info: Snapshot of the tracking entry at the time the tick fired.
                  Mutating it does not affect the live tracking dict; the
                  ``last_seen_pos`` update is applied to the *live* dict via
                  ``_update_last_seen_pos``.
        """
        try:
            queue = info.get("queue")
            if queue:
                # Queued-episode branch: follow playlist-pos.
                props = self.player_manager.get_properties(
                    ["time-pos", "duration", "playlist-pos"], key=key
                )
                pos_s = props.get("time-pos")
                dur_s = props.get("duration")
                pl_pos = props.get("playlist-pos")

                # playlist-pos is None when mpv is idle / finished.
                if pl_pos is None or pos_s is None:
                    return

                # Guard: playlist-pos may briefly exceed our queue length
                # (e.g. mpv adds an item between play and our tick).
                if not (0 <= pl_pos < len(queue)):
                    return

                threshold = getattr(self.config, "watch_complete_threshold", 0.9)
                last_pos = info.get("last_seen_pos", 0)

                # Finalise every episode that the playlist advanced past since
                # the last tick.  Each one played to the end (mpv auto-advanced).
                if pl_pos > last_pos:
                    for passed_idx in range(last_pos, pl_pos):
                        passed = queue[passed_idx]
                        via = "manual" if passed_idx == 0 else "queue"
                        # Schedule the finalise in this same worker call — we're
                        # already off the main thread so direct call is fine.
                        self._bg_finalise_episode(passed["content_id"], via)
                    # Update last_seen_pos in the LIVE tracking dict so the next
                    # tick doesn't re-finalise the same episodes.
                    self._update_last_seen_pos(key, pl_pos)

                # Record live progress for the currently-playing episode.
                if dur_s and dur_s > 0:
                    current = queue[pl_pos]
                    via = "manual" if pl_pos == 0 else "queue"
                    with self.db.session_scope() as session:
                        repos = RepositoryFactory(session)
                        repos.episodes.record_watch_progress(
                            current["content_id"], pos_s, dur_s, threshold, via
                        )
            else:
                # Single-episode / movie branch: unchanged behaviour.
                props = self.player_manager.get_properties(["time-pos", "duration"], key=key)
                pos_s = props.get("time-pos")
                dur_s = props.get("duration")
                if pos_s is None or not dur_s or dur_s <= 0:
                    return
                threshold = getattr(self.config, "watch_complete_threshold", 0.9)
                with self.db.session_scope() as session:
                    repos = RepositoryFactory(session)
                    played_via = info.get("played_via", "manual")
                    if info.get("media_type") == "episode":
                        repos.episodes.record_watch_progress(
                            info["content_id"], pos_s, dur_s, threshold, played_via
                        )
                    else:
                        repos.channels.record_watch_progress(
                            info["content_id"], pos_s, dur_s, threshold, played_via
                        )
        except Exception as e:
            logger.debug(f"Watch-progress capture failed for {key}: {e}")

    def _update_last_seen_pos(self, key: str, new_pos: int) -> None:
        """Main-thread-safe update of ``last_seen_pos`` in the live tracking dict.

        Called from the off-thread ``_bg_capture_watch`` worker.  The GIL makes
        this single dict-item assignment atomic in CPython, so no additional
        locking is needed here — but callers must never read-modify-write the
        nested dict in a non-atomic way from the worker thread.

        Args:
            key: Player instance key.
            new_pos: The new ``last_seen_pos`` value (current ``playlist-pos``).
        """
        tracking = getattr(self, "_watch_tracking", {})
        live = tracking.get(key)
        if live is not None and live.get("queue") is not None:
            live["last_seen_pos"] = new_pos
