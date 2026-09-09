"""The "Still watching?" end-of-queue confirmation (extracted from ``_StreamingMixin``).

When a queued auto-advance run ends, the off-thread checkpoint tick emits
``_queue_end_detected`` with the ids of every episode the playlist advanced
PAST — those were already written 100%-complete by ``_bg_finalise_episode``
while the queue was still running.  This mixin owns the main-thread prompt that
asks whether the user actually watched them, and both answers' write paths.

Both answers write, and both refresh
--------------------------------------
The prompt asks "Did you watch them?", so **No must undo the auto-mark** — it
used to only downgrade ``last_played_via`` to ``'queue'`` (a greyer glyph) and
leave the episodes flagged watched, which is the opposite of the answer given.
Every write here ends by emitting ``_episode_watch_state_changed`` so the open
series tree re-reads those rows: the auto-mark writes happen off-thread while
the tree is already on screen, and a tree that never hears about them shows a
watch state that is simply out of date (#836 — the user then acts on the stale
view, unmarking the episodes it *did* show and leaving the ones it did not, so
the season ends up with an unwatched hole in the middle of a watched run).
"""

from __future__ import annotations

from loguru import logger
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from metatv.core.repositories import RepositoryFactory
from metatv.gui.dialog_chrome import dialog_buttons


class _QueueEndPromptMixin:
    """"Still watching?" prompt + the two answers' persistence paths."""

    def _on_queue_end_detected(self, auto_episode_ids: list) -> None:
        """Main-thread slot: show "Still here?" prompt after a queue-auto-advance run ends.

        Called when the ``_queue_end_detected`` signal fires (emitted from the
        off-thread checkpoint tick after a queued player window closes with
        ``last_seen_pos > 0``).

        Args:
            auto_episode_ids: Episode DB ids that were auto-advanced (played via
                ``'queue'``). These are episodes at queue indices 1‥last_seen_pos.
                Index 0 is already ``'manual'`` (the user explicitly started it).
        """
        if not auto_episode_ids:
            return
        if not getattr(self, "config", None) or not getattr(
            self.config, "prompt_after_autoplay", True
        ):
            return

        # Build a human-friendly label — show the episode count, not raw ids.
        count = len(auto_episode_ids)
        ep_label = "1 more episode" if count == 1 else f"{count} more episodes"

        dlg = QDialog(self)
        dlg.setWindowTitle("Still watching?")
        dlg.setModal(True)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        msg = QLabel(
            f"The queue auto-advanced through {ep_label}.\n\n"
            "Did you watch them?"
        )
        msg.setWordWrap(True)
        layout.addWidget(msg)

        # Ok/Cancel relabelled rather than Yes/No: same accept/reject slots,
        # and then the same row as every other dialog's.
        btns = dialog_buttons(dlg, ok="Yes")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("No")
        layout.addWidget(btns)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            # Confirmed — promote to 'manual' so they render solid and the
            # resume anchor advances past them.
            self.executor.submit(self._bg_promote_queue_episodes, auto_episode_ids)
        else:
            # Denied — the queue marked them watched while nobody was watching,
            # so take the mark back rather than merely greying it.
            self.executor.submit(self._bg_unmark_queue_episodes, auto_episode_ids)

    def _bg_promote_queue_episodes(self, episode_ids: list) -> None:
        """Worker: flip ``last_played_via`` to ``'manual'`` for confirmed episodes.

        Runs off the main thread.  Uses ``mark_episodes_as_engaged`` from the
        episode repository — a thin bulk updater that commits once.

        Args:
            episode_ids: DB ids of the episodes to promote.
        """
        try:
            with self.db.session_scope() as session:
                repos = RepositoryFactory(session)
                updated = repos.episodes.mark_episodes_as_engaged(episode_ids)
                logger.info(
                    f"Promoted {updated}/{len(episode_ids)} queue-watched episode(s) "
                    "to manual engagement after user confirmation"
                )
        except Exception as exc:
            logger.warning(f"Failed to promote queue-watched episodes: {exc}")
        self._episode_watch_state_changed.emit(list(episode_ids))

    def _bg_unmark_queue_episodes(self, episode_ids: list) -> None:
        """Worker: undo the auto-mark for episodes the user says they did not watch.

        The queue path writes each auto-advanced episode 100%-complete as the
        playlist moves past it, so answering "No" has to actively clear that —
        the same coherent field write the context menu's "Mark unwatched" makes,
        through the same repository chokepoint.

        Args:
            episode_ids: DB ids of the episodes to unmark.
        """
        try:
            with self.db.session_scope() as session:
                repos = RepositoryFactory(session)
                updated = repos.episodes.mark_watched_bulk(episode_ids, False)
                logger.info(
                    f"Unmarked {updated}/{len(episode_ids)} queue-watched episode(s) — "
                    "user answered No to the queue-end prompt"
                )
        except Exception as exc:
            logger.warning(f"Failed to unmark queue-watched episodes: {exc}")
        self._episode_watch_state_changed.emit(list(episode_ids))
