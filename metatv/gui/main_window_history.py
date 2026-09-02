"""MainWindow's playback-history surface: loading it, and forgetting it.

Split out of ``main_window_favorites.py``, which had become a grab-bag of forty
methods spanning ratings, favorites, the queue, alerts, retry AND history. These
six are a coherent cluster — they load the History section and clear it — and
none of them touches the ``ChannelStateBus`` contract, which is the one thing
CLAUDE.md says not to move without re-reading first (verified, not assumed:
zero references across all six).

Extracted while adding the per-group clear that History's time headings need.
The alternative was re-baselining a file that is a grab-bag precisely because
nothing ever pushed back on it growing.
"""

from __future__ import annotations

from loguru import logger

from metatv.core.repositories import RepositoryFactory


class _HistoryMixin:
    """History loading and clearing for MainWindow (uses self.db, self.status_bar)."""

    def load_history(self):
        """Load playback history into sidebar"""
        if "history" in self.sidebar_sections:
            self.sidebar_sections["history"].refresh()

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

    def _confirm_and_clear_history(self, *, title: str, question: str,
                                   purge, describe) -> None:
        """Ask, purge, report, reload — the shape all three clears share.

        Refreshing Favorites too is not incidental: a cleared row can be a
        favorite, and that section would otherwise keep showing the old count.

        Args:
            title: Dialog title.
            question: Body text; says what SURVIVES as well as what goes.
            purge: ``channels_repo -> int | None``.
            describe: ``count -> str`` for the status bar.
        """
        from PyQt6.QtWidgets import QMessageBox

        reply = QMessageBox.question(
            self, title, question,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            with self.db.session_scope() as session:
                count = purge(RepositoryFactory(session).channels)
            self.status_bar.showMessage(describe(count))
            self.load_history()
            self.load_favorites()
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to clear history ({title}): {e}")
            self.status_bar.showMessage(f"Error clearing history: {e}")

    def clear_history_older_than(self, days: int) -> None:
        """Forget playback older than ``days``, keeping everything since.

        Names what SURVIVES, which is the whole reason to offer it.
        """
        self._confirm_and_clear_history(
            title="Clear Old History",
            question=(
                f"Forget everything you played more than {days} days ago?\n\n"
                "Anything played since then is kept, as are favorites."
            ),
            purge=lambda channels: channels.clear_history_older_than(days),
            describe=lambda count: (
                f"Cleared {count} item(s) older than {days} days"
                if count else "Nothing was older than that"
            ),
        )

    def clear_history_group(self, bucket_key: str) -> None:
        """Forget one History time group at once, offering Undo instead of asking first.

        A per-group misclick is cheap to undo, so unlike the two big clears
        (``clear_history_older_than``, ``clear_history``) this never shows a
        confirmation dialog — it purges immediately and hands the user an
        Undo toast instead. The window comes from ``bucket_range``, the SAME
        function that decided which heading each row was shown under, so
        this cannot delete a row the group never listed.

        Args:
            bucket_key: A key from ``history_buckets.BUCKETS``.
        """
        from metatv.core.history_buckets import BUCKETS_BY_KEY, bucket_range

        bucket = BUCKETS_BY_KEY.get(bucket_key)
        if bucket is None:
            logger.warning(f"Unknown history bucket: {bucket_key!r}")
            return
        not_before, not_after = bucket_range(bucket_key)
        try:
            with self.db.session_scope() as session:
                count, snapshot = RepositoryFactory(session).channels.clear_history_in_range(
                    not_before, not_after
                )
            self.load_history()
            self.load_favorites()
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to clear history group {bucket.label!r}: {e}")
            self.status_bar.showMessage(f"Error clearing history: {e}")
            return

        if not count:
            self.status_bar.showMessage(f"Nothing to forget under {bucket.label}")
            return

        self.status_bar.showMessage(f"Cleared {count} item(s) from {bucket.label}")
        self.notification_manager.show(
            title="History cleared",
            message=f"Forgot {count} item(s) under {bucket.label}.",
            type="info",
            auto_dismiss_ms=8000,
            actions=[("Undo", lambda: self._undo_history_group_clear(snapshot))],
        )

    def _undo_history_group_clear(self, snapshot) -> None:
        """Restore a per-group clear's snapshot — the Undo toast's callback.

        A title re-played during the toast's lifetime keeps its newer state:
        :meth:`~metatv.core.repositories.channel_history._ChannelHistoryMixin.restore_history_snapshot`
        only restores rows still ``NULL``, so this can never move history
        backwards. Wrapped in try/except so a failed undo cannot crash the
        toast click.

        Args:
            snapshot: The ``(channel_id, last_played, play_count)`` tuples
                returned by the ``clear_history_in_range`` call being undone.
        """
        try:
            with self.db.session_scope() as session:
                restored = RepositoryFactory(session).channels.restore_history_snapshot(
                    snapshot
                )
            self.load_history()
            self.load_favorites()
            self.status_bar.showMessage(f"Restored {restored} item(s)")
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to undo history clear: {e}")
            self.status_bar.showMessage(f"Error restoring history: {e}")

    def clear_history(self):
        """Clear all history — the ⋯ menu's all-or-nothing option."""
        self._confirm_and_clear_history(
            title="Clear History",
            question=(
                "Are you sure you want to clear all playback history?\n\n"
                "This will not remove favorites."
            ),
            purge=lambda channels: channels.clear_history(),
            describe=lambda _count: "History cleared",
        )

