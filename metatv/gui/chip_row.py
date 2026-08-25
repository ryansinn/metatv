"""Shared sidebar row widget: a title over a quiet meta line.

One canonical builder for every sidebar content list (Recommended, Watch Queue,
Favorites, History), so the rows read identically.

**V3 changed the shape of this row.** It used to be a single line carrying an
icon and a right-aligned cluster of chips — ``[icon] Title [4K] … [Year] [Lang]``
— and it is now two lines of text: the title, and underneath it the
circumstantial detail in a quieter colour. Chips are a *channel-list* idiom in
V3, where a row is 40+px tall and the eye is comparing versions of one title; in
a 260px sidebar they cost the width the title needed, and three of them stacked
against the right margin turned every section into a column of badges with
titles behind them. The facts they carried are not lost — they compose into the
meta line via :func:`sidebar_meta_line`, where "Movie · 1985 · EN" says what
three chips said, in reading order, for less width.

``MiddleElideLabel`` is the anti-clip label both lines use; ``build_chip_row``
assembles the mouse-transparent row so a ``QListWidget`` item can host it via
``setItemWidget``. Look a label up with :func:`row_title_label` /
:func:`row_meta_label` rather than ``findChild`` — see their docstrings for the
trap that motivates them.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QLabel, QPushButton, QSizePolicy, QWidget, QHBoxLayout, QVBoxLayout,
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor, QPainter

from metatv.core.channel_name_utils import quality_display
from metatv.core.models import MediaType
from metatv.gui import theme as _theme
from metatv.gui import icons as _icons

#: Object names for the row's two labels. A row has two ``MiddleElideLabel``
#: children and ``QObject.findChild`` searches breadth-first, so it returns the
#: META label (a direct child) and not the title (one level deeper, inside the
#: title line). Every lookup goes through :func:`row_title_label` /
#: :func:`row_meta_label`; a drift-guard test fails the suite on a bare
#: ``findChild(MiddleElideLabel)``.
TITLE_OBJECT_NAME = "chipRowTitle"
META_OBJECT_NAME = "chipRowMeta"


class MiddleElideLabel(QLabel):
    """Single-line label that middle-elides ('Long ti…tle') only when genuinely
    too long for its width.

    Sizes to content: ``sizeHint`` = full-text advance + a small buffer, so — laid out
    with a Preferred policy and no stretch — a title that fits is given enough width and
    is NEVER clipped. The buffer absorbs the sub-pixel layout rounding that previously
    chopped even short titles ("1983" → "1…3"). Zero contents margins + eliding against
    the label's FULL ``width()`` in ``paintEvent`` (drawing in ``rect()``, not a
    margin-shrunk ``contentsRect()``) keeps the elide threshold identical to the draw
    area, so a title exactly as wide as its box still renders in full. Only when the row
    is too narrow does the label shrink toward ``minimumSizeHint`` (width of "…") and the
    title middle-elide. Keeps the full text as the tooltip and as ``text()``.

    The pen comes from ``color_token``, resolved **by name at paint time** so a
    theme switch repaints in the new palette without re-instantiating the label.
    It is a constructor argument rather than a stylesheet ``color:`` because this
    class paints itself: a role applied with ``theme.style()`` still governs the
    label's font and background, but its ``color`` is never consulted by the
    overridden ``paintEvent``, so a two-line row styled that way rendered both
    lines in the same colour and the visual hierarchy silently did not exist.
    """

    # Slack added to the preferred width so a title that fits is never clipped by
    # sub-pixel layout rounding (guards the "1983" → "1…3" regression).
    _HINT_BUFFER_PX = 8

    def __init__(self, text: str = "", parent=None, *, color_token: str = "COLOR_TEXT"):
        super().__init__(parent)
        self._full = text or ""
        self._color_token = color_token
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

    def pen_color(self) -> QColor:
        """The colour this label paints in, resolved from the live theme."""
        return QColor(getattr(_theme, self._color_token, _theme.COLOR_TEXT))

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setPen(self.pen_color())  # token, never a literal
        elided = self.fontMetrics().elidedText(
            self._full, Qt.TextElideMode.ElideMiddle, self.width()
        )
        painter.drawText(self.rect(), int(self.alignment().value), elided)


def row_title_label(row: QWidget) -> MiddleElideLabel | None:
    """The row's TITLE label, unambiguously.

    ``row.findChild(MiddleElideLabel)`` does not do this: Qt searches direct
    children before recursing, so on a two-line row it returns the meta label
    and every caller silently starts reading "1982 · UK" where it meant
    "Blade Runner". Seven call sites had that shape when the second line landed.
    """
    return row.findChild(MiddleElideLabel, TITLE_OBJECT_NAME)


def row_meta_label(row: QWidget) -> MiddleElideLabel | None:
    """The row's META (second-line) label, or ``None`` on a single-line row."""
    return row.findChild(MiddleElideLabel, META_OBJECT_NAME)


