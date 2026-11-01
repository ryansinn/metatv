"""Failures by time of day: a 24-hour strip (Source Analytics Q11).

One column per local hour. A column's HEIGHT is that hour's failure rate and
it takes the warning colour, so the pattern reads by shape as well as colour;
an hour with no plays draws only the baseline track. The exact figures are in
the tooltip, and :func:`struggle_span` puts the worst stretch into words
("Struggles 8 PM–11 PM") for the line above the strip.
"""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import QSizePolicy, QToolTip, QWidget

from metatv.core.time_display import hour_text
from metatv.gui import theme as _theme
from metatv.gui.token_color import to_qcolor

#: An hour needs this many plays before its rate can count as a struggle — one
#: failed play at 4 am is an incident, not a pattern.
MIN_HOUR_PLAYS = 3

#: A struggling hour fails at least this often AND at least twice the source's
#: overall rate, so a source that fails a lot everywhere has no "bad hours".
STRUGGLE_FLOOR = 0.25


def _label(hour: int) -> str:
    return hour_text(datetime(2000, 1, 1, hour % 24))


def struggle_span(by_hour: tuple[tuple[int, int], ...]) -> str | None:
    """The longest run of struggling hours as "8 PM–11 PM", or None.

    A run may wrap past midnight. The end shown is the hour the run stops, so
    a run covering 20:00-22:59 reads "8 PM–11 PM".
    """
    if len(by_hour) != 24:
        return None
    attempts = sum(a for a, _ in by_hour)
    failures = sum(f for _, f in by_hour)
    if not attempts or not failures:
        return None
    bar = max(STRUGGLE_FLOOR, 2 * failures / attempts)
    bad = [a >= MIN_HOUR_PLAYS and f / a >= bar for a, f in by_hour]
    if not any(bad):
        return None
    if all(bad):
        return None  # every hour alike is no time-of-day pattern
    best_start, best_len = 0, 0
    start = next(h for h in range(24) if not bad[h]) + 1  # begin after a good hour
    run_start, run_len = None, 0
    for i in range(24):
        h = (start + i) % 24
        if bad[h]:
            run_start = h if run_start is None else run_start
            run_len += 1
            if run_len > best_len:
                best_start, best_len = run_start, run_len
        else:
            run_start, run_len = None, 0
    return f"{_label(best_start)}–{_label(best_start + best_len)}"


class HourStrip(QWidget):
    """24 columns, one per local hour, each as tall as that hour's failure rate."""

    _TICKS = (0, 6, 12, 18)

    def __init__(self, by_hour: tuple[tuple[int, int], ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._by_hour = by_hour
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(46)
        self.setMouseTracking(True)

    def sizeHint(self) -> QSize:  # noqa: N802 — Qt override
        return QSize(24 * 14, 46)

    def _columns(self) -> tuple[int, QRect]:
        """(column width, the bar area) — the tick labels sit below the area."""
        area = QRect(0, 0, self.width(), self.height() - self.fontMetrics().height() - 2)
        return max(1, area.width() // 24), area

    def column_rect(self, hour: int) -> QRect:
        """Where *hour*'s full-height column is painted (for tooltips and tests)."""
        col, area = self._columns()
        return QRect(hour * col + 1, area.top(), col - 2, area.height())

    def paintEvent(self, event) -> None:  # noqa: N802 — Qt override
        painter = QPainter(self)
        try:
            painter.setPen(Qt.PenStyle.NoPen)
            track = to_qcolor(_theme.COLOR_LINE)
            fill = to_qcolor(_theme.COLOR_WARN)
            for hour, (attempts, failures) in enumerate(self._by_hour):
                cell = self.column_rect(hour)
                painter.setBrush(track)
                painter.drawRect(QRect(cell.left(), cell.bottom() - 1, cell.width(), 2))
                if attempts and failures:
                    h = max(2, round(cell.height() * failures / attempts))
                    painter.setBrush(fill)
                    painter.drawRect(QRect(cell.left(), cell.bottom() - h + 1, cell.width(), h))
            painter.setPen(to_qcolor(_theme.COLOR_MUTED_2))
            col, area = self._columns()
            for hour in self._TICKS:
                painter.drawText(QRect(hour * col, area.bottom() + 2, col * 6, self.fontMetrics().height()),
                                 Qt.AlignmentFlag.AlignLeft, _label(hour))
        finally:
            painter.end()

    def event(self, ev) -> bool:
        if ev.type() == ev.Type.ToolTip:
            col, _area = self._columns()
            hour = min(23, max(0, ev.pos().x() // col))  # a QHelpEvent
            attempts, failures = self._by_hour[hour] if len(self._by_hour) == 24 else (0, 0)
            span = f"{_label(hour)}–{_label(hour + 1)}"
            QToolTip.showText(ev.globalPos(), f"{span}: no plays" if not attempts else
                              f"{span}: {failures:,} of {attempts:,} failed ({failures / attempts:.0%})", self)
            return True
        return super().event(ev)
