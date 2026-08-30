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
        """Forget one History time group — the heading's own "forget these".

        The window comes from ``bucket_range``, the SAME function that decided
        which heading each row was shown under, so this cannot delete a row the
        group never listed. Scoped to its own group and no further; the ⋯ menu
        keeps "Clear all history".

        Args:
            bucket_key: A key from ``history_buckets.BUCKETS``.
        """
        from metatv.core.history_buckets import BUCKETS_BY_KEY, bucket_range

        bucket = BUCKETS_BY_KEY.get(bucket_key)
        if bucket is None:
            logger.warning(f"Unknown history bucket: {bucket_key!r}")
            return
        not_before, not_after = bucket_range(bucket_key)
        self._confirm_and_clear_history(
            title=f"Clear History — {bucket.label}",
            question=(
                f"{bucket.purge_prompt}\n\n"
                "Everything in the other groups is kept, as are favorites."
            ),
            purge=lambda channels: channels.clear_history_in_range(
                not_before, not_after
            ),
            describe=lambda count: (
                f"Cleared {count} item(s) from {bucket.label}"
                if count else f"Nothing left under {bucket.label}"
            ),
        )

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

