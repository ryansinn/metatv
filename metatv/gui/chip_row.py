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
    QLabel, QPushButton, QSizePolicy, QWidget, QHBoxLayout, QVBoxLayout,
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor, QPainter

from metatv.core.channel_name_utils import quality_display, quality_tooltip
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


def sidebar_meta_line(*parts: str | None) -> str:
    """Compose a row's second line — ``"S18E01 · 12 min left"``.

    One builder for all four sidebar sections so the separator, the ordering
    convention (most specific first) and the treatment of missing values cannot
    drift between them. Empty and ``None`` parts are dropped rather than
    leaving a dangling separator, which is the whole reason this is a function
    and not four f-strings.
    """
    return " · ".join(str(p) for p in parts if p)


def build_chip_row(
    *,
    media_icon: str,
    title: str,
    liked: bool = False,
    year: str = "",
    quality: str = "",
    prefix: str = "",
    new_badge: bool = False,
    meta: str = "",
    trailing_button: QPushButton | None = None,
) -> QWidget:
    """Build a sidebar content row: ``[icon] [NEW] Title [4K] … [Year] [Lang] [▶]``.

    The canonical chip row shared by Recommended, Watch Queue, Favorites and
    History.  Mirrors the mouse-transparent ``setItemWidget`` pattern: the row is
    ``WA_TransparentForMouseEvents`` so the hosting ``QListWidget`` item keeps
    ownership of click / double-click / context-menu / selection.

    Layout, left→right: an icon (with an optional 👍 like glyph prefixed), an
    optional "NEW" pill (``new_badge``), then the middle-eliding title sized to
    its content (Preferred policy, no stretch, buffered ``sizeHint`` — see
    :class:`MiddleElideLabel` — so a title that fits is never clipped), then the
    quality badge (``QUALITY_CHIP``) hugging the title TEXT when present, then a
    stretch, then the right-aligned cluster: the year as a subtle bordered chip
    (``YEAR_CHIP``) and the audio-language chip (``LANG_CHIP``) as the CONSISTENT
    rightmost element on every row, so the right edge stays aligned, and finally
    an optional interactive ``trailing_button`` (e.g. History's "Play next
    episode" ``>>``) as the very last element.  Each chip is added only when its
    value is non-empty.

    ``trailing_button`` and row-wide transparency are mutually exclusive: a
    ``QPushButton`` consumes its own mouse press (it never bubbles up, unlike a
    plain unhandled ``QLabel``, which ignores the event and lets it bubble to the
    hosting ``QListWidget`` for selection) — but ``WA_TransparentForMouseEvents``
    on an ANCESTOR hides its entire subtree from hit-testing, including any
    non-transparent button inside it, so a button embedded in the current
    all-or-nothing transparent row would never receive a click at all. So when
    ``trailing_button`` is given, the row is left at Qt's default (untransparent)
    instead: every plain label still bubbles unhandled clicks up to the list item
    exactly as before (no behavior change there), while the button — landed on
    directly — now consumes its own click instead of bubbling, which is exactly
    what makes it independently clickable. Rows with no ``trailing_button`` are
    completely unaffected — the row stays ``WA_TransparentForMouseEvents`` exactly
    as before, pixel-identical to every existing caller.

    Args:
        media_icon: The resolved media-type glyph (movie/series/live/unknown).
        title: The display title (already the clean ``detected_title`` / name).
        liked: When True, prefix the icon with the 👍 like glyph.
        year: The release year — rendered as a ``YEAR_CHIP`` when non-empty.
        quality: The quality token (e.g. "4K") — rendered as a ``QUALITY_CHIP``.
        prefix: The audio-language prefix (e.g. "EN") — the honest language, NEVER
            the source region — rendered as the far-right ``LANG_CHIP``.
        new_badge: When True, show a small green "NEW" pill after the icon (e.g.
            the Watch Queue's "Alerts Matched" rows) — the word "NEW" itself is
            the cue, never colour alone.
        meta: The second line — "S18E01 · 12 min left", "1984 · yesterday",
            "Series · new episodes". When empty the row stays single-line and is
            pixel-identical to what it was, so a caller that has nothing to say
            on a second line does not grow one.
        trailing_button: An optional, already-built, already-styled/tooltipped
            ``QPushButton`` (the caller owns its click wiring) appended as the
            row's rightmost element. When present, the row does NOT get the
            blanket ``WA_TransparentForMouseEvents`` treatment (see above) so the
            button stays clickable.

    Returns:
        A ``QWidget`` ready for ``QListWidget.setItemWidget`` — mouse-transparent
        when ``trailing_button`` is ``None`` (the default, existing behavior),
        otherwise left untransparent so the trailing button can receive clicks.
    """
    liked_prefix = f"{_icons.like_icon} " if liked else ""

    # A two-line row when the caller has a meta line, one when it does not.
    # The V3 sidebar render puts the identifying text on top and the
    # circumstantial detail — episode, how long left, when you watched it —
    # underneath in a quieter colour, so a glance reads titles and a second
    # look reads state. Built as VBox-over-HBox rather than a second widget
    # type so every existing caller keeps the same function and the same row.
    row = QWidget()
    if meta:
        outer = QVBoxLayout(row)
        outer.setContentsMargins(4, 3, 8, 3)
        outer.setSpacing(1)
        line = QWidget()
        outer.addWidget(line)
        layout = QHBoxLayout(line)
        layout.setContentsMargins(0, 0, 0, 0)
    else:
        outer = None
        layout = QHBoxLayout(row)
        layout.setContentsMargins(4, 1, 8, 1)
    layout.setSpacing(4)

    icon_lbl = QLabel(f"{liked_prefix}{media_icon}")
    layout.addWidget(icon_lbl)

    if new_badge:
        new_lbl = QLabel("NEW")
        _theme.style(new_lbl, "QUEUE_MATCHED_NEW_TAG")
        layout.addWidget(new_lbl)

    title_lbl = MiddleElideLabel(title)
    _theme.style(title_lbl, "VOD_ALERT_NAME")  # COLOR_TEXT — legible title
    # Preferred + no stretch: the title sizes to its content so the 4K chip can hug
    # the title TEXT. MiddleElideLabel's buffered sizeHint keeps a title that fits
    # from being clipped; only a title too long for the row elides.
    title_lbl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
    layout.addWidget(title_lbl)

    # Quality (4K) chip hugs the title TEXT — reuse the existing QUALITY_CHIP badge
    # (QPushButton-scoped, so a flat non-focusable QPushButton renders it as a chip).
    if quality:
        quality_chip = QPushButton(quality_display(quality.upper()))
        quality_chip.setFlat(True)
        quality_chip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        _theme.style(quality_chip, "QUALITY_CHIP")
        quality_chip.setToolTip(quality_tooltip(quality))
        layout.addWidget(quality_chip)

    layout.addStretch(1)  # pushes the year + language chips to the far right

    # Right-aligned cluster: the year as a subtle bordered chip (``YEAR_CHIP``) then
    # the language chip as the CONSISTENT far-right element on every row.
    if year:
        year_lbl = QLabel(str(year))
        _theme.style(year_lbl, "YEAR_CHIP")  # subtle bordered chip
        layout.addWidget(year_lbl)

    # Language chip (QLabel — LANG_CHIP is label-friendly). This is the honest
    # detected_prefix, NOT the source detected_region.
    if prefix:
        lang_chip = QLabel(prefix)
        _theme.style(lang_chip, "LANG_CHIP")
        lang_chip.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(lang_chip)

    if trailing_button is not None:
        layout.addWidget(trailing_button)

    # The second line, added after the title line is complete so the chips above
    # keep their existing order.
    if outer is not None:
        meta_lbl = MiddleElideLabel(meta)
        _theme.style(meta_lbl, "SIDEBAR_ROW_META")
        meta_lbl.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        outer.addWidget(meta_lbl)

    row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    if trailing_button is None:
        # The item (not this widget) owns click/double-click/context-menu — let mouse
        # events pass through to the QListWidget viewport. Skipped when a
        # trailing_button is present — see the docstring: this attribute would hide
        # the button's whole subtree from hit-testing too, so it would never be
        # clickable.
        row.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    return row
