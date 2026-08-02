"""MetadataEnrichmentView — Tools-menu progress + controls for the background
metadata enrichment queue (roadmap #249, ``metatv/core/metadata_enrichment_queue.py``).

Modeled on ``missing_tmdb_view.py``'s shape (back bar, section headers, scroll
area) but the data source is different: instead of a one-shot query on
``on_activate``, this view tracks a LIVE background pass via
``MetadataEnrichmentQueue``'s signals — the queue itself is owned by
``MainWindow`` and keeps running whether or not this view is visible; the view
only starts/stops *listening* to it in ``on_activate``/``on_deactivate``
(symmetric activate/deactivate — CLAUDE.md view-lifecycle rule), matching
``get_status()`` for an immediate snapshot on open in case a pass is already
mid-flight (auto-started at launch, or left running from a prior visit).
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QProgressBar, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)
from PyQt6.QtCore import pyqtSignal
from loguru import logger

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme

# Recent-failures rows shown (the queue itself keeps a slightly larger ring —
# see metadata_enrichment_queue._MAX_FAILURE_LOG).
_VISIBLE_FAILURES = 10


class MetadataEnrichmentView(QWidget):
    """Tools view: start/pause/resume/cancel the background enrichment queue.

    ``on_activate`` connects the queue's signals and renders its current
    snapshot; ``on_deactivate`` disconnects them (the queue itself is
    independent of this view's visibility — it is owned by ``MainWindow`` and
    keeps draining in the background either way).
    """

    done = pyqtSignal()

    def __init__(self, main_window) -> None:
        super().__init__()
        self.main_window = main_window
        self._connected = False
        self._build_ui()

    # ── UI scaffold ─────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        top_bar = QHBoxLayout()
        back_btn = QPushButton(_icons.prev_icon + " Back")
        back_btn.setToolTip("Return to channel list")
        back_btn.clicked.connect(self.done.emit)
        title = QLabel(f"{_icons.metadata_enrich_icon}  Background Metadata Enrichment")
        title.setStyleSheet(_theme.DETAIL_TITLE)
        top_bar.addWidget(back_btn)
        top_bar.addWidget(title)
        top_bar.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)

        content_layout.addWidget(self._section_header("Status"))
        hint = QLabel(
            f"{_icons.info_icon}  Fills in missing/stale posters, plot, cast and "
            "ratings across your library — favorited, queued, and recently played "
            "titles first. Safe to pause or close the app; it resumes where it "
            "left off."
        )
        hint.setStyleSheet(_theme.SECTION_HINT)
        hint.setWordWrap(True)
        content_layout.addWidget(hint)

        self._state_label = QLabel("Idle")
        self._state_label.setStyleSheet(_theme.SECTION_HDR)
        content_layout.addWidget(self._state_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setMinimum(0)
        self._progress_bar.setMaximum(0)  # indeterminate until a total is known
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setStyleSheet(_theme.PROGRESS_BAR)
        content_layout.addWidget(self._progress_bar)

        self._current_label = QLabel("")
        self._current_label.setStyleSheet(_theme.SECTION_HINT)
        self._current_label.setWordWrap(True)
        content_layout.addWidget(self._current_label)

        self._failed_label = QLabel("")
        self._failed_label.setStyleSheet(_theme.SECTION_HINT)
        content_layout.addWidget(self._failed_label)

        controls = QHBoxLayout()
        self._start_btn = QPushButton(f"{_icons.play_icon} Start")
        self._start_btn.setToolTip("Begin (or resume) a background enrichment pass")
        self._start_btn.setStyleSheet(_theme.SAVE_BTN)
        self._start_btn.clicked.connect(self._on_start_clicked)
        controls.addWidget(self._start_btn)

        self._pause_btn = QPushButton(f"{_icons.enrich_pause_icon} Pause")
        self._pause_btn.setToolTip("Pause after the current title finishes")
        self._pause_btn.setStyleSheet(_theme.PANEL_BTN)
        self._pause_btn.clicked.connect(self._on_pause_clicked)
        controls.addWidget(self._pause_btn)

        self._cancel_btn = QPushButton(f"{_icons.enrich_cancel_icon} Cancel")
        self._cancel_btn.setToolTip("Stop this pass after the current title finishes")
        self._cancel_btn.setStyleSheet(_theme.DELETE_BTN)
        self._cancel_btn.clicked.connect(self._on_cancel_clicked)
        controls.addWidget(self._cancel_btn)

        controls.addStretch()
        content_layout.addLayout(controls)

        content_layout.addSpacing(16)
        content_layout.addWidget(self._section_header("Recent Failures"))
        self._failures_panel = QWidget()
        self._failures_layout = QVBoxLayout(self._failures_panel)
        self._failures_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(self._failures_panel)
        content_layout.addStretch()

        scroll.setWidget(content)
        layout.addLayout(top_bar)
        layout.addWidget(scroll)

    def _section_header(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(_theme.SECTION_HDR_LG)
        return label

    # ── Lifecycle ───────────────────────────────────────────────────────────

    def on_activate(self) -> None:
        """Connect the queue's live signals and render its current snapshot."""
        queue = self.main_window.metadata_enrichment_queue
        if not self._connected:
            queue.progress_changed.connect(self._on_progress)
            queue.state_changed.connect(self._on_state)
            queue.enrichment_failed.connect(self._on_failure)
            self._connected = True
        self._render(queue.get_status())

    def on_deactivate(self) -> None:
        """Disconnect the queue's signals (the queue itself keeps running)."""
        if self._connected:
            queue = self.main_window.metadata_enrichment_queue
            queue.progress_changed.disconnect(self._on_progress)
            queue.state_changed.disconnect(self._on_state)
            queue.enrichment_failed.disconnect(self._on_failure)
            self._connected = False

    # ── Controls ────────────────────────────────────────────────────────────

    def _on_start_clicked(self) -> None:
        queue = self.main_window.metadata_enrichment_queue
        status = queue.get_status()
        if status.state == "paused":
            queue.resume()
        else:
            queue.start()

    def _on_pause_clicked(self) -> None:
        self.main_window.metadata_enrichment_queue.pause()

    def _on_cancel_clicked(self) -> None:
        self.main_window.metadata_enrichment_queue.cancel()

    # ── Live signal slots (main thread — queued-connection delivery) ────────

    def _on_progress(self, done: int, total: int, current_title: str) -> None:
        self._render_progress(done, total, current_title)

    def _on_state(self, state: str) -> None:
        self._render_state(state)

    def _on_failure(self, title: str, reason: str) -> None:
        logger.debug("metadata_enrichment_view: failure — {} ({})", title, reason)
        self._render(self.main_window.metadata_enrichment_queue.get_status())

    # ── Render ──────────────────────────────────────────────────────────────

    def _render(self, status) -> None:
        self._render_state(status.state)
        self._render_progress(status.done, status.total, status.current_title)
        self._render_failures(status.failed_count, status.recent_failures)

    def _render_state(self, state: str) -> None:
        labels = {
            "idle": (f"{_icons.playback_neutral_icon}  Idle — no pass has run yet", False),
            "running": (f"{_icons.notification_progress_icon}  Running…", True),
            "paused": (f"{_icons.enrich_pause_icon}  Paused", False),
            "cancelled": (f"{_icons.notification_warning_icon}  Cancelled", False),
            "finished": (f"{_icons.notification_success_icon}  Up to date", False),
        }
        text, running = labels.get(state, (state, False))
        self._state_label.setText(text)

        self._start_btn.setEnabled(not running)
        self._start_btn.setText(
            f"{_icons.play_icon} " + ("Resume" if state == "paused" else "Start")
        )
        self._pause_btn.setEnabled(running)
        self._cancel_btn.setEnabled(running or state == "paused")

    def _render_progress(self, done: int, total: int, current_title: str) -> None:
        if total > 0:
            self._progress_bar.setMaximum(total)
            self._progress_bar.setValue(min(done, total))
            self._progress_bar.setFormat(f"{done:,} / {total:,}")
        else:
            self._progress_bar.setMaximum(0)  # indeterminate — total not yet known
            self._progress_bar.setValue(0)
            self._progress_bar.setFormat("")
        self._current_label.setText(f"Now enriching: {current_title}" if current_title else "")

    def _render_failures(self, failed_count: int, recent_failures) -> None:
        self._failed_label.setText(
            f"{_icons.notification_warning_icon}  {failed_count:,} failed this pass"
            if failed_count else ""
        )
        self._clear_layout(self._failures_layout)
        if not recent_failures:
            empty = QLabel(f"{_icons.notification_success_icon}  No failures yet.")
            empty.setStyleSheet(_theme.SECTION_HINT)
            self._failures_layout.addWidget(empty)
            return
        for title, reason in list(recent_failures)[-_VISIBLE_FAILURES:]:
            row = QLabel(f"{_icons.notification_error_icon}  {title} — {reason}")
            row.setStyleSheet(_theme.SECTION_HINT)
            row.setWordWrap(True)
            self._failures_layout.addWidget(row)

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