def media_type_word(media_type: str | None) -> str:
    """"Movie" / "Series" / "Live" — the media type as a WORD for the meta line.

    V3 drops the per-row media-type emoji, so the type now travels as the first
    part of the meta line ("Movie · 1985"). A word also satisfies the project's
    never-colour-or-glyph-alone rule outright, which a 🎬 never did.
    """
    return {
        MediaType.MOVIE: "Movie",
        MediaType.SERIES: "Series",
        MediaType.LIVE: "Live",
    }.get(media_type or "", "")


def quality_word(quality: str | None) -> str:
    """``"RAW"`` → ``"Uncompressed"`` — the quality token as the meta line shows it.

    Routes through :func:`~metatv.core.channel_name_utils.quality_display`, the
    one chokepoint that turns a stored token into a viewer-facing label. The
    quality chip did this and the meta line that replaced it has to as well, or
    the sidebar quietly starts showing "RAW" to mean "uncompressed" — which
    reads as the opposite of what it is. Uppercased first, per that function's
    contract for the badge-tier convention.
    """
    return quality_display(quality.upper()) if quality else ""


def episode_code(season_num: int | None, episode_num: int | None) -> str:
    """``"S05E03"`` from a season/episode pair, or ``""`` when either is missing."""
    if season_num is None or episode_num is None:
        return ""
    return f"S{season_num:02d}E{episode_num:02d}"


def sidebar_meta_line(*parts: str | None) -> str:
    """Compose a row's second line — ``"S18E01 · 2 hours ago"``.

    One builder for all four sidebar sections so the separator, the ordering
    convention (most specific first) and the treatment of missing values cannot
    drift between them. Empty and ``None`` parts are dropped rather than
    leaving a dangling separator, which is the whole reason this is a function
    and not four f-strings — a live channel has no year and no language, and its
    meta line has to read "3 days ago", never "· · 3 days ago".
    """
    return " · ".join(str(p) for p in parts if p)


