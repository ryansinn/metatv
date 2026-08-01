"""Shared sidebar chip-row widget: ``[icon] Title [4K] … [Year] [Lang]``.

One canonical builder for every sidebar content list (Recommended, Watch Queue,
Favorites, History), so the rows read identically: a clean title on the left with
the quality badge hugging its text, and a right-aligned year + audio-language
cluster.  Extracted from ``RecommendedSection._build_rec_row`` (PR #344) so the
Queue / Favorites / History sections share the exact same layout rather than each
hand-rolling a parallel plain-text row.

``MiddleElideLabel`` is the anti-clip title label the rows use; ``build_chip_row``
assembles the mouse-transparent row so a ``QListWidget`` item can host it via
``setItemWidget``.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QLabel, QPushButton, QSizePolicy, QWidget, QHBoxLayout,
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor, QPainter

from metatv.gui import theme as _theme
from metatv.gui import icons as _icons


class MiddleElideLabel(QLabel):
    """Single-line title label that middle-elides ('Long ti…tle') only when genuinely
    too long for its width.

    Sizes to content: ``sizeHint`` = full-text advance + a small buffer, so — laid out
    with a Preferred policy and no stretch — a title that fits is given enough width and
    is NEVER clipped. The buffer absorbs the sub-pixel layout rounding that previously
    chopped even short titles ("1983" → "1…3"). Zero contents margins + eliding against
    the label's FULL ``width()`` in ``paintEvent`` (drawing in ``rect()``, not a
    margin-shrunk ``contentsRect()``) keeps the elide threshold identical to the draw
    area, so a title exactly as wide as its box still renders in full. Only when the row
    is too narrow does the label shrink toward ``minimumSizeHint`` (width of "…") and the
    title middle-elide. Keeps the full text as the tooltip and as ``text()``; the pen
    colour comes from the ``COLOR_TEXT`` token (never a literal).
    """

    # Slack added to the preferred width so a title that fits is never clipped by
    # sub-pixel layout rounding (guards the "1983" → "1…3" regression).
    _HINT_BUFFER_PX = 8

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full = text or ""
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setContentsMargins(0, 0, 0, 0)  # elide/draw width == the label's full width
        self.setToolTip(self._full)
        # Keep QLabel's own text set to the full string so its size-hint height stays
        # correct; the overridden paintEvent draws the elided form, so QLabel's default
        # (full-text) painter never runs.
        super().setText(self._full)

    def setText(self, text: str) -> None:  # keep _full authoritative if reused
        self._full = text or ""
        self.setToolTip(self._full)
        super().setText(self._full)  # updates height hints + text(); paintEvent re-elides

    def text(self) -> str:  # authoritative full text (not the elided paint)
        return self._full

    def minimumSizeHint(self) -> QSize:
        h = super().minimumSizeHint().height()
        return QSize(self.fontMetrics().horizontalAdvance("…"), h)

    def sizeHint(self) -> QSize:
        h = super().sizeHint().height()
        w = self.fontMetrics().horizontalAdvance(self._full) + self._HINT_BUFFER_PX
        return QSize(w, h)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setPen(QColor(_theme.COLOR_TEXT))  # token, never a literal
        elided = self.fontMetrics().elidedText(
            self._full, Qt.TextElideMode.ElideMiddle, self.width()
        )
        painter.drawText(self.rect(), int(self.alignment().value), elided)


def build_chip_row(
    *,
    media_icon: str,
    title: str,
    liked: bool = False,
    year: str = "",
    quality: str = "",
    prefix: str = "",
) -> QWidget:
    """Build a sidebar content row: ``[icon] Title [4K] … [Year] [Lang]``.

    The canonical chip row shared by Recommended, Watch Queue, Favorites and
    History.  Mirrors the mouse-transparent ``setItemWidget`` pattern: the row is
    ``WA_TransparentForMouseEvents`` so the hosting ``QListWidget`` item keeps
    ownership of click / double-click / context-menu / selection.

    Layout, left→right: an icon (with an optional 👍 like glyph prefixed), then the
    middle-eliding title sized to its content (Preferred policy, no stretch,
    buffered ``sizeHint`` — see :class:`MiddleElideLabel` — so a title that fits is
    never clipped), then the quality badge (``QUALITY_CHIP``) hugging the title
    TEXT when present, then a stretch, then the right-aligned cluster: the year as a
    subtle bordered chip (``YEAR_CHIP``) and the audio-language chip (``LANG_CHIP``)
    as the CONSISTENT rightmost element on every row, so the right edge stays
    aligned.  Each chip is added only when its value is non-empty.

    Args:
        media_icon: The resolved media-type glyph (movie/series/live/unknown).
        title: The display title (already the clean ``detected_title`` / name).
        liked: When True, prefix the icon with the 👍 like glyph.
        year: The release year — rendered as a ``YEAR_CHIP`` when non-empty.
        quality: The quality token (e.g. "4K") — rendered as a ``QUALITY_CHIP``.
        prefix: The audio-language prefix (e.g. "EN") — the honest language, NEVER
            the source region — rendered as the far-right ``LANG_CHIP``.

    Returns:
        A mouse-transparent ``QWidget`` ready for ``QListWidget.setItemWidget``.
    """
    liked_prefix = f"{_icons.like_icon} " if liked else ""

    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(4, 1, 8, 1)
    layout.setSpacing(4)

    icon_lbl = QLabel(f"{liked_prefix}{media_icon}")
    layout.addWidget(icon_lbl)

    title_lbl = MiddleElideLabel(title)
    title_lbl.setStyleSheet(_theme.VOD_ALERT_NAME)  # COLOR_TEXT — legible title
    # Preferred + no stretch: the title sizes to its content so the 4K chip can hug
    # the title TEXT. MiddleElideLabel's buffered sizeHint keeps a title that fits
    # from being clipped; only a title too long for the row elides.
    title_lbl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
    layout.addWidget(title_lbl)

    # Quality (4K) chip hugs the title TEXT — reuse the existing QUALITY_CHIP badge
    # (QPushButton-scoped, so a flat non-focusable QPushButton renders it as a chip).
    if quality:
        quality_chip = QPushButton(quality)
        quality_chip.setFlat(True)
        quality_chip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        quality_chip.setStyleSheet(_theme.QUALITY_CHIP)
        layout.addWidget(quality_chip)

    layout.addStretch(1)  # pushes the year + language chips to the far right

    # Right-aligned cluster: the year as a subtle bordered chip (``YEAR_CHIP``) then
    # the language chip as the CONSISTENT far-right element on every row.
    if year:
        year_lbl = QLabel(str(year))
        year_lbl.setStyleSheet(_theme.YEAR_CHIP)  # subtle bordered chip
        layout.addWidget(year_lbl)

    # Language chip (QLabel — LANG_CHIP is label-friendly). This is the honest
    # detected_prefix, NOT the source detected_region.
    if prefix:
        lang_chip = QLabel(prefix)
        lang_chip.setStyleSheet(_theme.LANG_CHIP)
        lang_chip.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(lang_chip)

    row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    # The item (not this widget) owns click/double-click/context-menu — let mouse
    # events pass through to the QListWidget viewport.
    row.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    return row
