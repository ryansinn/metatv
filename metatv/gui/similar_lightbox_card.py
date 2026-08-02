"""The poster-hero content card for the Similar-Titles lightbox.

Split out of ``similar_lightbox.py`` so responsibilities read off the file
structure (self-documenting modularity, and both files stay well under the
1000-line limit):

- ``SimilarTitleLightbox`` (the overlay) owns the backdrop, prev/next chevrons,
  navigation state, the background DB read (``_bg_load``) and the ImageCache.
- ``_LightboxCard`` (here) owns the card's widget tree — header, poster hero,
  metadata, rating cluster, actions, Overview, Cast, **Other Versions**, the
  **Similar Titles** strip and the keyboard-hint footer — plus the populate
  logic.  It is a *dumb view*: it emits user intents as signals (the overlay
  attaches the current channel id and relays them) and exposes a single
  ``set_poster_pixmap`` seam so the overlay — which owns the ImageCache — can
  drive async image loading on the main thread (QPixmap is main-thread only).

The poster slot is deliberately built as a self-contained ``_HoverPosterSlot``
so a future embedded player can drop into the same footprint; clicking it enlarges
the poster (the same peek affordance as the details pane), while the dedicated
Play button owns playback.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QAbstractScrollArea, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

if TYPE_CHECKING:
    from metatv.core.database import Database

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.cursor_affordance import set_clickable
from metatv.gui.flow_layout import FlowLayout
from metatv.gui.lightbox_breadcrumb import LightboxBreadcrumb
from metatv.gui.sim_badges import make_sim_badges

# Poster / strip-card dimensions (structural spacing — px is fine inline).
# Poster is the mockup's 2:3 poster-hero; strip cards are 116×174 (also 2:3).
_POSTER_W, _POSTER_H = 168, 252
_SIM_W, _SIM_H = 116, 174

# Max width of the hero's Other-Versions chip column (flow-wraps the compact chips
# in the upper-right; the metadata column takes the rest of the hero).
_VERSIONS_COL_W = 240

# Responsive card-width bounds. The overlay sizes the card to a fraction of the
# window between these (single source of truth — imported by ``similar_lightbox``);
# the card's Fixed/Maximum size policy then lets height grow to content up to the
# overlay's 0.9×window cap. A sensible floor means it never collapses.
CARD_MIN_W = 760
CARD_MAX_W = 1150


def _fmt_runtime(minutes: int | None) -> str:
    """Return a human runtime like ``2h 9m`` / ``48m`` from whole minutes."""
    if not minutes or minutes <= 0:
        return ""
    h, m = divmod(int(minutes), 60)
    if h and m:
        return f"{h}h {m}m"
    if h:
        return f"{h}h"
    return f"{m}m"


_MEDIA_TYPE_ICON = {
    "movie": _icons.movie_icon,
    "series": _icons.series_icon,
    "live": _icons.live_icon,
}


class _GrowScrollArea(QScrollArea):
    """A scroll area whose size-hint tracks its content instead of the stock cap.

    Stock ``QScrollArea.sizeHint()`` clamps to ``24 × fontMetrics().height()``
    (~400px) even with ``AdjustToContents`` set, so a ``Fixed/Maximum``-height
    parent can never grow past that — the exact reason the lightbox body used to
    fold every section below a scrollbar on a large window. Reporting the inner
    content's real height (plus the frame) lets the card grow to its natural
    content height up to the overlay's cap; the vertical scrollbar then appears
    only once content genuinely exceeds that cap.

    Height is measured with ``heightForWidth`` at the actual content width so the
    wrapping FlowLayout sections (genre / Other-Versions chips) report the height
    they *really* occupy — their raw one-chip-per-row size-hint would over-grow
    the card and leave dead space below the last section on a tall window.
    """

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt override)
        w = self.widget()
        if w is None:
            return super().sizeHint()
        frame = 2 * self.frameWidth()
        hint = w.sizeHint()
        height = hint.height()
        lay = w.layout()
        avail = self.viewport().width() or w.width()
        if avail > 0 and lay is not None and lay.hasHeightForWidth():
            hfw = lay.heightForWidth(avail)
            if hfw > 0:
                height = hfw
        return QSize(hint.width() + frame, height + frame)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # heightForWidth depends on the viewport width, so when the width changes
        # our size-hint changes too — re-publish it to the parent card's layout
        # (otherwise the card keeps a stale, taller hint and leaves dead space).
        super().resizeEvent(event)
        if event.oldSize().width() != event.size().width():
            self.updateGeometry()


class _StripScrollArea(QScrollArea):
    """Fixed-height horizontal strip whose size-hint reports that fixed height.

    Stock ``QScrollArea`` ignores its fixed height in ``sizeHint``, so the
    grow-to-content parent (which measures via child size-hints) would under-count
    the Similar strip and clip its last row. Reporting the row height keeps the
    measurement honest.
    """

    def __init__(self, row_height: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._row_height = row_height
        self.setFixedHeight(row_height)

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt override)
        return QSize(super().sizeHint().width(), self._row_height)


class _ClickableFrame(QFrame):
    """A QFrame that emits :attr:`clicked` on a mouse press.

    Used for the similar-strip poster (the whole card is a dive-in target).  An
    instance-level ``mousePressEvent`` assignment does NOT override Qt's virtual
    dispatch, so this must be a real subclass.
    """

    clicked = pyqtSignal()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.clicked.emit()
        super().mousePressEvent(event)


class _HoverPosterSlot(QFrame):
    """Static poster surface sized as the eventual embedded-player viewport.

    Clicking the poster emits :attr:`clicked`, which the card turns into an
    *enlarge poster* request (the same peek affordance as the details pane) —
    playback is owned by the dedicated Play button below the poster.  The full-res
    pixmap is retained (:attr:`_full_pix`) so the enlarged overlay shows the
    original, not the down-scaled slot image.  A real player can later replace
    :attr:`_img` without moving anything else.
    """

    clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("lightbox_poster")
        self.setFixedSize(_POSTER_W, _POSTER_H)
        self.setStyleSheet(_theme.LIGHTBOX_POSTER_SLOT)
        set_clickable(self)
        self.setToolTip("Enlarge poster")

        # The full-resolution pixmap most recently set (None on a placeholder) —
        # the enlarged-poster overlay shows this, not the scaled slot image.
        self._full_pix: QPixmap | None = None

        self._img = QLabel(self)
        self._img.setGeometry(0, 0, _POSTER_W, _POSTER_H)
        self._img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img.setWordWrap(True)
        self._img.setStyleSheet(_theme.LIGHTBOX_POSTER_PLACEHOLDER)
        # Let presses on the image fall through to the slot (enlarge affordance).
        self._img.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    # -- population ------------------------------------------------------- #
    def set_pixmap(self, pix: QPixmap) -> None:
        # Keep the full-res pixmap BEFORE scaling — it feeds the enlarged overlay.
        self._full_pix = pix
        scaled = pix.scaled(
            QSize(_POSTER_W, _POSTER_H),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._img.setPixmap(scaled)
        self._img.setText("")

    def set_placeholder(self, text: str) -> None:
        self._full_pix = None
        self._img.setPixmap(QPixmap())
        self._img.setText(text)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.clicked.emit()
        super().mousePressEvent(event)


class _LightboxCard(QFrame):
    """The lightbox content card (header + hero + sections + footer)."""

    # User intents relayed up to the overlay (which attaches the current id).
    back_clicked        = pyqtSignal()
    close_clicked       = pyqtSignal()
    explore_clicked     = pyqtSignal()   # open the Explore trail-map (seeded with the nav trail)
    breadcrumb_crumb_clicked = pyqtSignal(str)  # channel_id — breadcrumb navigation
    play_clicked        = pyqtSignal()
    queue_clicked       = pyqtSignal()
    favorite_clicked    = pyqtSignal()
    hide_clicked        = pyqtSignal()
    rating_clicked      = pyqtSignal(int)   # +1 like / -1 dislike
    suppression_toggled = pyqtSignal(bool)  # Not-Interested on/off
    dive_requested      = pyqtSignal(str)   # channel_id (Other Version OR similar card)
    poster_expand_requested = pyqtSignal(QPixmap)  # enlarge the main poster (peek)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("lightbox_card")
        self.setStyleSheet(_theme.LIGHTBOX_CARD)
        # Width is driven responsively by the overlay (see ``apply_overlay_size``);
        # this is only the pre-first-resize default so the card never renders at
        # its bare size-hint width. Height is Maximum so it can grow to content up
        # to the overlay's 0.9×window cap (grow-to-content, scroll only on overflow).
        self.setFixedWidth(CARD_MAX_W)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Maximum)

        # url → poster labels awaiting an async image (main poster + strip cards).
        self._poster_targets: dict[str, list[QLabel]] = {}
        self.main_poster_url: str | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._build_header(outer)
        self._build_body(outer)
        self._build_footer(outer)

    # ------------------------------------------------------------------ #
    # Construction                                                         #
    # ------------------------------------------------------------------ #

    def _build_header(self, outer: QVBoxLayout) -> None:
        bar = QWidget()
        bar.setStyleSheet(_theme.LIGHTBOX_HEADER_BAR)
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 10, 12, 10)
        row.setSpacing(10)

        self._back_btn = QPushButton(f"{_icons.nav_prev_icon} Back")
        self._back_btn.setFlat(True)
        self._back_btn.setStyleSheet(_theme.LIGHTBOX_BACK_BTN)
        self._back_btn.setToolTip("Back to the previous title (Backspace)")
        self._back_btn.clicked.connect(self.back_clicked)
        self._back_btn.hide()
        row.addWidget(self._back_btn)

        self._title_lbl = QLabel()
        self._title_lbl.setStyleSheet(_theme.LIGHTBOX_TITLE)
        self._title_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        row.addWidget(self._title_lbl, 1)

        self._counter_lbl = QLabel()
        self._counter_lbl.setStyleSheet(_theme.LIGHTBOX_COUNTER)
        row.addWidget(self._counter_lbl)

        # Explore — opens the cascading-columns trail-map seeded with this dive path
        # (contextual lateral adjacency; distinct from the global ✨ Discover).
        self._explore_btn = QPushButton(f"{_icons.explore_icon} Explore")
        self._explore_btn.setFlat(True)
        self._explore_btn.setStyleSheet(_theme.LIGHTBOX_ACTION_BTN)
        self._explore_btn.setToolTip(
            "Explore — walk the adjacency trail of everything you've dived through"
        )
        self._explore_btn.clicked.connect(self.explore_clicked)
        row.addWidget(self._explore_btn)

        close_btn = QPushButton(_icons.close_icon)
        close_btn.setFlat(True)
        close_btn.setFixedSize(24, 24)
        close_btn.setStyleSheet(_theme.LIGHTBOX_CLOSE_BTN)
        close_btn.setToolTip("Close preview (Esc)")
        close_btn.clicked.connect(self.close_clicked)
        row.addWidget(close_btn)

        outer.addWidget(bar)

        # Breadcrumb trail — shows the dive path when in a rabbit hole
        self._breadcrumb = LightboxBreadcrumb()
        self._breadcrumb.crumb_clicked.connect(self._on_breadcrumb_clicked)
        self._breadcrumb.explore_ellipsis_clicked.connect(self.explore_clicked)
        outer.addWidget(self._breadcrumb)

    def _build_body(self, outer: QVBoxLayout) -> None:
        scroll = _GrowScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Grow-to-content: the scroll area reports its inner content's size-hint as
        # its own, so the card (Fixed/Maximum) expands to show every section. The
        # vertical scrollbar then appears ONLY when content exceeds the height cap.
        scroll.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        scroll.setStyleSheet(_theme.BG_TRANSPARENT)
        self._body_scroll = scroll

        content = QWidget()
        content.setStyleSheet(_theme.BG_TRANSPARENT)
        body = QVBoxLayout(content)
        body.setContentsMargins(24, 14, 24, 14)
        body.setSpacing(2)

        # Other Versions is built INSIDE the hero (upper-right column) — it is no
        # longer a wasteful full-width block below the hero (that repeated the
        # identical title/year/source N×). See ``_build_versions_column``.
        self._build_hero(body)
        self._build_overview(body)
        self._build_cast(body)
        self._build_similar_strip(body)
        body.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

    def _build_hero(self, body: QVBoxLayout) -> None:
        hero = QHBoxLayout()
        hero.setSpacing(22)
        hero.setContentsMargins(0, 0, 0, 0)

        # -- left: poster + primary Play --
        left = QVBoxLayout()
        left.setSpacing(6)
        self._poster = _HoverPosterSlot()
        # Poster click enlarges the poster (peek) — NOT play; the dedicated Play
        # button below owns playback.  A placeholder (no pixmap) click is a no-op.
        self._poster.clicked.connect(self._on_poster_clicked)
        left.addWidget(self._poster, 0, Qt.AlignmentFlag.AlignHCenter)

        self._play_btn = QPushButton(f"{_icons.play_icon} Play")
        self._play_btn.setStyleSheet(_theme.LIGHTBOX_PLAY_PRIMARY)
        self._play_btn.setToolTip("Play this title")
        self._play_btn.clicked.connect(self.play_clicked)
        left.addWidget(self._play_btn)

        left.addStretch()

        left_w = QWidget()
        left_w.setLayout(left)
        left_w.setFixedWidth(_POSTER_W)
        hero.addWidget(left_w, 0)

        # -- right column --
        right = QVBoxLayout()
        right.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_row.setContentsMargins(0, 0, 0, 0)
        self._heading_lbl = QLabel()
        self._heading_lbl.setStyleSheet(_theme.LIGHTBOX_HEADING)
        self._heading_lbl.setWordWrap(True)
        title_row.addWidget(self._heading_lbl, 0)
        self._year_lbl = QLabel()
        self._year_lbl.setStyleSheet(_theme.LIGHTBOX_META)
        title_row.addWidget(self._year_lbl, 0, Qt.AlignmentFlag.AlignBottom)
        title_row.addStretch()
        right.addLayout(title_row)

        # Meta line — rebuilt per populate (rating · runtime · type · ×N versions).
        self._meta_row_w = QWidget()
        self._meta_row = QHBoxLayout(self._meta_row_w)
        self._meta_row.setContentsMargins(0, 4, 0, 0)
        self._meta_row.setSpacing(8)
        right.addWidget(self._meta_row_w)

        # Source attribution + active/live dot.
        src_row = QHBoxLayout()
        src_row.setContentsMargins(0, 6, 0, 0)
        src_row.setSpacing(6)
        self._source_dot = QLabel(_icons.status_dot_icon)
        src_row.addWidget(self._source_dot)
        self._source_lbl = QLabel()
        self._source_lbl.setStyleSheet(_theme.LIGHTBOX_SOURCE)
        src_row.addWidget(self._source_lbl)
        src_row.addStretch()
        self._source_row_w = QWidget()
        self._source_row_w.setLayout(src_row)
        right.addWidget(self._source_row_w)

        # Genre chips — DISPLAY ONLY (not clickable-to-Recipe yet).
        self._genres_w = QWidget()
        self._genres_flow = FlowLayout(self._genres_w, spacing=6)
        right.addWidget(self._genres_w)

        # Rating cluster (Like / Not-Interested / Dislike) — checkable, colourblind
        # safe: the distinct glyph carries state, the checked fill is reinforcement.
        rate_row = QHBoxLayout()
        rate_row.setContentsMargins(0, 10, 0, 0)
        rate_row.setSpacing(6)
        self._like_btn = self._make_rating_btn(_icons.like_icon, "Like")
        self._like_btn.clicked.connect(lambda: self.rating_clicked.emit(1))
        rate_row.addWidget(self._like_btn)
        self._not_interested_btn = self._make_rating_btn(
            _icons.not_interested_icon, "Not Interested (suppress from recommendations)"
        )
        self._not_interested_btn.clicked.connect(
            lambda checked: self.suppression_toggled.emit(checked)
        )
        rate_row.addWidget(self._not_interested_btn)
        self._dislike_btn = self._make_rating_btn(_icons.dislike_icon, "Dislike")
        self._dislike_btn.clicked.connect(lambda: self.rating_clicked.emit(-1))
        rate_row.addWidget(self._dislike_btn)
        rate_row.addStretch()
        right.addLayout(rate_row)

        # Library actions.
        act_row = QHBoxLayout()
        act_row.setContentsMargins(0, 10, 0, 0)
        act_row.setSpacing(7)
        self._queue_btn = QPushButton()
        self._queue_btn.setStyleSheet(_theme.LIGHTBOX_ACTION_BTN)
        self._queue_btn.setToolTip("Add to / remove from Watch Later")
        self._queue_btn.clicked.connect(self.queue_clicked)
        act_row.addWidget(self._queue_btn)
        self._fav_btn = QPushButton()
        self._fav_btn.setStyleSheet(_theme.LIGHTBOX_ACTION_BTN)
        self._fav_btn.setToolTip("Add to / remove from Favorites")
        self._fav_btn.clicked.connect(self.favorite_clicked)
        act_row.addWidget(self._fav_btn)
        self._hide_btn = QPushButton(f"{_icons.hide_icon} Hide")
        self._hide_btn.setStyleSheet(_theme.LIGHTBOX_ACTION_BTN)
        self._hide_btn.setToolTip("Hide this channel from all views")
        self._hide_btn.clicked.connect(self.hide_clicked)
        act_row.addWidget(self._hide_btn)
        act_row.addStretch()
        right.addLayout(act_row)
        right.addStretch()

        right_w = QWidget()
        right_w.setLayout(right)
        hero.addWidget(right_w, 1)

        # -- far-right column: Other Versions (fills the hero's empty upper-right) --
        self._build_versions_column(hero)
        body.addLayout(hero)

    def _make_rating_btn(self, glyph: str, tip: str) -> QPushButton:
        btn = QPushButton(glyph)
        btn.setCheckable(True)
        btn.setFixedSize(38, 32)
        btn.setFlat(True)
        btn.setToolTip(tip)
        btn.setStyleSheet(_theme.RATING_BTN)
        return btn

    def _on_poster_clicked(self) -> None:
        """Enlarge the main poster (peek) on click — never play.

        Emits :attr:`poster_expand_requested` with the retained full-res pixmap so
        the overlay can feed the same enlarged-poster overlay the details pane uses.
        A placeholder (no pixmap yet) click is a graceful no-op.
        """
        pix = self._poster._full_pix
        if pix is not None and not pix.isNull():
            self.poster_expand_requested.emit(pix)

    def _build_overview(self, body: QVBoxLayout) -> None:
        self._overview_hdr = self._section_header("OVERVIEW")
        body.addWidget(self._overview_hdr)
        self._plot_lbl = QLabel()
        self._plot_lbl.setWordWrap(True)
        self._plot_lbl.setStyleSheet(_theme.LIGHTBOX_PLOT)
        body.addWidget(self._plot_lbl)

    def _build_cast(self, body: QVBoxLayout) -> None:
        self._cast_hdr = self._section_header("CAST & CREW")
        body.addWidget(self._cast_hdr)
        self._cast_lbl = QLabel()
        self._cast_lbl.setWordWrap(True)
        self._cast_lbl.setStyleSheet(_theme.LIGHTBOX_CAST)
        body.addWidget(self._cast_lbl)

    def _build_versions_column(self, hero: QHBoxLayout) -> None:
        """Other Versions — a vertical, scrollable single-column list in the hero's
        top-right.

        Each row is a friendly, clickable entry ("<source> · <quality/region>") rather
        than a cryptic 2-char token chip; the full "<name> · <source>" is the tooltip.
        The list scrolls once it exceeds the poster's height so it never grows the card.
        """
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        self._versions_hdr = self._section_header("OTHER VERSIONS")
        col.addWidget(self._versions_hdr)

        self._versions_list_w = QWidget()
        self._versions_list = QVBoxLayout(self._versions_list_w)
        self._versions_list.setContentsMargins(0, 0, 0, 0)
        self._versions_list.setSpacing(0)

        self._versions_scroll = QScrollArea()
        self._versions_scroll.setWidget(self._versions_list_w)
        self._versions_scroll.setWidgetResizable(True)
        self._versions_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._versions_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        # List height == the poster height (aligns the column with the poster); a
        # trailing stretch keeps rows top-packed when short, and it scrolls once the
        # version set exceeds the poster height so it never grows the card.
        self._versions_scroll.setFixedHeight(_POSTER_H)
        col.addWidget(self._versions_scroll)

        self._versions_col_w = QWidget()
        self._versions_col_w.setLayout(col)
        self._versions_col_w.setFixedWidth(_VERSIONS_COL_W)
        hero.addWidget(self._versions_col_w, 0, Qt.AlignmentFlag.AlignTop)

    def _build_similar_strip(self, body: QVBoxLayout) -> None:
        hdr_row = QHBoxLayout()
        hdr_row.setContentsMargins(0, 8, 0, 0)
        hdr_row.setSpacing(10)
        self._similar_hdr = self._section_header("SIMILAR TITLES")
        hdr_row.addWidget(self._similar_hdr)
        hdr_row.addStretch()
        self._similar_hdr_row_w = QWidget()
        self._similar_hdr_row_w.setLayout(hdr_row)
        body.addWidget(self._similar_hdr_row_w)

        # Poster (174) + 2-line name + badge meta line + state-glyph line + row
        # margins — sized so the full mini card shows and only the horizontal
        # scrollbar ever appears (the fixed height is reported in sizeHint so the
        # grow-to-content parent counts it).
        self._strip_scroll = _StripScrollArea(_SIM_H + 88)
        self._strip_scroll.setWidgetResizable(True)
        self._strip_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._strip_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._strip_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._strip_scroll.setStyleSheet(_theme.BG_TRANSPARENT)
        self._strip_w = QWidget()
        self._strip_w.setStyleSheet(_theme.BG_TRANSPARENT)
        self._strip_layout = QHBoxLayout(self._strip_w)
        self._strip_layout.setContentsMargins(0, 6, 0, 6)
        self._strip_layout.setSpacing(12)
        self._strip_layout.addStretch()
        self._strip_scroll.setWidget(self._strip_w)
        body.addWidget(self._strip_scroll)

    def _build_footer(self, outer: QVBoxLayout) -> None:
        bar = QWidget()
        bar.setStyleSheet(_theme.LIGHTBOX_FOOTER_BAR)
        row = QHBoxLayout(bar)
        row.setContentsMargins(20, 10, 20, 10)
        row.setSpacing(18)
        hints = [
            (f"{_icons.nav_prev_icon} {_icons.nav_next_icon}", "browse similar"),
            (_icons.lightbox_icon, "dive in"),
            ("Backspace", "back"),
            ("Esc", "close"),
        ]
        for key, text in hints:
            kbd = QLabel(key)
            kbd.setStyleSheet(_theme.LIGHTBOX_KBD)
            row.addWidget(kbd)
            lbl = QLabel(text)
            lbl.setStyleSheet(_theme.LIGHTBOX_FOOTER_HINT)
            row.addWidget(lbl)
        row.addStretch()
        outer.addWidget(bar)

    def _section_header(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(_theme.LIGHTBOX_SECTION_HDR)
        # Top margin gives each section the mockup's breathing gap (body spacing
        # adds the rest); the small bottom margin keeps the header tight to its
        # own content.
        lbl.setContentsMargins(0, 8, 0, 2)
        return lbl

    # ------------------------------------------------------------------ #
    # Responsive sizing (single seam — driven by the overlay)             #
    # ------------------------------------------------------------------ #

    def apply_overlay_size(self, overlay_w: int, overlay_h: int) -> None:
        """Size the card to the overlay: responsive width, grow-to-content height.

        Width is a generous fraction of the window, clamped to
        ``[CARD_MIN_W, CARD_MAX_W]`` for readability (so it scales up on a large
        window but never collapses). Height is capped at 0.9× the window; the card's
        Maximum vertical policy plus the body's ``AdjustToContents`` scroll area let
        it grow to its natural content height below that cap, scrolling only when the
        content genuinely exceeds it. One seam so the overlay's ``resizeEvent`` and
        any offscreen render share exactly the same maths.
        """
        card_w = min(CARD_MAX_W, max(CARD_MIN_W, int(overlay_w * 0.82)))
        self.setFixedWidth(card_w)
        self.setMaximumHeight(max(420, int(overlay_h * 0.9)))

    # ------------------------------------------------------------------ #
    # Header / navigation state (driven by the overlay)                    #
    # ------------------------------------------------------------------ #

    def set_header(self, origin_title: str) -> None:
        self._title_lbl.setText(f"Similar to:  {origin_title}")

    def set_counter(self, text: str) -> None:
        self._counter_lbl.setText(text)

    def set_back_visible(self, visible: bool) -> None:
        self._back_btn.setVisible(visible)

    def update_breadcrumb(
        self,
        origin_title: str,
        origin_ids: list[str],
        nav_stack: list[str],
        current_id: str,
        db: "Database",
    ) -> None:
        """Update the breadcrumb trail with the current dive path.

        Called whenever the lightbox loads a new channel or dives deeper.
        """
        self._breadcrumb.update_trail(origin_title, origin_ids, nav_stack, current_id, db)

    def _on_breadcrumb_clicked(self, channel_id: str) -> None:
        """Handle breadcrumb crumb click — relay as a signal for the overlay."""
        self.breadcrumb_crumb_clicked.emit(channel_id)

    # ------------------------------------------------------------------ #
    # Populate                                                             #
    # ------------------------------------------------------------------ #

    def reset_loading(self) -> None:
        """Reset every field to the between-titles loading state."""
        self._poster_targets.clear()
        self.main_poster_url = None
        self._heading_lbl.setText("Loading…")
        self._year_lbl.clear()
        self._clear_layout(self._meta_row)
        self._source_row_w.hide()
        self._clear_flow(self._genres_flow)
        self._genres_w.hide()
        self._overview_hdr.hide()
        self._plot_lbl.hide()
        self._plot_lbl.clear()
        self._cast_hdr.hide()
        self._cast_lbl.hide()
        self._cast_lbl.clear()
        self._versions_col_w.hide()
        self._clear_layout(self._versions_list)
        self._similar_hdr_row_w.hide()
        self._strip_scroll.hide()
        self._clear_strip()
        self._poster.set_placeholder("…")
        self._like_btn.setChecked(False)
        self._dislike_btn.setChecked(False)
        self._not_interested_btn.setChecked(False)
        self._queue_btn.setText(f"{_icons.queue_icon} Watch Later")
        self._fav_btn.setText(f"{_icons.unfavorite_icon} Favorite")

    def show_error(self, message: str) -> None:
        """Reset to the loading skeleton and show a single error heading."""
        self.reset_loading()
        self._heading_lbl.setText(message)
        self._poster.set_placeholder("")

    def populate(self, data: dict) -> None:
        """Fill the card from a plain data dict (built off-thread by the overlay).

        Poster images are NOT loaded here — the overlay reads
        :meth:`pending_poster_urls` and pushes pixmaps back via
        :meth:`set_poster_pixmap` (QPixmap is main-thread only).
        """
        self._heading_lbl.setText(data.get("name") or "Unknown")
        year = data.get("year")
        self._year_lbl.setText(f"({year})" if year else "")

        self._populate_meta(data)
        self._populate_source(data)
        self._populate_genres(data.get("genres") or [])
        self._populate_rating(data)
        self._populate_actions(data)
        self._populate_overview(data.get("plot") or "")
        self._populate_cast(data.get("cast") or "")
        self._populate_versions(data.get("versions") or [])
        self._populate_similar(data.get("similar") or [])
        self._prepare_main_poster(data.get("poster_url"))

    def _populate_meta(self, data: dict) -> None:
        self._clear_layout(self._meta_row)
        parts: list[QLabel] = []
        rating = data.get("rating")
        if rating:
            star = QLabel(f"{_icons.rating_star_icon} {rating}")
            star.setStyleSheet(_theme.LIGHTBOX_STAR)
            parts.append(star)
        runtime = _fmt_runtime(data.get("runtime"))
        if runtime:
            parts.append(self._meta_text(runtime))
        mt = data.get("media_type") or ""
        icon = _MEDIA_TYPE_ICON.get(mt)
        if icon:
            parts.append(self._meta_text(f"{icon} {mt.title()}"))
        count = int(data.get("version_count") or 0)
        first = True
        for w in parts:
            if not first:
                self._meta_row.addWidget(self._meta_sep())
            self._meta_row.addWidget(w)
            first = False
        if count > 0:
            if not first:
                self._meta_row.addWidget(self._meta_sep())
            badge = QLabel(f"{_icons.variant_count_icon}{count} versions")
            badge.setStyleSheet(_theme.LIGHTBOX_VERSION_BADGE)
            badge.setToolTip(f"{count} other version(s) — see Other Versions below")
            self._meta_row.addWidget(badge)
        self._meta_row.addStretch()

    def _meta_text(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(_theme.LIGHTBOX_META)
        return lbl

    def _meta_sep(self) -> QLabel:
        return self._meta_text("·")

    def _populate_source(self, data: dict) -> None:
        name = data.get("provider_name")
        if not name:
            self._source_row_w.hide()
            return
        active = bool(data.get("provider_active", True))
        dot_color = _theme.COLOR_OK if active else _theme.COLOR_MUTED
        self._source_dot.setStyleSheet(f"color: {dot_color}; font-size: {_theme.FONT_SM};")
        self._source_lbl.setText(f"Source: {name}")
        self._source_row_w.show()

    def _populate_genres(self, genres: list[str]) -> None:
        self._clear_flow(self._genres_flow)
        shown = 0
        for g in genres:
            g = (g or "").strip()
            if not g:
                continue
            chip = QLabel(g)
            chip.setStyleSheet(_theme.LIGHTBOX_GENRE_CHIP)
            self._genres_flow.addWidget(chip)
            shown += 1
        self._genres_w.setVisible(shown > 0)

    def _populate_rating(self, data: dict) -> None:
        rating = int(data.get("user_rating") or 0)
        self._like_btn.setChecked(rating > 0)
        self._dislike_btn.setChecked(rating < 0)
        self._not_interested_btn.setChecked(bool(data.get("is_suppressed")))

    def _populate_actions(self, data: dict) -> None:
        in_queue = bool(data.get("in_queue"))
        self._queue_btn.setText(
            f"{_icons.queue_icon} In Watch Later" if in_queue
            else f"{_icons.queue_icon} Watch Later"
        )
        is_fav = bool(data.get("is_favorite"))
        self._fav_btn.setText(
            f"{_icons.favorite_icon} Favorited" if is_fav
            else f"{_icons.unfavorite_icon} Favorite"
        )

    def _populate_overview(self, plot: str) -> None:
        has = bool(plot.strip())
        self._overview_hdr.setVisible(has)
        self._plot_lbl.setVisible(has)
        self._plot_lbl.setText(plot)

    def _populate_cast(self, cast: str) -> None:
        has = bool(cast.strip())
        self._cast_hdr.setVisible(has)
        self._cast_lbl.setVisible(has)
        self._cast_lbl.setText(cast)

    def _populate_versions(self, versions: list[dict]) -> None:
        self._clear_layout(self._versions_list)
        if not versions:
            self._versions_col_w.hide()
            return
        self._versions_hdr.setText(f"OTHER VERSIONS ({len(versions)})")
        for v in versions:
            self._versions_list.addWidget(self._make_version_row(v))
        self._versions_list.addStretch()  # keep rows top-packed when short of the cap
        self._versions_col_w.show()

    def _make_version_row(self, v: dict) -> QPushButton:
        """A full-width, friendly Other-Versions row: "<source> · <quality/region>".

        The visible label is the human-readable source name plus the distinguishing
        quality/region token (never a bare 2-char code), prefixed by the source's icon
        glyph when the provider has one; the full "<name> · <source>" is the tooltip.
        A runtime provider colour tints the left border as a source badge; the label
        text is always present, so the row never distinguishes by colour alone.
        """
        tag = (v.get("tag") or "").strip()
        name = v.get("name") or "?"
        src = (v.get("provider_name") or "").strip()
        icon = (v.get("provider_icon") or "").strip()
        color = (v.get("provider_color") or "").strip()

        label = " · ".join(p for p in (src or name, tag) if p)
        visible = f"{icon}  {label}".strip() if icon else label
        row = QPushButton(visible)
        row.setFlat(True)
        row.setStyleSheet(_theme.lightbox_version_row(color))
        detail = f"{name} · {src}" if src else name
        row.setToolTip(detail)  # QPushButton auto-qualifies for the hand cursor
        cid = v.get("id")
        row.clicked.connect(lambda _=False, c=cid: self.dive_requested.emit(c))
        return row

    def _populate_similar(self, similar: list[dict]) -> None:
        self._clear_strip()
        if not similar:
            self._similar_hdr_row_w.hide()
            self._strip_scroll.hide()
            return
        self._similar_hdr.setText(f"SIMILAR TITLES ({len(similar)})")
        for item in similar:
            card = self._make_sim_card(item)
            self._strip_layout.insertWidget(self._strip_layout.count() - 1, card)
        self._similar_hdr_row_w.show()
        self._strip_scroll.show()

    def _make_sim_card(self, item: dict) -> QWidget:
        cid = item.get("id")
        name = item.get("name") or "?"

        card = QWidget()
        col = QVBoxLayout(card)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)

        poster_wrap = _ClickableFrame()
        poster_wrap.setObjectName("lightbox_sim_poster")
        poster_wrap.setFixedSize(_SIM_W, _SIM_H)
        poster_wrap.setStyleSheet(_theme.LIGHTBOX_SIM_POSTER)
        set_clickable(poster_wrap)
        poster_wrap.setToolTip(f"Preview in lightbox: {name}")
        # The whole poster is the dive-in target — no separate ⤢ button (it was
        # redundant clutter on every card; a click anywhere on the poster dives in).
        poster_wrap.clicked.connect(lambda c=cid: self.dive_requested.emit(c))

        img = QLabel(poster_wrap)
        img.setGeometry(0, 0, _SIM_W, _SIM_H)
        img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img.setWordWrap(True)
        img.setText(name)
        # Presses on the poster fall through to the clickable frame (dive-in).
        img.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        col.addWidget(poster_wrap)

        name_lbl = QLabel(name)
        name_lbl.setStyleSheet(_theme.LIGHTBOX_SIM_NAME)
        name_lbl.setWordWrap(True)
        name_lbl.setFixedWidth(_SIM_W)
        col.addWidget(name_lbl)

        # Badge cluster — language/rating + state glyphs, mirroring the details-pane
        # Similar rows (one shared builder for every strip card).
        col.addWidget(self._make_sim_badges(item))

        url = item.get("poster_url")
        if url:
            self._poster_targets.setdefault(url, []).append(img)
        return card

    def _make_sim_badges(self, item: dict) -> QWidget:
        """Build a strip card's badge cluster (delegates to the shared renderer).

        The badge cluster — a meta line (language/region + ★rating, year on the
        right) above the active state glyphs (liked / in Watch Later / favorited /
        watched) — is built by the single shared :func:`sim_badges.make_sim_badges`
        so the lightbox strip and the Explore trail-map rows render badges
        identically (one badge renderer everywhere).  The strip fixes the cluster to
        the poster width so it aligns under the poster.
        """
        return make_sim_badges(item, width=_SIM_W)

    # ------------------------------------------------------------------ #
    # Poster image seam (overlay owns the ImageCache)                      #
    # ------------------------------------------------------------------ #

    def _prepare_main_poster(self, url: str | None) -> None:
        self.main_poster_url = url or None
        if url:
            self._poster.set_placeholder("")
            self._poster_targets.setdefault(url, [])  # marker; main handled specially
        else:
            self._poster.set_placeholder("No poster")

    def pending_poster_urls(self) -> list[str]:
        """URLs the overlay should load (main poster + strip cards), main first."""
        urls: list[str] = []
        if self.main_poster_url:
            urls.append(self.main_poster_url)
        for u in self._poster_targets:
            if u != self.main_poster_url:
                urls.append(u)
        return urls

    def set_poster_pixmap(self, url: str, pix: QPixmap) -> None:
        """Route a loaded pixmap to the main poster and/or any strip cards."""
        if url == self.main_poster_url:
            self._poster.set_pixmap(pix)
        for lbl in self._poster_targets.get(url, []):
            scaled = pix.scaled(
                QSize(_SIM_W, _SIM_H),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            lbl.setPixmap(scaled)
            lbl.setText("")

    # ------------------------------------------------------------------ #
    # Layout helpers                                                       #
    # ------------------------------------------------------------------ #

    def _clear_strip(self) -> None:
        # Keep the trailing stretch (index count-1); remove card widgets before it.
        while self._strip_layout.count() > 1:
            item = self._strip_layout.takeAt(0)
            if w := item.widget():
                w.deleteLater()

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if w := item.widget():
                w.deleteLater()

    @staticmethod
    def _clear_flow(flow) -> None:
        while flow.count():
            item = flow.takeAt(0)
            if item is not None and (w := item.widget()):
                w.deleteLater()
