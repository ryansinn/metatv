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

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QPainter

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
