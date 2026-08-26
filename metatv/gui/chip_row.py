"""Shared sidebar row widget — one builder, two densities.

Every sidebar content list (Recommended, Watch Queue, Favorites, History) renders
through :func:`build_chip_row`, in one of two shapes the viewer chooses at
``Settings → Interface → Sidebar rows``:

**Compact** (the default) — one line::

    [icon] Title …………………………… [4K] [1985] [EN]

**Comfortable** — two lines, the second quieter::

    [icon] Title
           S05E03 · 2 hours ago

Compact is the default because the sidebar's scarcest resource is vertical
space: at ~20px against comfortable's ~37px it shows roughly twice the entries
in the same allocation, which is the whole point of a rail you scan.

**The media type is an ICON, never a word.** ``icon_role`` takes a semantic role
("movie"/"series"/"live") and paints the vector glyph for it. A row that spells
out "Movie · " on every line is repetition a glyph already handles for free, and
it costs the width the title needed — the icons exist precisely to avoid it.

Callers pass BOTH ``chips`` and ``meta`` and let the density decide which is
drawn, so switching density is one config read here rather than a branch in
every section.

Look a row's labels up with :func:`row_title_label` / :func:`row_meta_label`
rather than ``findChild`` — see their docstrings for the trap.
"""

from __future__ import annotations

from collections.abc import Sequence

