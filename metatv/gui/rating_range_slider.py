"""RatingRangeSlider — a horizontal dual-handle range slider (0–10 rating scale).

The recipe builder's first *non-tag* ingredient: it limits results by the rating
shown on Discover / Now-Plating cards (``ChannelDB.raw_data["rating"]``).  Two
handles pick a ``(min, max)`` band on a 0–10 scale:

- Full-left minimum (0) imposes **no floor** — unrated content is INCLUDED.
- Any minimum > 0 excludes unrated content (it can't satisfy the floor).
- The default is the full span ``(0, 10)`` → no filter at all.

Interaction (owner-approved):

- **Click the open bar** sets the *floor* (min handle) to that point — the
  dominant one-click gesture is "at least 7".  (Pure geometric "nearest handle"
  can't deliver "at least 7" from the full-span default, since 7 sits closer to
  the max handle at 10 — so the open-bar click resolves to the floor, which is
  what "the dominant gesture is 'at least 7' in one click" means.)
- **Click on/near a handle** grabs it; **drag** to move either handle for a
  two-sided range.  A click past the current ceiling extends the ceiling.

Values snap to :data:`RatingRangeSlider.STEP` (0.5).  The widget emits
:attr:`rangeChanged` on every change; the host debounces the resulting query.

Theming: the paint path builds ``QColor`` objects from ``theme`` tokens only
(no hex literals).  The pointing-hand affordance is routed through
``cursor_affordance.set_clickable`` per the app-wide cursor rule.
"""

from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QSizePolicy, QWidget

from metatv.core.recipe_state import RATING_SCALE_MAX, RATING_SCALE_MIN
from metatv.gui import theme as _theme
from metatv.gui.cursor_affordance import set_clickable


def format_rating_range(lo: float, hi: float, *, empty: str = "Any") -> str:
    """Render a rating band as a compact human label — the single formatting seam.

    Shared by the pantry readout and the recipe-card "RATING" menu line so both
    read identically.  A ceiling at (or above) 10 means "no ceiling" and renders
    as a ``≥`` floor; a floor at (or below) 0 means "no floor" and renders as a
    ``≤`` ceiling; a two-sided band renders as ``lo – hi``.

    Args:
        lo: Band minimum on the 0–10 scale.
        hi: Band maximum on the 0–10 scale.
        empty: Text to return when the band is the full span (no constraint).

    Returns:
        e.g. ``"Any"``, ``"≥ 7.0"``, ``"≤ 8.0"``, or ``"6.0 – 8.0"``.
    """
    has_floor = lo > RatingRangeSlider.MIN
    has_ceil = hi < RatingRangeSlider.MAX
    if not has_floor and not has_ceil:
        return empty
    if has_floor and not has_ceil:
        return f"≥ {lo:.1f}"          # ≥ 7.0
    if has_ceil and not has_floor:
        return f"≤ {hi:.1f}"          # ≤ 8.0
    return f"{lo:.1f} – {hi:.1f}"     # 6.0 – 8.0


