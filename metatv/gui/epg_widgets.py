"""Shared EPG widget primitives (Band 10 B10-4 file split).

Module-level helpers and dialogs used by multiple EPG tab mixins.
Imports nothing from ``metatv.gui.epg_view`` — consumed by both
``epg_view.py`` (re-exported for backwards compat) and tab-specific
mixins (e.g. ``epg_browse_mixin``).

Exports
-------
_SORT_ROLE
_PROGRESS_ROLE
_REMAIN_ROLE
_ProgressBarDelegate
_EpgTreeItem
_progress_bar
_DismissedDialog
_AssignCategoryDialog
_parse_iso
"""

from __future__ import annotations

from datetime import datetime, timezone

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStyledItemDelegate,
    QTreeWidgetItem,
    QVBoxLayout,
)

from metatv.core.epg_utils import now_utc as _now_utc

# ---------------------------------------------------------------------------
# Qt item-data roles shared across all EPG tree widgets
# ---------------------------------------------------------------------------

_SORT_ROLE     = Qt.ItemDataRole.UserRole + 2  # numeric sort key (seconds)
_PROGRESS_ROLE = Qt.ItemDataRole.UserRole + 3  # 0–100 progress pct for progress bar
_REMAIN_ROLE   = Qt.ItemDataRole.UserRole + 4  # "10m left" tooltip string


# ---------------------------------------------------------------------------
# Delegate — progress bar in the Remaining column
# ---------------------------------------------------------------------------

class _ProgressBarDelegate(QStyledItemDelegate):
    """Paints a compact horizontal progress bar in the Remaining column."""

    def paint(self, painter, option, index) -> None:  # noqa: N802
        from PyQt6.QtGui import QColor
        pct = index.data(_PROGRESS_ROLE)
        if pct is None:
            super().paint(painter, option, index)
            return
        painter.save()
        r = option.rect.adjusted(4, 6, -4, -6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(55, 55, 55))
        painter.drawRoundedRect(r, 2, 2)
        fill_w = max(4, int(r.width() * pct / 100))
        # hue: 55 (yellow) at start → 30 (orange) near end
        hue = int(55 - (pct / 100) * 25)
        painter.setBrush(QColor.fromHsv(hue, 200, 210, 200))
        from PyQt6.QtCore import QRect
        fill_r = QRect(r.x(), r.y(), fill_w, r.height())
        painter.drawRoundedRect(fill_r, 2, 2)
        painter.restore()

    def sizeHint(self, option, index):  # noqa: N802
        from PyQt6.QtCore import QSize
        return QSize(64, super().sizeHint(option, index).height())


# ---------------------------------------------------------------------------
# Tree item — numeric sort via _SORT_ROLE
# ---------------------------------------------------------------------------

class _EpgTreeItem(QTreeWidgetItem):
    """QTreeWidgetItem that sorts any column with a _SORT_ROLE numeric value."""

    def __lt__(self, other: QTreeWidgetItem) -> bool:
        col = self.treeWidget().sortColumn() if self.treeWidget() else 0
        a = self.data(col, _SORT_ROLE)
        b = other.data(col, _SORT_ROLE)
        if a is not None and b is not None:
            return float(a) < float(b)
        # Category column: empty strings sort after non-empty in both directions
        if col == 0:
            a_text = self.text(0)
            b_text = other.text(0)
            if bool(a_text) != bool(b_text):
                return bool(a_text) > bool(b_text)  # non-empty < empty → non-empty first
        return super().__lt__(other)


# ---------------------------------------------------------------------------
# ASCII progress bar helper
# ---------------------------------------------------------------------------

def _progress_bar(start: datetime, stop: datetime, width: int = 20) -> str:
    """ASCII progress bar showing how far through the programme we are."""
    total = max(1, (stop - start).total_seconds())
    elapsed = max(0, (_now_utc() - start).total_seconds())
    ratio = min(1.0, elapsed / total)
    filled = int(ratio * width)
    return "█" * filled + "░" * (width - filled)


# ---------------------------------------------------------------------------
# Manage Dismissed dialog
# ---------------------------------------------------------------------------

class _DismissedDialog(QDialog):
    """Lists dismissed channels and allows un-dismissing them."""

    def __init__(self, config, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Manage Dismissed Channels")
        self.resize(400, 300)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Dismissed recommendations (click to un-dismiss):"))

        self.list = QListWidget()
        layout.addWidget(self.list)

        now = _now_utc()
        for cid, ts_str in list(self.config.epg_dismissed_channels.items()):
            until = _parse_iso(ts_str)
            if until > now:
                days = max(0, (until - now).days)
                item = QListWidgetItem(f"{cid} — {days}d remaining")
                item.setData(Qt.ItemDataRole.UserRole, cid)
                self.list.addItem(item)

        if self.list.count() == 0:
            self.list.addItem("No dismissed channels.")

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        undismiss_btn = QPushButton("Un-dismiss selected")
        undismiss_btn.clicked.connect(self._undismiss)
        btn_box.addButton(undismiss_btn, QDialogButtonBox.ButtonRole.ActionRole)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _undismiss(self) -> None:
        item = self.list.currentItem()
        if not item:
            return
        cid = item.data(Qt.ItemDataRole.UserRole)
        if cid and cid in self.config.epg_dismissed_channels:
            del self.config.epg_dismissed_channels[cid]
            self.config.save()
            row = self.list.row(item)
            self.list.takeItem(row)


# ---------------------------------------------------------------------------
# Assign Category dialog
# ---------------------------------------------------------------------------

class _AssignCategoryDialog(QDialog):
    """Lets the user pick or type a category code to assign to selected channels."""

    def __init__(self, known: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Assign Category")
        self.setModal(True)
        self.setMinimumWidth(300)
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.setContentsMargins(12, 12, 12, 12)

        lay.addWidget(QLabel("Category code (e.g. BEIN, US, UK, NHL):"))

        self._edit = QLineEdit()
        self._edit.setClearButtonEnabled(True)
        self._edit.setPlaceholderText("Type a code or pick from list below…")
        lay.addWidget(self._edit)

        from PyQt6.QtWidgets import QComboBox
        combo = QComboBox()
        combo.addItem("— pick existing —")
        combo.addItems(known)
        combo.currentIndexChanged.connect(
            lambda i: self._edit.setText(combo.currentText()) if i > 0 else None
        )
        lay.addWidget(combo)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def category_code(self) -> str:
        return self._edit.text().strip().upper()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_iso(ts_str: str) -> datetime:
    """Parse ISO timestamp string to naive datetime (UTC)."""
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except (ValueError, TypeError):
        return datetime.min