from PyQt6.QtWidgets import (
    QLabel, QPushButton, QSizePolicy, QWidget, QHBoxLayout, QVBoxLayout,
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor, QPainter

from metatv.core.channel_name_utils import quality_display
from metatv.gui import theme as _theme
from metatv.gui import icons as _icons
from metatv.gui import icon_utils as _icon_utils

#: The two row shapes. Stored at ``Config.sidebar_row_density``.
DENSITY_COMPACT = "compact"
DENSITY_COMFORTABLE = "comfortable"
DENSITIES = (DENSITY_COMPACT, DENSITY_COMFORTABLE)

#: Chip kinds a caller may put in ``chips``, mapped to their theme role. These
#: are the SIDEBAR_CHIP_* family, not the channel list's YEAR_CHIP/LANG_CHIP:
#: those are sized for a 40px list row (YEAR_CHIP is 15px type, larger than the
#: 13px title beside it) and inflated a compact row to 27px. Quality is a
#: ``QPushButton`` because its role is QPushButton-scoped — as a QLabel the
#: badge silently renders as plain text.
CHIP_QUALITY = "quality"
CHIP_YEAR = "year"
CHIP_LANG = "lang"
CHIP_NEWS = "news"
#: Quality and news are absent on purpose: both sheets are COMPOSED at build
#: time — quality per tier (see :func:`_quality_chip_style`), news from
#: ``theme.on_fill`` (:func:`_news_chip_style`) — so neither has a single
#: static role.
_CHIP_ROLES = {
    CHIP_YEAR: "SIDEBAR_CHIP_YEAR",
    CHIP_LANG: "SIDEBAR_CHIP_LANG",
}

#: Object names for the row's two labels. A row has two ``MiddleElideLabel``
#: children and ``QObject.findChild`` searches breadth-first, so it returns the
#: META label and not the title. Every lookup goes through
#: :func:`row_title_label` / :func:`row_meta_label`; a drift-guard test fails the
#: suite on a bare ``findChild(MiddleElideLabel)``.
TITLE_OBJECT_NAME = "chipRowTitle"
META_OBJECT_NAME = "chipRowMeta"

#: The caller-supplied interactive button (History's "play next episode"). It
#: needs a name for the same reason the labels do: chips are ``QPushButton`` too
#: since they were unified onto one box model, so ``findChild(QPushButton)``
#: returns a CHIP — the row's quality badge — not the control the caller wired.
TRAILING_OBJECT_NAME = "chipRowTrailing"

#: The dim qualifier after the title. Named for the same reason the others are:
#: it is a plain ``QLabel`` and a bare ``findChild(QLabel)`` on a row would
#: return whichever one Qt reaches first.
SUFFIX_OBJECT_NAME = "chipRowSuffix"

#: Row-icon edge length, sized against the title's CAP HEIGHT rather than its
#: font size. A 13px font draws ~9px of capital, but a 13px icon is 13px of
#: visible glyph — so an icon nominally the same size as the text reads ~44%
#: bigger than the letters beside it, which is what "the type icons are still
#: too large" was seeing. 11px sits just above cap height, the usual
#: relationship between a glyph and the type it sits in.
ICON_PX = 11

#: The news marker's diameter. A ring, not a "NEW" pill: the pill was a second
#: word competing with the title, and the count beside it ("+12 eps") already
#: says what is new — so the marker only has to say THAT something is, and a
#: ring does that at a fraction of the width.
NEWS_DOT_PX = 9


class MiddleElideLabel(QLabel):
    """Single-line label that middle-elides ('Long ti…tle') only when genuinely
    too long for its width.

    Sizes to content: ``sizeHint`` = full-text advance + a small buffer, so — laid out
    with a Preferred policy and no stretch — a title that fits is given enough width and
    is NEVER clipped. The buffer absorbs the sub-pixel layout rounding that previously
    chopped even short titles ("1983" → "1…3"). Zero contents margins + eliding against
    the label's FULL ``width()`` in ``paintEvent`` (drawing in ``rect()``, not a
    margin-shrunk ``contentsRect()``) keeps the elide threshold identical to the draw
    area. Keeps the full text as the tooltip and as ``text()``.

    The pen comes from ``color_token``, resolved **by name at paint time** so a
    theme switch repaints in the new palette. It is a constructor argument rather
    than a stylesheet ``color:`` because this class paints itself: a role applied
    with ``theme.style()`` still governs font and background, but its ``color`` is
    never consulted by the overridden ``paintEvent``, so a two-line row styled
    that way rendered both lines in the same colour and the hierarchy silently did
    not exist.
    """

    _HINT_BUFFER_PX = 8

    def __init__(self, text: str = "", parent=None, *, color_token: str = "COLOR_TEXT"):
        super().__init__(parent)
        self._full = text or ""
        self._color_token = color_token
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setContentsMargins(0, 0, 0, 0)
        self.setToolTip(self._full)
        super().setText(self._full)

    def setText(self, text: str) -> None:
        self._full = text or ""
        self.setToolTip(self._full)
        super().setText(self._full)

    def text(self) -> str:
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
        painter.setPen(self.pen_color())
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
    """The row's META (second-line) label — ``None`` on a compact row."""
    return row.findChild(MiddleElideLabel, META_OBJECT_NAME)


def row_trailing_button(row: QWidget) -> QPushButton | None:
    """The row's interactive trailing button, or ``None``.

    Not ``findChild(QPushButton)``: the chips are flat QPushButtons too — they
    were unified onto one box model so their padding could not drift — so the
    bare lookup returns whichever chip Qt reaches first. A test asking "does
    this row have a play-next button" got a "4K" badge and passed.
    """
    return row.findChild(QPushButton, TRAILING_OBJECT_NAME)


def media_icon_role(media_type: str | None) -> str:
    """``"movie"`` / ``"series"`` / ``"live"`` — the icon role for a media type.

    Returns ``""`` for an unknown type, which draws no glyph rather than a
    placeholder: an unknown row loses its icon, never its row.
    """
    role = (media_type or "").strip().lower()
    return role if role in ("movie", "series", "live") else ""


def episode_code(season_num: int | None, episode_num: int | None) -> str:
    """``"S05E03"`` from a season/episode pair, or ``""`` when either is missing."""
    if season_num is None or episode_num is None:
        return ""
    return f"S{season_num:02d}E{episode_num:02d}"


def quality_word(quality: str | None) -> str:
    """``"RAW"`` → ``"Uncompressed"`` — the quality token as a viewer sees it.

    Routes through :func:`~metatv.core.channel_name_utils.quality_display`, the
    one chokepoint that turns a stored token into a label, so the sidebar never
    shows "RAW" to mean "uncompressed" — which reads as its opposite.
    """
    return quality_display(quality.upper()) if quality else ""


def sidebar_meta_line(*parts: str | None) -> str:
    """Compose a comfortable row's second line — ``"S18E01 · 2 hours ago"``.

    One builder for all four sections so the separator, the ordering convention
    (most specific first) and the treatment of missing values cannot drift.
    Empty and ``None`` parts are dropped rather than leaving a dangling
    separator — a live channel has no year and no language, and its meta line
    has to read "3 days ago", never "· · 3 days ago".
    """
    return " · ".join(str(p) for p in parts if p)


def _icon_label(role: str) -> QLabel | None:
    """A theme-tracking QLabel holding the vector glyph for *role*.

    Registered through ``theme.style_fn`` because an already-rasterised pixmap
    cannot change colour on its own — the builder re-renders it on every palette
    switch, which is the same mechanism the section headers use.
    """
    if not role:
        return None
    label = QLabel()
    label.setFixedWidth(ICON_PX)

    def _build() -> str:
        pixmap = _icon_utils.vector_pixmap(
            _icons.vector_key(role), _theme.COLOR_TEXT, ICON_PX
        )
        if pixmap is not None and not pixmap.isNull():
            label.setPixmap(pixmap)
        return ""      # the label carries no sheet of its own

    _theme.style_fn(label, _build)
    return label


def _news_dot() -> QLabel:
    """The "this has news" marker — a small ring, painted in the OK colour.

    Never colour alone: the ring is a SHAPE that no other row carries, and the
    count beside it ("+12 eps", "1 new") is the words. It replaced a "NEW" pill,
    which was a second piece of text competing with the title it sat in front of.
    """
    label = QLabel()
    label.setFixedWidth(NEWS_DOT_PX)
    label.setToolTip("New since you last looked")

    def _build() -> str:
        pixmap = _icon_utils.vector_pixmap(
            _icons.vector_key("news"), _theme.COLOR_OK, NEWS_DOT_PX
        )
        if pixmap is not None and not pixmap.isNull():
            label.setPixmap(pixmap)
        return ""

    _theme.style_fn(label, _build)
    return label


def _quality_chip_style(text: str) -> str:
    """The quality chip's sheet: tier-coloured text on the NEUTRAL hairline.

    Two things were wrong with the flat role this replaced. It painted every
    tier one ``COLOR_WARN``, discarding the per-tier hue the ``quality`` tokens
    define (amber RAW, orange LIVE, cyan HD, purple 4K) — and it drew the border
    in that same full-strength colour, which is most of what made the chip
    shout: at ``COLOR_WARN`` on Midnight the ring measures 10.4:1, louder than
    the title it annotates.

    Splitting the two fixes both. The TEXT keeps the per-tier outline colour,
    which carries the 4.5:1 floor (guarded by ``test_palette_completeness``);
    the BORDER drops to ``COLOR_BORDER``, the same hairline the year chip uses,
    which has no contrast requirement to meet. The tier still reads, the chip
    stops competing, and every chip in a row now shares one border so they look
    like a family instead of three unrelated objects.

    Args:
        text: The quality token as stored ("RAW", "4K", "HD"…).

    Returns:
        A ``QPushButton``-scoped stylesheet string.
    """
    from metatv.gui.badge_utils import quality_outline_color

    return (
        f"QPushButton {{ color: {quality_outline_color(text)};"
        f" border: 1px solid {_theme.COLOR_BORDER};"
        f" background: transparent;"
        f" border-radius: {_theme.RADIUS_SM}; padding: 0px 5px;"
        f" font-size: {_theme.FONT_XS}; }}"
    )


def _news_chip_style() -> str:
    """The "+N" pill: FILLED, not tinted text.

    It is the one thing on a row you are meant to notice, and the loudest
    element the V3 row grammar allows. The foreground comes from
    ``theme.on_fill`` rather than a hardcoded white, because the fill carries
    the palette — a ``COLOR_OK`` pill is mint in the dark themes and forest in
    Daylight, so the legible foreground flips with the FILL, not the theme.

    Distinct from ``SIDEBAR_ROW_NEWS``, which is the same count as bare OK-
    coloured TEXT. Both exist: text where the row already carries chips and a
    pill would be a third weight, a pill where the count is the row's headline.
    """
    fill = _theme.COLOR_OK
    return (
        f"QPushButton {{ color: {_theme.on_fill(fill)}; background: {fill};"
        f" border: 1px solid {fill}; border-radius: {_theme.RADIUS_SM};"
        f" padding: 0px 5px; font-size: {_theme.FONT_XS}; font-weight: bold; }}"
    )


def chip_widget(kind: str, text: str) -> QWidget:
    """One chip — a flat ``QPushButton`` whatever the kind.

    Public because a row that must KEEP a reference to one of its chips (Watch
    Alerts rewrites its time chip on a clock tick) has to build it rather than
    fish it back out of the assembled row by matching text — a lookup that
    silently returns the wrong widget the moment a title happens to equal a
    time string. Hand it to ``build_chip_row`` as ``tail_widget``.

    All three kinds are the same widget so they share one box model and one
    padding. As QLabels the year and language chips looked looser than the
    quality chip on identical declared padding, because a QLabel's border wraps
    the font's full line box while a button's hugs content + padding.

    Not interactive: flat, unfocusable and mouse-transparent, so the hosting
    list item keeps every click even on a row that carries a real button.
    """
    chip = QPushButton(text)
    chip.setFlat(True)
    chip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    chip.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    if kind == CHIP_NEWS:
        # style_fn for the same reason quality uses it: the sheet is composed
        # from runtime colour, so a rendered string goes stale on a switch.
        _theme.style_fn(chip, _news_chip_style)
    elif kind == CHIP_QUALITY:
        # Per-TIER hue, from badge_utils — the mapping that already owns
        # quality→colour. style_fn (not style) because the sheet is composed
        # from a runtime value, so it must be REBUILT on a palette switch;
        # a rendered string would go stale.
        _theme.style_fn(chip, lambda: _quality_chip_style(text))
    else:
        _theme.style(chip, _CHIP_ROLES[kind])
    return chip


def build_chip_row(
    *,
    title: str,
    icon_role: str = "",
    chips: Sequence[tuple[str, str]] = (),
    tail: str = "",
    news_text: str = "",
    meta: str = "",
    density: str = DENSITY_COMPACT,
    liked: bool = False,
    new_badge: bool = False,
    trailing_button: QPushButton | None = None,
    leading_slot: QWidget | None = None,
    title_suffix: str = "",
    title_chips: Sequence[tuple[str, str]] = (),
    tail_widget: QWidget | None = None,
    indent: int = 0,
) -> QWidget:
    """Build a sidebar content row in the caller's chosen density.

    Mirrors the mouse-transparent ``setItemWidget`` pattern: the row is
    ``WA_TransparentForMouseEvents`` so the hosting ``QListWidget`` item keeps
    ownership of click / double-click / context-menu / selection.

    ``trailing_button`` and row-wide transparency are mutually exclusive: a
    ``QPushButton`` consumes its own mouse press, but
    ``WA_TransparentForMouseEvents`` on an ANCESTOR hides its entire subtree from
    hit-testing — so a button in a transparent row would never receive a click at
    all. When one is given the row is left untransparent instead: plain labels
    still bubble unhandled clicks to the item exactly as before, while the button
    consumes its own, which is what makes it independently clickable.

    Args:
        title: The display title (already the clean ``detected_title`` / name).
        icon_role: ``"movie"`` / ``"series"`` / ``"live"`` — resolve it with
            :func:`media_icon_role`. Empty draws no glyph.
        chips: ``[(CHIP_QUALITY, "4K"), (CHIP_YEAR, "1985"), (CHIP_LANG, "EN")]``
            — drawn right-aligned in the given order, COMPACT density only.
            Each is skipped when its text is empty.
        tail: Terse muted text pinned to the right edge ("2h", "329m"), after the
            chips. Compact density only — it is where History spends the slot the
            language chip would otherwise take.
        news_text: The count on a row that has news ("+12 eps", "1 new"), drawn
            at the right edge in the OK colour. Pairs with ``new_badge``: the
            ring says THAT there is news, this says how much. Shown in BOTH
            densities — a count is the reason the row is worth looking at, so
            it is not something the compact shape trades away.
        meta: The second line ("S18E01 · 2 hours ago"), COMFORTABLE density only.
            Compose it with :func:`sidebar_meta_line`.
        density: :data:`DENSITY_COMPACT` or :data:`DENSITY_COMFORTABLE`. An
            unknown value falls back to compact rather than raising — a bad
            config value should cost the preference, not the sidebar.
        liked: When True, prefix the row with the 👍 like glyph.
        new_badge: When True, show a small "NEW" pill before the title — the word
            itself is the cue, never colour alone.
        trailing_button: An already-built, already-styled ``QPushButton`` (the
            caller owns its click wiring) appended as the row's last element.
        leading_slot: A caller-owned widget pinned at the ABSOLUTE left, before
            everything else including ``liked`` and ``icon_role``. Give it a
            fixed width: the point of the slot is that it reserves its column
            whether or not it currently holds anything, so a marker appearing
            on hover cannot shove the rest of the row sideways. Watch Alerts
            paints play / caret / new-dot into one such slot.
        title_chips: Chips drawn with the TITLE, left of the stretch, rather
            than in the right-hand rail. The distinction is what the chip
            claims: a quality token or an episode code is a fact about THIS
            copy and travels with its name, while ``chips`` are facts about the
            row's place in the list and belong in the rail. Owner, on the Watch
            Alerts grammar: "the quality chip should be align left right after
            the channel title".
        title_suffix: A quieter qualifier immediately after the title — a
            collision disambiguator when two rows share a cleaned name. Takes
            ``SIDEBAR_ROW_TAIL``, the row family's existing "terse and
            subordinate" role, rather than a second definition of the same idea.
            It never elides: it is what tells two identical titles apart, so it
            is the last thing that should be dropped.
        tail_widget: A caller-owned widget in the right-hand cluster, after the
            chips and ``tail``. For a fact that cannot be a string — Watch
            Alerts puts a programme's progress bar here.
        indent: Left inset, for a child row nested under a parent. Supplied by
            the caller rather than a tree's ``setIndentation``, which also
            indents TOP-level rows and so gives a section two left edges.

    Returns:
        A ``QWidget`` ready for ``QListWidget.setItemWidget``.
    """
    comfortable = density == DENSITY_COMFORTABLE and bool(meta)

    row = QWidget()
    if comfortable:
        outer = QVBoxLayout(row)
        # Tight, deliberately: a two-line row costs the sidebar its scarcest
        # resource, so every pixel of padding is a row someone does not see.
        outer.setContentsMargins(4, 1, 8, 1)  # indent goes on the inner line
        outer.setSpacing(0)
        title_line = QWidget()
        outer.addWidget(title_line)
        layout = QHBoxLayout(title_line)
        layout.setContentsMargins(indent, 0, 0, 0)
    else:
        outer = None
        layout = QHBoxLayout(row)
        layout.setContentsMargins(4 + indent, 1, 8, 1)
    layout.setSpacing(5)

    # Absolute left, ahead of every other leading element: the slot is the
    # column titles align against, so anything placed before it would break the
    # alignment it exists to provide.
    if leading_slot is not None:
        layout.addWidget(leading_slot)

    if liked:
        like_lbl = QLabel(_icons.like_icon)
        like_lbl.setToolTip("You liked this")
        layout.addWidget(like_lbl)

    icon_lbl = _icon_label(icon_role)
    if icon_lbl is not None:
        layout.addWidget(icon_lbl)

    if new_badge:
        layout.addWidget(_news_dot())

    # COLOR_TEXT_HI, one step brighter than the meta line's COLOR_TEXT: the
    # hierarchy between the two lines IS the design, and both clear 4.5:1 on
    # every card surface.
    title_lbl = MiddleElideLabel(title, color_token="COLOR_TEXT_HI")
    title_lbl.setObjectName(TITLE_OBJECT_NAME)
    _theme.style(title_lbl, "SIDEBAR_ROW_TITLE")
    title_lbl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
    layout.addWidget(title_lbl)

    if title_suffix:
        suffix_lbl = QLabel(title_suffix)
        suffix_lbl.setObjectName(SUFFIX_OBJECT_NAME)
        _theme.style(suffix_lbl, "SIDEBAR_ROW_TAIL")
        layout.addWidget(suffix_lbl)

    for kind, text in title_chips:
        if text:
            layout.addWidget(chip_widget(kind, text))

    layout.addStretch(1)

    if not comfortable:
        # The right-aligned cluster. Chips carry what distinguishes THIS
        # section's rows — see each section for which it spends them on.
        for kind, text in chips:
            if text:
                layout.addWidget(chip_widget(kind, text))
        if tail:
            tail_lbl = QLabel(tail)
            _theme.style(tail_lbl, "SIDEBAR_ROW_TAIL")
            layout.addWidget(tail_lbl)
        if tail_widget is not None:
            layout.addWidget(tail_widget)

    if news_text:
        news_lbl = QLabel(news_text)
        _theme.style(news_lbl, "SIDEBAR_ROW_NEWS")
        layout.addWidget(news_lbl)

    if trailing_button is not None:
        trailing_button.setObjectName(TRAILING_OBJECT_NAME)
        layout.addWidget(trailing_button)

    if comfortable:
        meta_lbl = MiddleElideLabel(meta, color_token="COLOR_TEXT")
        meta_lbl.setObjectName(META_OBJECT_NAME)
        _theme.style(meta_lbl, "SIDEBAR_ROW_META")
        # Ignored horizontally: the meta line never widens the row. A long
        # "S05E03 · 2 hours ago" elides rather than forcing the section wider
        # than the titles need.
        meta_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        if icon_lbl is not None:
            # Indent under the title, not under the icon — the second line is
            # subordinate to the TITLE, and hanging it below the glyph reads as
            # a second row rather than a continuation.
            holder = QWidget()
            hl = QHBoxLayout(holder)
            hl.setContentsMargins(ICON_PX + 5, 0, 0, 0)
            hl.setSpacing(0)
            hl.addWidget(meta_lbl)
            outer.addWidget(holder)
        else:
            outer.addWidget(meta_lbl)

    row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    if trailing_button is None:
        row.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    return row
