"""MigrationProgressWidget — corner-overlay panel that shows migration task progress.

Positioned in the same bottom-right overlay lane as ``NotificationWidget``.
One row per task: status glyph, label, progress bar, percentage.  The panel
is non-dismissible while tasks run and auto-hides ~2 s after ``all_finished``.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from loguru import logger

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme

# Auto-hide delay after all_finished fires (ms)
_HIDE_DELAY_MS = 2_000


class _TaskRow(QWidget):
    """Single row: ``[glyph]  label  [progress bar]  pct%``."""

    def __init__(self, task_id: str, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.task_id = task_id
        self._done = False

        # Two-line row so a long task label is never squeezed by the bar:
        #   line 1 — [glyph]  label  (label gets the full panel width)
        #   line 2 —          [────── progress bar ──────]  pct%
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 3, 0, 3)
        outer.setSpacing(3)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)

        self._glyph = QLabel(_icons.migration_pending_icon)
        self._glyph.setFixedWidth(14)
        self._glyph.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self._glyph.setToolTip("Migration in progress")
        self._glyph.setStyleSheet(f"color: {_theme.COLOR_DIM}; font-size: {_theme.FONT_MD};")
        top.addWidget(self._glyph)

        self._label = QLabel(label)
        self._label.setStyleSheet(f"color: {_theme.COLOR_TEXT}; font-size: {_theme.FONT_SM};")
        self._label.setWordWrap(True)            # wrap rather than clip long labels
        self._label.setToolTip(label)
        self._label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        top.addWidget(self._label, 1)
        outer.addLayout(top)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(20, 0, 0, 0)   # indent under the label, past the glyph column
        bottom.setSpacing(6)

        self._bar = QProgressBar()
        self._bar.setMinimum(0)
        self._bar.setMaximum(0)  # indeterminate until first progress_cb fires
        self._bar.setValue(0)
        self._bar.setFixedHeight(8)
        self._bar.setTextVisible(False)
        self._bar.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._bar.setToolTip("Migration progress")
        self._bar.setStyleSheet(
            f"QProgressBar {{ border: 1px solid {_theme.COLOR_BORDER}; border-radius: 3px;"
            f" background: {_theme.COLOR_LINE}; }}"
            f"QProgressBar::chunk {{ background: {_theme.COLOR_ACCENT_BLUE}; border-radius: 2px; }}"
        )
        bottom.addWidget(self._bar, 1)

        self._pct = QLabel("")
        self._pct.setFixedWidth(36)
        self._pct.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._pct.setStyleSheet(f"color: {_theme.COLOR_MUTED}; font-size: {_theme.FONT_XS};")
        bottom.addWidget(self._pct)
        outer.addLayout(bottom)

    # ── Slots called by MigrationProgressWidget ─────────────────────────────

    def on_progress(self, done: int, total: int) -> None:
        """Update the progress bar and percentage label."""
        if self._done:
            return
        if total > 0:
            self._bar.setMaximum(total)
            self._bar.setValue(done)
            pct = int(done / total * 100)
            self._pct.setText(f"{pct}%")
        else:
            # Indeterminate
            self._bar.setMaximum(0)
            self._bar.setValue(0)
            self._pct.setText("")

    def on_finished(self) -> None:
        """Flip to the done glyph and fill the bar to 100%."""
        self._done = True
        self._glyph.setText(_icons.migration_done_icon)
        self._glyph.setStyleSheet(f"color: {_theme.COLOR_OK}; font-size: {_theme.FONT_MD};")
        self._glyph.setToolTip("Migration complete")
        if self._bar.maximum() > 0:
            self._bar.setValue(self._bar.maximum())
            self._pct.setText("100%")
        else:
            # Was indeterminate — switch to determinate full
            self._bar.setMaximum(100)
            self._bar.setValue(100)
            self._pct.setText("100%")


class MigrationProgressWidget(QFrame):
    """Corner-overlay panel showing migration task progress.

    Matches the bottom-right positioning of ``NotificationWidget``:
    placed as a sibling overlay on the ``centralWidget()`` and repositioned
    via ``reposition()`` whenever content changes or the parent resizes.

    Connect ``MigrationManager``'s public signals to the ``on_*`` slots.

    Slots
    -----
    on_task_started(task_id, label)
    on_task_progress(task_id, done, total)
    on_task_finished(task_id)
    on_all_finished()
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._rows: dict[str, _TaskRow] = {}
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(_HIDE_DELAY_MS)
        self._hide_timer.timeout.connect(self.hide)

        self._setup_ui()
        self.hide()  # invisible until the first task_started

    def _setup_ui(self) -> None:
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self.setMinimumWidth(340)
        self.setMaximumWidth(420)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.setStyleSheet(
            f"MigrationProgressWidget {{"
            f" background-color: {_theme.COLOR_NOTIFY_INFO_BG};"
            f" border: 2px solid {_theme.COLOR_ACCENT_BLUE};"
            f" border-radius: 6px;"
            f"}}"
            f"QLabel {{ color: {_theme.COLOR_TEXT_HI}; }}"
        )

        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(10, 8, 10, 8)
        self._outer.setSpacing(4)

        # Header row
        header = QLabel(f"{_icons.notification_progress_icon}  Migration in progress")
        _font = header.font()
        _font.setBold(True)
        header.setFont(_font)
        header.setStyleSheet(
            f"color: {_theme.COLOR_TEXT_HI}; font-size: {_theme.FONT_MD};"
        )
        header.setToolTip("Background data migration running — please do not quit")
        self._outer.addWidget(header)

        # Task rows are added dynamically in on_task_started
        self._rows_container = QVBoxLayout()
        self._rows_container.setSpacing(6)
        self._outer.addLayout(self._rows_container)

    # ── Public slots (connect MigrationManager signals here) ────────────────

    def on_task_started(self, task_id: str, label: str) -> None:
        """Add a new task row and show the panel."""
        logger.debug("MigrationProgressWidget: task_started task_id={}", task_id)
        if task_id in self._rows:
            return  # idempotent
        row = _TaskRow(task_id, label, self)
        self._rows[task_id] = row
        self._rows_container.addWidget(row)
        self._hide_timer.stop()
        self.show()
        self.adjustSize()
        self.reposition()

    def on_task_progress(self, task_id: str, done: int, total: int) -> None:
        """Update the progress bar for *task_id*."""
        row = self._rows.get(task_id)
        if row is not None:
            row.on_progress(done, total)

    def on_task_finished(self, task_id: str) -> None:
        """Flip the glyph to done for *task_id*."""
        logger.debug("MigrationProgressWidget: task_finished task_id={}", task_id)
        row = self._rows.get(task_id)
        if row is not None:
            row.on_finished()

    def on_all_finished(self) -> None:
        """Schedule the panel to auto-hide after a short delay."""
        logger.debug("MigrationProgressWidget: all_finished — scheduling hide")
        self._hide_timer.start()

    # ── Positioning (mirrors NotificationWidget.reposition) ─────────────────

    def reposition(self) -> None:
        """Reposition in the bottom-right corner of the parent widget."""
        if self.parent():
            parent_rect = self.parent().rect()
            self.adjustSize()
            # Sit just above the bottom edge, same 20 px margin as notifications.
            # If a NotificationWidget is also showing, they may overlap — that is
            # acceptable given migrations are infrequent.  A future enhancement
            # could stack them, but that requires coordination between the two widgets.
            x = parent_rect.width() - self.width() - 20
            y = parent_rect.height() - self.height() - 20
            self.move(x, max(0, y))
            self.raise_()
