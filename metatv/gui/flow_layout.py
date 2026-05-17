"""Responsive flow layout — wraps items like CSS flex-wrap.

Items define their own minimumSizeHint; the layout packs them left-to-right
and wraps to the next row when there is no more horizontal space.  Column
count adjusts automatically on every resize — no manual reflow needed.

Usage:
    layout = FlowLayout(parent_widget, spacing=8)
    layout.addWidget(card1)
    layout.addWidget(card2)
    # Cards reflow automatically when the parent is resized.
"""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, QSize, Qt
from PyQt6.QtWidgets import QLayout, QSizePolicy, QWidgetItem


class FlowLayout(QLayout):
    """A layout that flows items left-to-right, wrapping to the next row."""

    def __init__(self, parent=None, spacing: int = 8) -> None:
        super().__init__(parent)
        self._items: list[QWidgetItem] = []
        self.setSpacing(spacing)

    # ── QLayout interface ──────────────────────────────────────────────

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), dry_run=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, dry_run=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    # ── Layout engine ──────────────────────────────────────────────────

    def _do_layout(self, rect: QRect, *, dry_run: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(
            margins.left(), margins.top(), -margins.right(), -margins.bottom()
        )
        x = effective.x()
        y = effective.y()
        row_height = 0
        spacing = self.spacing()

        for item in self._items:
            hint = item.sizeHint()
            w, h = hint.width(), hint.height()

            # Wrap to next row if item doesn't fit
            if x + w > effective.right() and x > effective.x():
                x = effective.x()
                y += row_height + spacing
                row_height = 0

            if not dry_run:
                item.setGeometry(QRect(QPoint(x, y), hint))

            x += w + spacing
            row_height = max(row_height, h)

        return y + row_height - rect.y() + margins.bottom()
