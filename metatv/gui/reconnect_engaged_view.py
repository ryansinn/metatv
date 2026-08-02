"""Reconnect Engaged Content — recover orphaned favorites/history/queue rows.

When a source is deleted or expires, engaged channels (favorited, played, or
queued — see ``ChannelRepository._engaged_channel_predicate``) are deliberately
KEPT rather than pruned, so the user never loses a favorite/history row outright.
But nothing re-points them at an equivalent copy a still-active source carries —
they just sit there as orphans pointing at a source that is gone.

This view lists every such orphan, proposes the best-quality live replacement
sharing the same stored ``content_key`` (never a title heuristic — see
``ChannelRepository.get_reconnect_candidates``), and lets the user move the
engagement (favorite/history/resume-position/rating/queue membership) onto the
live channel one row at a time (**Reconnect**) or all matched rows at once
(**Reconnect All**). Nothing moves automatically — reconnecting a user's
favorites/history is explicit-only (CLAUDE.md: user tags/ratings/favorites/
history are sacrosanct). Rows with no available match are still listed, marked
plainly as unmatched (mirror-not-cage: nothing is silently dropped).

All data loads asynchronously via the ``MainWindow._run_query`` seam and returns
frozen DTOs (no ORM objects cross the boundary); the reconnect mutation itself is
a cheap single-row write run synchronously on the main thread (same pattern as
``_toggle_favorite_by_id`` / ``_toggle_rating``).
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QLabel, QPushButton, QFrame,
)
from PyQt6.QtCore import pyqtSignal
from loguru import logger

from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.dtos import ReconnectCandidateDTO
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme


class ReconnectEngagedView(QWidget):
    """Tools view: orphaned engaged content + one-click reconnect to a live copy.

    Opening it (``on_activate``) loads the candidate list off-thread.
    ``reload`` re-runs the load (called after a reconnect settles the counts).
    """

    done = pyqtSignal()

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self._token = [0]
        self._candidates: list[ReconnectCandidateDTO] = []
        self._build_ui()

    # ── UI scaffold ─────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        top_bar = QHBoxLayout()
        back_btn = QPushButton(_icons.prev_icon + " Back")
        back_btn.setToolTip("Return to channel list")
        back_btn.clicked.connect(self.done.emit)
        title = QLabel(f"{_icons.reconnect_icon}  Reconnect Engaged Content")
        title.setStyleSheet(_theme.DETAIL_TITLE)
        top_bar.addWidget(back_btn)
        top_bar.addWidget(title)
        top_bar.addStretch()
        self._reconnect_all_btn = QPushButton(f"{_icons.reconnect_icon} Reconnect All")
        self._reconnect_all_btn.setToolTip(
            "Move every matched row's engagement onto its proposed live replacement"
        )
        self._reconnect_all_btn.setStyleSheet(_theme.LINK_BTN_SM)
        self._reconnect_all_btn.clicked.connect(self._on_reconnect_all_clicked)
        self._reconnect_all_btn.setEnabled(False)
        top_bar.addWidget(self._reconnect_all_btn)

        hint = QLabel(
            f"{_icons.info_icon}  When a source is removed, your favorited/watched/"
            "queued content from it is kept but stranded. These rows have a "
            "same-title match on one of your active sources — reconnecting moves "
            "your favorite, watch history, resume position, rating, and queue "
            "membership onto the live copy. Nothing moves automatically."
        )
        hint.setStyleSheet(_theme.SECTION_HINT)
        hint.setWordWrap(True)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self._rows_layout = QVBoxLayout(content)
        scroll.setWidget(content)

        layout.addLayout(top_bar)
        layout.addWidget(hint)
        layout.addWidget(scroll)

    # ── Lifecycle ───────────────────────────────────────────────────────────

    def on_activate(self) -> None:
        """Show a loading state, then kick the async load."""
        self._reconnect_all_btn.setEnabled(False)
        self._clear_layout(self._rows_layout)
        loading = QLabel("Loading…")
        loading.setStyleSheet(_theme.SECTION_HINT)
        self._rows_layout.addWidget(loading)
        self._load()

    def on_deactivate(self) -> None:
        """Cancel any pending load (bump the query token)."""
        self._token[0] += 1

    def reload(self) -> None:
        """Re-run the load when visible (called after a reconnect settles)."""
        if self.isVisible():
            self._load()

    # ── Data loading ────────────────────────────────────────────────────────

    def _load(self) -> None:
        self.main_window._run_query(
            self._query_candidates,
            self._on_candidates_loaded,
            token_ref=self._token,
            on_error=self._on_load_error,
        )

    @staticmethod
    def _query_candidates(repos) -> list[ReconnectCandidateDTO]:
        hidden = set(repos.providers.get_hidden_provider_ids())
        return repos.channels.get_reconnect_candidates(hidden)

    # ── Render ──────────────────────────────────────────────────────────────

    def _on_candidates_loaded(self, candidates: list[ReconnectCandidateDTO]) -> None:
        self._candidates = candidates
        self._clear_layout(self._rows_layout)

        matched = sum(1 for c in candidates if c.match is not None)
        self._reconnect_all_btn.setEnabled(matched > 0)

        if not candidates:
            done = QLabel(
                f"{_icons.notification_success_icon}  No orphaned engaged content — "
                "everything you've favorited, watched, or queued is on an active source."
            )
            done.setStyleSheet(_theme.SECTION_HINT)
            self._rows_layout.addWidget(done)
            return

        for candidate in candidates:
            self._rows_layout.addWidget(self._candidate_row(candidate))
        self._rows_layout.addStretch()

    def _candidate_row(self, candidate: ReconnectCandidateDTO) -> QWidget:
        row = QFrame()
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(0, 6, 0, 10)

        mtype_icon = {
            "movie": _icons.movie_icon, "series": _icons.series_icon,
        }.get(candidate.media_type or "", _icons.unknown_icon)
        title = candidate.detected_title or candidate.orphan_name
        year = f" ({candidate.detected_year})" if candidate.detected_year else ""
        header = QLabel(f"{mtype_icon}  {title}{year}  ·  was on {candidate.provider_name}")
        header.setStyleSheet(_theme.SECTION_HDR)
        header.setWordWrap(True)
        row_layout.addWidget(header)

        engaged_line = QLabel(f"    {self._engagement_summary(candidate)}")
        engaged_line.setStyleSheet(_theme.SECTION_HINT)
        engaged_line.setWordWrap(True)
        row_layout.addWidget(engaged_line)

        action_row = QHBoxLayout()
        if candidate.match is not None:
            match = candidate.match
            match_title = match.detected_title or match.name
            quality = f" ({match.detected_quality})" if match.detected_quality else ""
            match_label = QLabel(
                f"    {_icons.notification_success_icon} Match: {match_title}{quality} "
                f"on {match.provider_name}"
            )
            match_label.setStyleSheet(_theme.SECTION_HINT)
            match_label.setWordWrap(True)
            action_row.addWidget(match_label, 1)

            reconnect_btn = QPushButton(f"{_icons.reconnect_icon} Reconnect")
            reconnect_btn.setToolTip("Move this row's engagement onto the matched live channel")
            reconnect_btn.setStyleSheet(_theme.PANEL_BTN)
            orphan_id, live_id = candidate.orphan_id, match.channel_id
            reconnect_btn.clicked.connect(
                lambda _checked=False, o=orphan_id, l=live_id: self._on_reconnect_clicked(o, l)
            )
            action_row.addWidget(reconnect_btn)
        else:
            unmatched_label = QLabel(
                f"    {_icons.notification_warning_icon} No live match found on an active source"
            )
            unmatched_label.setStyleSheet(_theme.SECTION_HINT)
            unmatched_label.setWordWrap(True)
            action_row.addWidget(unmatched_label, 1)

        row_layout.addLayout(action_row)
        return row

    def _engagement_summary(self, candidate: ReconnectCandidateDTO) -> str:
        """One line describing exactly what a reconnect would move for this row."""
        parts: list[str] = []
        if candidate.is_favorite:
            parts.append(f"{_icons.favorite_icon} favorited")
        if candidate.last_played is not None:
            parts.append(f"{_icons.history_icon} watched")
        if candidate.play_count:
            parts.append(f"played {candidate.play_count}×")
        if candidate.watch_completed:
            parts.append(f"{_icons.watched_icon} completed")
        elif candidate.watch_progress:
            parts.append(f"{candidate.watch_percent}% watched")
        if candidate.user_rating == 1:
            parts.append(_icons.like_icon)
        elif candidate.user_rating == -1:
            parts.append(_icons.dislike_icon)
        if candidate.in_queue:
            parts.append(f"{_icons.queue_icon} queued")
        return "Will move: " + (", ".join(parts) if parts else "engagement")

    # ── Reconnect actions ───────────────────────────────────────────────────

    def _on_reconnect_clicked(self, orphan_id: str, live_id: str) -> None:
        if self._reconnect_one(orphan_id, live_id):
            self.main_window.notification_manager.show(
                title="Reconnected", message="Engagement moved to the live copy.",
                type="success",
            )
        self._after_reconnect()

    def _on_reconnect_all_clicked(self) -> None:
        pairs = [
            (c.orphan_id, c.match.channel_id)
            for c in self._candidates if c.match is not None
        ]
        succeeded = 0
        for orphan_id, live_id in pairs:
            if self._reconnect_one(orphan_id, live_id):
                succeeded += 1
        self.main_window.notification_manager.show(
            title="Reconnect All",
            message=f"Reconnected {succeeded} of {len(pairs)} matched item(s).",
            type="success" if succeeded == len(pairs) else "warning",
        )
        self._after_reconnect()

    def _reconnect_one(self, orphan_id: str, live_id: str) -> bool:
        """Run one reconnect in its own transaction. Returns True on success."""
        try:
            with self.main_window.db.session_scope() as session:
                RepositoryFactory(session).channels.reconnect_engaged_content(orphan_id, live_id)
            return True
        except Exception as exc:  # noqa: BLE001 — surfaced as a toast, not a crash
            logger.error(f"Reconnect failed ({orphan_id!r} -> {live_id!r}): {exc}")
            self.main_window.notification_manager.show(
                title="Reconnect Failed", message=str(exc), type="error",
            )
            return False

    def _after_reconnect(self) -> None:
        """Refresh this view plus the sidebar sections engagement can land in."""
        self.reload()
        self.main_window.load_favorites()
        self.main_window.load_history()
        self.main_window._refresh_queue_section()

    # ── Error / cleanup ─────────────────────────────────────────────────────

    def _on_load_error(self, exc: Exception) -> None:
        logger.error(f"Reconnect-candidates load failed: {exc}")
        self._clear_layout(self._rows_layout)
        err = QLabel(f"{_icons.notification_warning_icon}  Couldn't load this list")
        err.setStyleSheet(_theme.SECTION_HINT)
        self._rows_layout.addWidget(err)

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