def build_chip_row(
    *,
    title: str,
    meta: str = "",
    liked: bool = False,
    new_badge: bool = False,
    trailing_button: QPushButton | None = None,
) -> QWidget:
    """Build a sidebar content row: a title, and optionally a meta line under it.

    The canonical row shared by Recommended, Watch Queue, Favorites and History.
    Mirrors the mouse-transparent ``setItemWidget`` pattern: the row is
    ``WA_TransparentForMouseEvents`` so the hosting ``QListWidget`` item keeps
    ownership of click / double-click / context-menu / selection.

    Layout: an optional 👍 like glyph and an optional "NEW" pill, then the
    middle-eliding title sized to its content (Preferred policy, no stretch,
    buffered ``sizeHint`` — see :class:`MiddleElideLabel` — so a title that fits
    is never clipped), then a stretch, then an optional interactive
    ``trailing_button`` (e.g. History's "Play next episode" ``>>``). When ``meta``
    is given, a second, quieter line is added beneath that whole first line.

    ``trailing_button`` and row-wide transparency are mutually exclusive: a
    ``QPushButton`` consumes its own mouse press (it never bubbles up, unlike a
    plain unhandled ``QLabel``, which ignores the event and lets it bubble to the
    hosting ``QListWidget`` for selection) — but ``WA_TransparentForMouseEvents``
    on an ANCESTOR hides its entire subtree from hit-testing, including any
    non-transparent button inside it, so a button embedded in the current
    all-or-nothing transparent row would never receive a click at all. So when
    ``trailing_button`` is given, the row is left at Qt's default (untransparent)
    instead: every plain label still bubbles unhandled clicks up to the list item
    exactly as before, while the button — landed on directly — consumes its own
    click, which is exactly what makes it independently clickable.

    Args:
        title: The display title (already the clean ``detected_title`` / name).
        meta: The second line — "S18E01 · 12 min left", "1984 · yesterday",
            "Movie · 1985 · EN". Compose it with :func:`sidebar_meta_line` so
            missing parts drop cleanly. When empty the row stays single-line, so
            a caller with nothing to say on a second line does not grow one.
        liked: When True, prefix the title with the 👍 like glyph.
        new_badge: When True, show a small "NEW" pill before the title (e.g. the
            Watch Queue's "Alerts Matched" rows) — the word "NEW" itself is the
            cue, never colour alone.
        trailing_button: An optional, already-built, already-styled/tooltipped
            ``QPushButton`` (the caller owns its click wiring) appended as the
            first line's rightmost element. When present, the row does NOT get
            the blanket ``WA_TransparentForMouseEvents`` treatment (see above) so
            the button stays clickable.

    Returns:
        A ``QWidget`` ready for ``QListWidget.setItemWidget`` — mouse-transparent
        when ``trailing_button`` is ``None`` (the default), otherwise left
        untransparent so the trailing button can receive clicks.
    """
    # A two-line row when the caller has a meta line, one when it does not. The
    # title line is built inside its own container widget in the two-line case so
    # the meta label sits UNDER the whole line (title, badges and button), not
    # beside the title inside it.
    row = QWidget()
    if meta:
        outer = QVBoxLayout(row)
        # Tight, deliberately: a two-line row costs the sidebar its scarcest
        # resource, so every pixel of padding is a row someone does not get to
        # see. At these margins the row is ~34px against the single-line row's
        # ~20 — see CollapsibleSection.CONTENT_ROW_H, which is derived from it.
        outer.setContentsMargins(4, 1, 8, 1)
        outer.setSpacing(0)
        title_line = QWidget()
        outer.addWidget(title_line)
        layout = QHBoxLayout(title_line)
        layout.setContentsMargins(0, 0, 0, 0)
    else:
        outer = None
        layout = QHBoxLayout(row)
        layout.setContentsMargins(4, 1, 8, 1)
    layout.setSpacing(4)

    if liked:
        like_lbl = QLabel(_icons.like_icon)
        like_lbl.setToolTip("You liked this")
        layout.addWidget(like_lbl)

    if new_badge:
        new_lbl = QLabel("NEW")
        _theme.style(new_lbl, "QUEUE_MATCHED_NEW_TAG")
        layout.addWidget(new_lbl)

    # COLOR_TEXT_HI, one step brighter than the meta line's COLOR_TEXT: the
    # hierarchy between the two lines IS the design, and both tokens clear 4.5:1
    # on every card surface, so the quiet line is quiet without being dim.
    title_lbl = MiddleElideLabel(title, color_token="COLOR_TEXT_HI")
    title_lbl.setObjectName(TITLE_OBJECT_NAME)
    _theme.style(title_lbl, "SIDEBAR_ROW_TITLE")
    # Preferred + no stretch: the title sizes to its content. MiddleElideLabel's
    # buffered sizeHint keeps a title that fits from being clipped; only a title
    # too long for the row elides.
    title_lbl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
    layout.addWidget(title_lbl)

    layout.addStretch(1)

    if trailing_button is not None:
        layout.addWidget(trailing_button)

    if outer is not None:
        meta_lbl = MiddleElideLabel(meta, color_token="COLOR_TEXT")
        meta_lbl.setObjectName(META_OBJECT_NAME)
        _theme.style(meta_lbl, "SIDEBAR_ROW_META")
        # Ignored horizontally: the meta line never widens the row. It is the
        # subordinate line — a long "Movie · 1985 · EN" elides rather than
        # forcing the section wider than the titles need.
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
