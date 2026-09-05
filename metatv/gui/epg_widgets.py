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
    QTreeWidget,
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
#: defined — this is that definition). +8/+9, not +6/+7: On Now uses +1 for
#: its category/group key and Browse uses +6 for its day-separator marker —
#: on +6 every Browse programme row read as a separator (CI on #741).
_PROG_START_ROLE   = Qt.ItemDataRole.UserRole + 8
_PROG_STOP_ROLE    = Qt.ItemDataRole.UserRole + 9


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
# "record_programme"/"record_window" handlers — shared by On Now + Browse
# ---------------------------------------------------------------------------

def add_record_programme_handler(handlers: dict, ctx, host, cid: str) -> None:
    """Register the EPG surfaces' record handlers — the identical block On Now
    and Browse both built.

    "record_window" (Option B) needs no programme identity at all, so it is
    registered unconditionally; "record_programme" (REC-3) only when *ctx*
    actually carries a programme window — a Browse row past its own end has
    neither, so nothing is added there.

    Direct calls, not ``hasattr``: both ``record_channel_window`` and
    ``schedule_recording_from_programme`` are real ``MainWindow`` methods
    (``main_window_downloads.py``); a skeleton test host gets them from the
    shared conftest factory (CLAUDE.md: never a ``hasattr`` guard in
    production to satisfy a skeleton — wire the shared factory instead).

    Args:
        handlers: The surface's handler dict, mutated in place.
        ctx: The built ``ChannelMenuContext`` — read for
            ``programme_start``/``programme_end``/``programme_title``.
        host: The resolved menu host (``self._host()``), carrying
            ``record_channel_window``/``schedule_recording_from_programme``.
        cid: The single selected channel id.
    """
    handlers["record_window"] = lambda c=cid: host.record_channel_window(c)

    if ctx.programme_start is None or ctx.programme_end is None:
        return

    def _record_h(c=cid, s=ctx.programme_start, e=ctx.programme_end,
                  t=ctx.programme_title):
        host.schedule_recording_from_programme(c, s, e, t)

    handlers["record_programme"] = _record_h


# ---------------------------------------------------------------------------
# Rec column — shared by On Now + Browse (Catch, Keep, Record, Feature 3)
# ---------------------------------------------------------------------------

def rec_cell_click(host, item: QTreeWidgetItem, title_column: int) -> None:
    """Handle a click on the shared Rec column: schedule from THIS row's window.

    On Now and Browse differ only in which column carries the title (Show is
    column 3 on On Now, column 4 on Browse), so the click behaviour otherwise
    exists once rather than twice. A no-op on any row missing a channel id or
    a programme window — a group header, a Q3 day separator — so callers need
    not guard those cases themselves.

    Args:
        host: The resolved menu host (``self._host()``), carrying
            ``schedule_recording_from_programme``.
        item: The clicked row.
        title_column: Which column holds the programme title.
    """
    cid = item.data(0, Qt.ItemDataRole.UserRole)
    start = item.data(0, _PROG_START_ROLE)
    stop = item.data(0, _PROG_STOP_ROLE)
    if not cid or start is None or stop is None:
        return
    title = item.text(title_column).split(" ᴸᶦᵛᵉ")[0].split(" ᴺᵉʷ")[0].strip()
    host.schedule_recording_from_programme(cid, start, stop, title)


def apply_rec_cell(item: QTreeWidgetItem, column: int, channel_id, start, stop,
                    progress_rows, now) -> None:
    """Set column ``column``'s glyph/tooltip/colour for a programme row's Rec control.

    One call from each tree's render loop (initial populate) AND from
    :func:`refresh_rec_column` (the poll-tick re-walk) — the recording/
    scheduled/plain decision is made ONCE, here, rather than reimplemented per
    caller. ``recording_indicators.indicator_for`` does the actual overlap
    test against ``progress_rows``.
    """
    from metatv.gui.recording_indicators import glyph_for, indicator_for

    state, tooltip = indicator_for(channel_id, start, stop, progress_rows, now)
    item.setText(column, glyph_for(state))
    item.setToolTip(column, tooltip)
    item.setTextAlignment(column, Qt.AlignmentFlag.AlignCenter)
    item.setForeground(
        column,
        QColor(_theme.COLOR_ERR if state == "recording" else _theme.COLOR_TEXT),
    )


def refresh_rec_column(tree: QTreeWidget, column: int, progress_rows, now, *,
                        grouped: bool = False, separator_role: "int | None" = None) -> None:
    """Re-walk ``tree``'s programme rows, refreshing the Rec column in place.

    Shared by On Now (``grouped=True`` — programme rows sit one level under a
    prefix-group header) and Browse (flat top-level rows, some of which are Q3
    day separators skipped via ``separator_role``), called each poll tick from
    ``EpgView.refresh_recording_indicators`` — cheap, since it only touches
    rows already on screen and ``progress_rows`` is one shared read.
    """
    def _apply(row_item: QTreeWidgetItem) -> None:
        if separator_role is not None and row_item.data(0, separator_role):
            return
        apply_rec_cell(
            row_item, column, row_item.data(0, Qt.ItemDataRole.UserRole),
            row_item.data(0, _PROG_START_ROLE), row_item.data(0, _PROG_STOP_ROLE),
            progress_rows, now,
        )

    for i in range(tree.topLevelItemCount()):
        top = tree.topLevelItem(i)
        if grouped:
            for c in range(top.childCount()):
                _apply(top.child(c))
        else:
            _apply(top)


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