class RatingRangeSlider(QWidget):
    """A dual-handle range slider over the 0–10 rating scale.

    Emits :attr:`rangeChanged(min, max)` whenever either handle moves.  Use
    :meth:`set_values` to restore state programmatically (e.g. loading a saved
    recipe) without emitting.

    Attributes:
        MIN / MAX: The fixed rating scale endpoints (0 / 10).
        STEP:      Snap increment for handle values (0.5).
    """

    rangeChanged = pyqtSignal(float, float)   # (min, max)

    MIN: float = RATING_SCALE_MIN
    MAX: float = RATING_SCALE_MAX
    STEP: float = 0.5

    # Geometry (px).  The handle radius doubles as the track's horizontal inset
    # so a handle at either extreme is never clipped.
    _HANDLE_R: int = 7
    _TRACK_H: int = 4

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._lo: float = self.MIN
        self._hi: float = self.MAX
        self._dragging: str | None = None   # "lo" | "hi" | None

        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(120)
        self.setFixedHeight(2 * self._HANDLE_R + 8)
        self.setMouseTracking(False)
        self.setToolTip(
            "Drag the handles to set a rating range (0–10). A minimum of 0 keeps "
            "unrated content; any higher minimum hides it. Click the bar to move "
            "the nearest handle."
        )
        set_clickable(self)

    # ── public API ────────────────────────────────────────────────────────

    def values(self) -> tuple[float, float]:
        """Return the current ``(min, max)`` band."""
        return (self._lo, self._hi)

    def is_full_range(self) -> bool:
        """True when the band imposes no constraint (full 0–10 span)."""
        return self._lo <= self.MIN and self._hi >= self.MAX

    def set_values(self, lo: float, hi: float, *, emit: bool = False) -> None:
        """Set both handles, clamped/snapped and ordered; optionally emit.

        Args:
            lo: Desired minimum (clamped to ``[MIN, hi]``).
            hi: Desired maximum (clamped to ``[lo, MAX]``).
            emit: When True, emit :attr:`rangeChanged` after applying (default
                False — used for silent state restoration).
        """
        lo = self._snap(lo)
        hi = self._snap(hi)
        lo = max(self.MIN, min(lo, self.MAX))
        hi = max(self.MIN, min(hi, self.MAX))
        if lo > hi:
            lo, hi = hi, lo
        self._lo, self._hi = lo, hi
        self.update()
        if emit:
            self.rangeChanged.emit(self._lo, self._hi)

    def reset(self, *, emit: bool = False) -> None:
        """Restore the full-span default (no filter)."""
        self.set_values(self.MIN, self.MAX, emit=emit)

    # ── geometry helpers (exposed for tests) ──────────────────────────────

    def _track_left(self) -> float:
        return float(self._HANDLE_R)

    def _track_right(self) -> float:
        return float(self.width() - self._HANDLE_R)

    def _value_to_x(self, value: float) -> float:
        """Map a rating value to an x pixel on the track."""
        span = self._track_right() - self._track_left()
        frac = (value - self.MIN) / (self.MAX - self.MIN)
        return self._track_left() + frac * span

    def _x_to_value(self, x: float) -> float:
        """Map an x pixel to a snapped rating value (clamped to the scale)."""
        span = self._track_right() - self._track_left()
        if span <= 0:
            return self.MIN
        frac = (x - self._track_left()) / span
        frac = max(0.0, min(1.0, frac))
        return self._snap(self.MIN + frac * (self.MAX - self.MIN))

    def _snap(self, value: float) -> float:
        """Snap *value* to the nearest :data:`STEP` increment."""
        return round(value / self.STEP) * self.STEP

    #: Pixel radius around a handle within which a press grabs that handle.
    _GRAB_PX: int = _HANDLE_R + 3

    def _handle_for_press(self, value: float, x_px: float) -> str:
        """Decide which handle a press grabs.

        - A press within :data:`_GRAB_PX` of a handle grabs that handle (the
          nearer one if both are in range) — this is how you drag the ceiling.
        - A press on the open bar past the current ceiling extends the ceiling.
        - Otherwise the press sets the **floor** (min handle) — the dominant
          one-click "at least X" gesture.

        Args:
            value: Snapped rating value at the press point.
            x_px: Press x in widget pixels (for the handle grab radius).

        Returns:
            ``"lo"`` or ``"hi"`` — the handle to move.
        """
        x_lo = self._value_to_x(self._lo)
        x_hi = self._value_to_x(self._hi)
        near_lo = abs(x_px - x_lo) <= self._GRAB_PX
        near_hi = abs(x_px - x_hi) <= self._GRAB_PX
        if near_lo or near_hi:
            if near_lo and near_hi:
                return "lo" if abs(x_px - x_lo) <= abs(x_px - x_hi) else "hi"
            return "lo" if near_lo else "hi"
        if value >= self._hi:
            return "hi"          # open-bar click past the ceiling → extend it
        return "lo"              # open-bar click → set the floor ("at least X")

    # ── mouse interaction ─────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        x_px = event.position().x()
        value = self._x_to_value(x_px)
        self._dragging = self._handle_for_press(value, x_px)
        self._move_active(value)
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._dragging is None:
            super().mouseMoveEvent(event)
            return
        self._move_active(self._x_to_value(event.position().x()))
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        self._dragging = None
        super().mouseReleaseEvent(event)

    def _move_active(self, value: float) -> None:
        """Move the currently-grabbed handle to *value*, keeping lo ≤ hi."""
        if self._dragging == "lo":
            self._lo = min(value, self._hi)
        elif self._dragging == "hi":
            self._hi = max(value, self._lo)
        else:
            return
        self.update()
        self.rangeChanged.emit(self._lo, self._hi)

    # ── painting ──────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        mid_y = self.height() / 2.0
        left = self._track_left()
        right = self._track_right()

        # Inactive track.
        track_color = QColor(_theme.COLOR_RECIPE_SLIDER_TRACK)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track_color)
        painter.drawRoundedRect(
            QRectF(left, mid_y - self._TRACK_H / 2, right - left, self._TRACK_H),
            self._TRACK_H / 2, self._TRACK_H / 2,
        )

        # Active (selected) band between the two handles.
        x_lo = self._value_to_x(self._lo)
        x_hi = self._value_to_x(self._hi)
        active_color = QColor(_theme.COLOR_RECIPE_SLIDER_ACTIVE)
        painter.setBrush(active_color)
        painter.drawRoundedRect(
            QRectF(x_lo, mid_y - self._TRACK_H / 2, max(0.0, x_hi - x_lo), self._TRACK_H),
            self._TRACK_H / 2, self._TRACK_H / 2,
        )

        # Handles (filled circle with an accent ring).
        handle_fill = QColor(_theme.COLOR_RECIPE_SLIDER_HANDLE)
        for x in (x_lo, x_hi):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(active_color)
            painter.drawEllipse(
                QRectF(x - self._HANDLE_R, mid_y - self._HANDLE_R,
                       2 * self._HANDLE_R, 2 * self._HANDLE_R)
            )
            painter.setBrush(handle_fill)
            inner = self._HANDLE_R - 2
            painter.drawEllipse(
                QRectF(x - inner, mid_y - inner, 2 * inner, 2 * inner)
            )
        painter.end()
