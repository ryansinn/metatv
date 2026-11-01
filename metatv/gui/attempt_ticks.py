"""A server address's recent requests as ticks, oldest → newest (Source Analytics Q22).

A share of the last 20 requests hides WHEN they failed: an address that
worked 6,715 times and has answered every request since 20 Oct with a 404
read "5%", the same as one that fails at random. One tick per request says
which it is. A request that worked is a full-height tick in the accent; one
that failed is a short tick in the warning colour — height as well as colour,
so the pattern reads without either alone. The figures are in the tooltip.
"""

from __future__ import annotations

from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import QWidget

from metatv.gui import theme as _theme
from metatv.gui.token_color import to_qcolor

#: Ticks drawn — the stored history keeps about this many requests per address.
SLOTS = 20

#: One tick and the gap after it, in px; the widget is SLOTS × this wide.
_PITCH = 3
_HEIGHT = 12
_FAILED_PX = 3


class AttemptTicks(QWidget):
    """``history`` (True = worked), oldest first; the newest tick sits at the right."""

    def __init__(self, history: tuple[bool, ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._history = tuple(history)[-SLOTS:]
        self.setFixedSize(SLOTS * _PITCH, _HEIGHT)
        worked = sum(self._history)
        self.setToolTip(f"{worked} of the last {len(self._history)} requests worked — newest on the right"
                        if self._history else "No requests recorded yet")

    def sizeHint(self) -> QSize:  # noqa: N802 — Qt override
        return QSize(SLOTS * _PITCH, _HEIGHT)

    def tick_rect(self, index: int) -> QRect:
        """The full-height slot of the *index*-th drawn request (0 = oldest shown)."""
        offset = SLOTS - len(self._history)            # right-aligned: newest at the edge
        return QRect((offset + index) * _PITCH, 0, _PITCH - 1, _HEIGHT)

    def paintEvent(self, event) -> None:  # noqa: N802 — Qt override
        painter = QPainter(self)
        try:
            painter.setPen(Qt.PenStyle.NoPen)
            ok, bad = to_qcolor(_theme.COLOR_ACCENT), to_qcolor(_theme.COLOR_WARN)
            for i, worked in enumerate(self._history):
                slot = self.tick_rect(i)
                if worked:
                    painter.fillRect(slot, ok)
                else:
                    painter.fillRect(QRect(slot.left(), slot.bottom() - _FAILED_PX + 1,
                                           slot.width(), _FAILED_PX), bad)
        finally:
            painter.end()
