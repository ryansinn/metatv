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
_CONTENT_TYPE_ROLE
_PROG_START_ROLE
_PROG_STOP_ROLE
_ProgressBarDelegate
_EpgTreeItem
_progress_bar
_DismissedDialog
_AssignCategoryDialog
_parse_iso
apply_watchlist_highlight
add_record_programme_handler
"""

from __future__ import annotations

from datetime import datetime, timezone

from PyQt6.QtCore import Qt

from metatv.gui.progress_paint import paint_progress
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
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
from metatv.gui import theme as _theme
from metatv.gui import deferred_config_save as _cfgsave

# ---------------------------------------------------------------------------
# Qt item-data roles shared across all EPG tree widgets
# ---------------------------------------------------------------------------

_SORT_ROLE         = Qt.ItemDataRole.UserRole + 2  # numeric sort key (seconds)
_PROGRESS_ROLE     = Qt.ItemDataRole.UserRole + 3  # 0–100 progress pct for progress bar
_REMAIN_ROLE       = Qt.ItemDataRole.UserRole + 4  # "10m left" tooltip string
_CONTENT_TYPE_ROLE = Qt.ItemDataRole.UserRole + 5  # On Now: classify_channel_content_type() result
#: REC-3: a programme row's raw UTC-naive start/stop — read by the channel-menu
#: handler that schedules a recording of THIS row, not "now". Shared across
#: On Now, Browse and Watch Alerts so "record_programme" behaves identically
#: on all three (CLAUDE.md: import a private name only from where it is
#: defined — this is that definition).
_PROG_START_ROLE   = Qt.ItemDataRole.UserRole + 6
_PROG_STOP_ROLE    = Qt.ItemDataRole.UserRole + 7


# ---------------------------------------------------------------------------
# Delegate — progress bar in the Remaining column
# ---------------------------------------------------------------------------

class _ProgressBarDelegate(QStyledItemDelegate):
    """Paints a compact horizontal progress bar in the Remaining column."""

    def paint(self, painter, option, index) -> None:  # noqa: N802
        pct = index.data(_PROGRESS_ROLE)
        if pct is None:
            super().paint(painter, option, index)
            return
        # Was four hardcoded colour literals and an HSV ramp, which the theme
        # layer could not see and which did not match the agenda strip's bar.
        paint_progress(painter, option.rect.adjusted(4, 6, -4, -6), pct)

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
# Watchlist-match highlight — shared by On Now + Browse (Q8, wave3/browse-makeover)
# ---------------------------------------------------------------------------

def apply_watchlist_highlight(item: QTreeWidgetItem, columns, bold_col: int) -> None:
    """Apply the shared watchlist-match row treatment: accent foreground across
    ``columns`` plus a bold font on ``bold_col`` (the Show/title column).

    Single chokepoint for the On Now + Browse tree "this row matches your
    watchlist" highlight so future accent tweaks land in one place instead of
    two copy-pasted inline loops. No visual change from the pre-existing
    per-mixin versions.

    Args:
        item: The tree row to highlight.
        columns: Iterable of column indexes to tint (usually ``range(N)``).
        bold_col: The column to additionally bold (the Show/title column).
    """
    for col in columns:
        item.setForeground(col, QColor(_theme.COLOR_ACCENT_HOVER))
    font = item.font(bold_col)
    font.setBold(True)
    item.setFont(bold_col, font)


# ---------------------------------------------------------------------------
# "record_programme" handler — shared by On Now + Browse (REC-3)
# ---------------------------------------------------------------------------

def add_record_programme_handler(handlers: dict, ctx, host, cid: str) -> None:
    """Register the "record_programme" channel-menu handler when *ctx* carries
    a programme window — the identical block On Now and Browse both built.

    Direct call, not ``hasattr``: ``schedule_recording_from_programme`` is a
    real ``MainWindow`` method (``main_window_downloads.py``); a skeleton test
    host gets it from the shared conftest factory (CLAUDE.md: never a
    ``hasattr`` guard in production to satisfy a skeleton — wire the shared
    factory instead).

    Args:
        handlers: The surface's handler dict, mutated in place.
        ctx: The built ``ChannelMenuContext`` — read for
            ``programme_start``/``programme_end``/``programme_title``.
        host: The resolved menu host (``self._host()``), carrying
            ``schedule_recording_from_programme``.
        cid: The single selected channel id.
    """
    if ctx.programme_start is None or ctx.programme_end is None:
        return

    def _record_h(c=cid, s=ctx.programme_start, e=ctx.programme_end,
                  t=ctx.programme_title):
        host.schedule_recording_from_programme(c, s, e, t)

    handlers["record_programme"] = _record_h


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
            _cfgsave.save_soon(self)
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
