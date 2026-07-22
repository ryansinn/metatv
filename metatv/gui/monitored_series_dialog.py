"""Episode Alerts management dialog — see and stop new-episode alerts.

Adding an alert happens through the native flow (right-click → "Alert me to new
episodes", or the details-pane Alert button).  This dialog is the see-all +
remove surface, opened from the "New Episodes" sidebar section.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)
from loguru import logger

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme


class MonitoredSeriesDialog(QDialog):
    """List every series you're alerting on with a Stop button. Config-only (no DB)."""

    # Emitted after a series is removed so the host can refresh dependent views.
    changed = pyqtSignal()

    def __init__(self, config, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("Episode Alerts")
        self.setMinimumSize(460, 420)
        self._setup_ui()
        self._load()

    # ── UI construction ──────────────────────────────────────────────────────
    def _setup_ui(self) -> None:
        vl = QVBoxLayout(self)
        vl.setSpacing(8)

        hdr_row = QHBoxLayout()
        hdr = QLabel(f"{_icons.new_episodes_icon}  Episode Alerts")
        hdr.setStyleSheet(f"font-size: {_theme.FONT_XL}; font-weight: bold;")
        hdr_row.addWidget(hdr)
        hdr_row.addStretch()
        self._count_lbl = QLabel("")
        self._count_lbl.setStyleSheet(
            f"color: {_theme.COLOR_MUTED_2}; font-size: {_theme.FONT_MD};"
        )
        hdr_row.addWidget(self._count_lbl)
        vl.addLayout(hdr_row)

        hint = QLabel(
            "New episodes are detected when you refresh a source or on startup."
        )
        hint.setStyleSheet(f"color: {_theme.COLOR_MUTED}; font-size: {_theme.FONT_SM};")
        vl.addWidget(hint)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {_theme.COLOR_LINE};")
        vl.addWidget(sep)

        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_content = QWidget()
        self._scroll_vl = QVBoxLayout(self._scroll_content)
        self._scroll_vl.setSpacing(4)
        self._scroll_area.setWidget(self._scroll_content)
        vl.addWidget(self._scroll_area, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        vl.addWidget(buttons)

    # ── Data loading ─────────────────────────────────────────────────────────
    def _load(self) -> None:
        while self._scroll_vl.count():
            item = self._scroll_vl.takeAt(0)
            if w := item.widget():
                w.deleteLater()

        entries = self._config.get_monitored_series()
        self._count_lbl.setText(f"{len(entries)} active" if entries else "")

        if not entries:
            empty = QLabel(
                "No episode alerts yet.\n\n"
                'Right-click a series → "Alert me to new episodes" to start.'
            )
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(
                f"color: {_theme.COLOR_FAINT}; font-size: {_theme.FONT_LG}; padding: 30px;"
            )
            self._scroll_vl.addWidget(empty)
            self._scroll_vl.addStretch()
            return

        # New-episode series first, then alphabetical.
        for entry in sorted(
            entries,
            key=lambda e: (-(e.get("unseen_new") or 0), (e.get("title") or "").lower()),
        ):
            self._scroll_vl.addWidget(self._make_row(entry))
        self._scroll_vl.addStretch()

    def _make_row(self, entry: dict) -> QWidget:
        cid = entry.get("series_channel_id", "")
        title = entry.get("title") or "Unknown series"
        unseen = entry.get("unseen_new") or 0

        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(4, 2, 4, 2)
        hl.setSpacing(6)

        name_lbl = QLabel(title)
        name_lbl.setStyleSheet(f"font-size: {_theme.FONT_MD}; color: {_theme.COLOR_TEXT};")
        hl.addWidget(name_lbl, 1)

        if unseen > 0:
            ep_word = "ep" if unseen == 1 else "eps"
            badge = QLabel(f"+{unseen} {ep_word}")
            badge.setStyleSheet(
                f"color: {_theme.COLOR_ACCENT_GREEN}; font-size: {_theme.FONT_SM};"
                " font-weight: bold;"
            )
            badge.setToolTip(f"{unseen} new {ep_word} since you last looked")
            hl.addWidget(badge)

        stop_btn = QPushButton(f"{_icons.close_icon} Stop alerts")
        stop_btn.setFlat(True)
        stop_btn.setStyleSheet(
            f"QPushButton {{ font-size: {_theme.FONT_SM}; color: {_theme.COLOR_ERR_2};"
            f" padding: 1px 6px; border: none; }}"
            f"QPushButton:hover {{ color: {_theme.COLOR_RED_BRIGHT}; }}"
        )
        stop_btn.setToolTip(f"Stop new-episode alerts for {title}")
        stop_btn.clicked.connect(lambda _checked=False, c=cid: self._stop(c))
        hl.addWidget(stop_btn)

        return row

    # ── Actions ──────────────────────────────────────────────────────────────
    def _stop(self, channel_id: str) -> None:
        self._config.remove_monitored_series(channel_id)
        logger.info(f"Stopped new-episode alerts for series {channel_id}")
        self._load()
        self.changed.emit()
