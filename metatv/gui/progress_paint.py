"""The one programme-progress bar.

Three surfaces show "how far through is this programme": the EPG tree's
Remaining column (a delegate), the EPG agenda strip (a widget), and now a Watch
Alerts row (a widget). Before this module there were two painters that did not
match each other — a ``QColor(55, 55, 55)`` track with a yellow→orange HSV ramp
in one, a ``QColor(60, 60, 60)`` track with a flat amber in the other — and four
hardcoded colour literals between them, invisible to the theme layer and frozen
across every palette.

A delegate paints into a ``QPainter`` it is handed; a widget paints into its
own. Both hold a painter and a rect, which is the whole interface here, so one
function serves both and neither has to become the other.

The colours are tokens, so the bar follows the palette like everything else, and
the fill says something: accent while the programme is running, warn once it is
nearly over. That is a real state change (you have minutes, not half an hour)
paired with the shrinking bar, never colour alone.
"""

from __future__ import annotations

from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import QSizePolicy, QWidget

from metatv.gui import theme as _theme
from metatv.gui.token_color import to_qcolor

#: Past this share of a programme, the fill takes the warning colour. The bar's
#: LENGTH already says how much is left; the colour change is what makes "nearly
#: over" readable at a glance in a list you are scanning rather than reading.
NEARLY_OVER_PCT = 80

#: Corner radius, and the shortest fill that still reads as a bar rather than as
#: a dot — a programme one minute in should still show something.
_RADIUS = 2
_MIN_FILL_PX = 4


def paint_progress(painter: QPainter, rect: QRect, pct: float) -> None:
    """Paint a progress bar for ``pct`` (0-100) into ``rect``.

    Args:
        painter: An active painter. Saved and restored here, so the caller's
            pen/brush survive.
        rect: The bar's full extent, already inset by the caller — a delegate
            insets to leave cell padding, a widget usually passes its own rect.
        pct: How far through, 0-100. Clamped, so a programme that has run over
            renders full rather than overflowing its track.
    """
    pct = max(0.0, min(100.0, float(pct)))
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)

    painter.setBrush(to_qcolor(_theme.COLOR_LINE))
    painter.drawRoundedRect(rect, _RADIUS, _RADIUS)

    fill_w = max(_MIN_FILL_PX, int(rect.width() * pct / 100))
    fill = _theme.COLOR_WARN if pct >= NEARLY_OVER_PCT else _theme.COLOR_ACCENT
    painter.setBrush(to_qcolor(fill))
    painter.drawRoundedRect(
        QRect(rect.x(), rect.y(), fill_w, rect.height()), _RADIUS, _RADIUS
    )
    painter.restore()


def elapsed_pct(start, stop, now) -> float:
    """How far through a programme ``now`` is, 0-100.

    Args:
        start: Programme start (UTC-naive).
        stop: Programme end (UTC-naive).
        now: The instant to measure at (UTC-naive).

    Returns:
        0-100. A zero-or-negative duration returns 0 rather than dividing by it —
        provider EPG data does contain such rows, and a crash in a paint path
        takes the whole list down.
    """
    if start is None or stop is None:
        return 0.0
    duration = (stop - start).total_seconds()
    if duration <= 0:
        return 0.0
    return max(0.0, min(100.0, (now - start).total_seconds() / duration * 100))


class ProgressBar(QWidget):
    """The widget form of :func:`paint_progress`, in both geometries that exist.

    There were two of these, privately, and they were NOT the same widget —
    which is why this takes parameters rather than picking a winner:

    * Watch Alerts wanted a **fixed 44x8** chip pinned in a row's right-hand
      rail, plus ``set_pct`` with a repaint threshold (a list of live rows
      ticks every 30s and most bars have not visibly moved).
    * The EPG agenda strip wanted a **height-4 bar that expands** to its
      column.

    Calling that a duplicate and deleting one would have moved a bar. Both
    geometries survive; what unifies is the painting, the repaint threshold and
    the painter lifetime.

    Owner's reasoning for the bar at all, which applies to every caller: *"30
    minutes left on a 30 minute show is different than 30 minutes left on a 3
    hour show."* Words cannot say that; a proportion can. Exact figures go in
    the tooltip, where they cost no width.

    Args:
        pct: Initial fill, 0-100. Clamped.
        width: Fixed width in px, or ``None`` for a bar that expands to its
            layout column.
        height: Fixed height in px.
        parent: Qt parent.
    """

    #: Below this movement a repaint is not worth the frame. A 30s tick across
    #: a list of live rows redraws almost nothing this way.
    _REPAINT_THRESHOLD_PCT = 0.5

    def __init__(self, pct: float = 0.0, *, width: "int | None" = None,
                 height: int = 8, parent: "QWidget | None" = None) -> None:
        super().__init__(parent)
        self._pct = max(0.0, min(100.0, float(pct)))
        self._w = width
        self._h = height
        if width is None:
            self.setFixedHeight(height)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        else:
            self.setFixedSize(width, height)

    def set_pct(self, pct: float, tooltip: str = "") -> None:
        """Update the fill, repainting only when it actually moved."""
        pct = max(0.0, min(100.0, float(pct)))
        if tooltip:
            self.setToolTip(tooltip)
        if abs(pct - self._pct) < self._REPAINT_THRESHOLD_PCT:
            return
        self._pct = pct
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt override)
        return QSize(self._w if self._w is not None else 0, self._h)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # BOUND and explicitly ended, never passed as a temporary: a QPainter
        # that outlives its paintEvent warns, and one whose lifetime depends on
        # when a temporary is collected is a bug waiting for a different
        # interpreter.
        painter = QPainter(self)
        paint_progress(painter, QRect(0, 0, self.width(), self.height()), self._pct)
        painter.end()
