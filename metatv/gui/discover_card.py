"""Discover view — content card widget and flow layout helper."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QContextMenuEvent, QPixmap
from PyQt6.QtWidgets import (
    QFrame, QGraphicsOpacityEffect, QLabel, QProgressBar, QVBoxLayout, QWidget,
)

from loguru import logger
from metatv.core.config import Config
from metatv.core.discovery_engine import ContentCard
from metatv.gui import cursor_affordance
from metatv.gui import theme as _theme
from metatv.gui import icons as _icons

if TYPE_CHECKING:
    from metatv.core.image_cache import ImageCache

_CARD_W = 120
_CARD_H = 220
_POSTER_H = 175

_ZOOM_MIN = 0.6
_ZOOM_MAX = 1.8


class CardMetrics(NamedTuple):
    """Zoomed card dimensions derived from the base constants."""

    card_w: int
    card_h: int
    poster_h: int


def card_metrics(zoom: float) -> CardMetrics:
    """Return card dimensions for the given zoom factor.

    The zoom is clamped to [0.6, 1.8] before scaling.  All three values are
    rounded to the nearest pixel so geometry stays crisp.

    Args:
        zoom: Zoom factor requested by the user (e.g. from ``config.discover_zoom``).

    Returns:
        A :class:`CardMetrics` with integer pixel dimensions.
    """
    z = max(_ZOOM_MIN, min(_ZOOM_MAX, zoom))
    return CardMetrics(
        card_w=round(_CARD_W * z),
        card_h=round(_CARD_H * z),
        poster_h=round(_POSTER_H * z),
    )


class UniformCardGrid:
    """A virtualized grid for uniformly-sized cards.

    A measuring flow layout sizes each widget to place it, so every card has to
    EXIST before the layout knows where anything goes — which is why the browse
    grid built a widget per result and kept it forever. At 84 KB and 0.26 ms per
    card (measured) a 20,000-result recipe "Show all" is 1.6 GB and 5.2 s, and
    the O(N) scroll sweep over every card ever created grows with it.

    Every card is ``setFixedSize(card_metrics(zoom))`` — they are all the SAME
    size. So the position of card *i* is arithmetic, not measurement:

        cols = (width + spacing) // (card_w + spacing)
        row, col = divmod(i, cols)

    which means the grid can size itself for N cards while materializing only
    the ones on screen. Memory and per-scroll cost become a function of the
    VIEWPORT, not the result count — so no cap is needed and none is imposed.

    Widgets outside the window are destroyed and rebuilt on the way back. That
    is safe because a card holds no state a user can edit; everything it shows
    comes from its ``ContentCard`` and the shared image cache, and the cache is
    what makes a rebuild cheap.
    """

    #: Rows of cards kept alive above and below the viewport. Two screens of
    #: overscan makes normal scrolling never see a gap, and bounds the live set
    #: at roughly three viewports' worth regardless of how many results exist.
    OVERSCAN_ROWS = 2

    def __init__(self, container: "QWidget", *, item_w: int, item_h: int,
                 spacing: int, factory) -> None:
        """
        Args:
            container: The widget cards are parented to.
            item_w: Fixed card width in px.
            item_h: Fixed card height in px.
            spacing: Gap between cards in px.
            factory: ``factory(card) -> QWidget``, called when a card scrolls
                into the window. Called again if it scrolls back.
        """
        self._container = container
        self._item_w = max(1, int(item_w))
        self._item_h = max(1, int(item_h))
        self._spacing = int(spacing)
        self._factory = factory
        self._cards: list = []
        self._live: dict[int, "QWidget"] = {}
        self._width: int = 0

    # -- geometry, from the index alone ---------------------------------- #

    def columns(self, available_width: int) -> int:
        step = self._item_w + self._spacing
        return max(1, (int(available_width) + self._spacing) // step)

    def rect_for(self, index: int, available_width: int) -> QRect:
        cols = self.columns(available_width)
        row, col = divmod(index, cols)
        return QRect(col * (self._item_w + self._spacing),
                     row * (self._item_h + self._spacing),
                     self._item_w, self._item_h)

    def total_height(self, available_width: int) -> int:
        if not self._cards:
            return 0
        cols = self.columns(available_width)
        rows = (len(self._cards) + cols - 1) // cols
        return rows * (self._item_h + self._spacing) - self._spacing

    def visible_range(self, scroll_y: int, viewport_h: int,
                      available_width: int) -> tuple[int, int]:
        """The half-open index range to keep alive, overscan included."""
        if not self._cards:
            return (0, 0)
        cols = self.columns(available_width)
        step = self._item_h + self._spacing
        first_row = max(0, int(scroll_y) // step - self.OVERSCAN_ROWS)
        last_row = (int(scroll_y) + max(0, int(viewport_h))) // step + self.OVERSCAN_ROWS
        return (first_row * cols,
                min(len(self._cards), (last_row + 1) * cols))

    # -- contents --------------------------------------------------------- #

    def set_cards(self, cards: list) -> None:
        """Replace every card. Live widgets are destroyed."""
        self.clear()
        self._cards = list(cards)

    def append_cards(self, cards: list) -> None:
        """Add a page without disturbing what is already on screen."""
        self._cards.extend(cards)

    def count(self) -> int:
        return len(self._cards)

    def live_widgets(self) -> list:
        """The materialized widgets, in index order."""
        return [self._live[i] for i in sorted(self._live)]

    def clear(self) -> None:
        for w in self._live.values():
            w.setParent(None)
            w.deleteLater()
        self._live.clear()
        self._cards = []

    # -- the window ------------------------------------------------------- #

    def sync(self, scroll_y: int, viewport_h: int, available_width: int) -> None:
        """Materialize the window, destroy what left it, position what stays."""
        self._width = int(available_width)
        first, last = self.visible_range(scroll_y, viewport_h, available_width)
        wanted = range(first, last)

        for i in [i for i in self._live if i < first or i >= last]:
            w = self._live.pop(i)
            w.setParent(None)
            w.deleteLater()

        for i in wanted:
            w = self._live.get(i)
            if w is None:
                w = self._factory(self._cards[i])
                w.setParent(self._container)
                w.show()
                self._live[i] = w
            w.setGeometry(self.rect_for(i, available_width))


class _ContentCard(QWidget):
    """Poster card with shimmer, status overlay, and title.

    The card dimensions are derived from ``card_metrics(config.discover_zoom)``
    so cards scale with the user's zoom preference.  Pass a ``Config`` instance
    (already a constructor arg) and the zoom is read from there automatically.
    """

    clicked              = pyqtSignal(str)          # channel_id
    doubleClicked        = pyqtSignal(str)
    middleClicked        = pyqtSignal(str)          # channel_id — configured middle-click play
    contextMenuRequested = pyqtSignal(str, int, int)

    def __init__(self, card: ContentCard, image_cache: "ImageCache",
                 config: Config, parent=None) -> None:
        super().__init__(parent)
        self._card = card
        self._image_cache = image_cache
        self._config = config
        self._image_requested = False

        # Derive all geometry from the zoom-aware metrics so card + shelf stay in sync.
        m = card_metrics(config.discover_zoom)
        cw, ch, ph = m.card_w, m.card_h, m.poster_h
        z = max(_ZOOM_MIN, min(_ZOOM_MAX, config.discover_zoom))

        self.setFixedSize(cw, ch)
        cursor_affordance.set_clickable(self)

        vl = QVBoxLayout(self)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(2)

        # Poster frame
        self._poster_frame = QFrame()
        self._poster_frame.setFixedSize(cw, ph)
        color = _theme.BACKDROP_TINTS[hash(card.channel_id) % len(_theme.BACKDROP_TINTS)]
        self._poster_frame.setStyleSheet(
            f"background: {color}; border-radius: 4px;"
        )

        # Poster image label (fills the frame)
        self._poster_lbl = QLabel(self._poster_frame)
        self._poster_lbl.setGeometry(0, 0, cw, ph)
        self._poster_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._poster_lbl.setStyleSheet("background: transparent; border-radius: 4px;")

        # Remember the zoomed poster dimensions for image-loaded crop math.
        self._zoomed_cw = cw
        self._zoomed_ph = ph

        # Shimmer animation — created here but only STARTED in request_image()
        # so collapsed-shelf cards don't burn CPU with hundreds of idle animations.
        if card.thumbnail_url:
            effect = QGraphicsOpacityEffect(self._poster_lbl)
            self._poster_lbl.setGraphicsEffect(effect)
            self._shimmer = QPropertyAnimation(effect, b"opacity", self)
            self._shimmer.setDuration(900)
            self._shimmer.setStartValue(0.35)
            self._shimmer.setEndValue(0.85)
            self._shimmer.setEasingCurve(QEasingCurve.Type.InOutSine)
            self._shimmer.setLoopCount(-1)
        else:
            self._shimmer = None

        # Placeholder media-type icon (centered) — font size scales with zoom.
        icon = config.movie_icon if card.media_type == "movie" else config.series_icon
        self._icon_lbl = QLabel(icon, self._poster_frame)
        self._icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_h = round(40 * z)
        self._icon_lbl.setGeometry(0, ph // 2 - icon_h // 2, cw, icon_h)
        self._icon_lbl.setFont(_theme.zoomed_font(_theme.FONT_ICON_LG, z))
        self._icon_lbl.setStyleSheet("background: transparent;")

        # Rating badge (bottom-left overlay) — magic numbers scaled by zoom.
        if card.rating:
            rating_lbl = QLabel(f"{config.rating_star_icon} {card.rating:.1f}", self._poster_frame)
            badge_y = ph - round(22 * z)
            badge_h = round(18 * z)
            badge_w = round(60 * z)
            rating_lbl.setGeometry(round(4 * z), badge_y, badge_w, badge_h)
            rating_lbl.setFont(_theme.zoomed_font(_theme.FONT_SM, z))
            _theme.style_fn(rating_lbl, lambda: f"background: {_theme.OVERLAY_BLACK_65}; color: {_theme.COLOR_GOLD};"
                " border-radius: 3px; padding: 1px 4px;")

        # Category badge (bottom-right overlay) — provider's prefix label.
        if card.detected_prefix:
            cat_lbl = QLabel(card.detected_prefix, self._poster_frame)
            cat_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cat_lbl.setFont(_theme.zoomed_font(_theme.FONT_XS, z))
            _theme.style_fn(cat_lbl, lambda: f"background: {_theme.OVERLAY_BLACK_55}; color: {_theme.COLOR_ON_FILL_LIGHT};"
                " border-radius: 3px; padding: 1px 3px;")
            cat_lbl.adjustSize()
            cat_lbl.move(cw - cat_lbl.width() - round(4 * z), ph - round(22 * z))

        # Status overlay (top-right corner) — badges scale with zoom.
        badges = []
        if card.is_liked:
            badges.append(config.like_icon)
        if card.is_favorite:
            badges.append(config.favorite_icon)
        if card.in_queue:
            badges.append(config.queue_icon)
        if card.already_watched:
            badges.append(config.watched_icon)
        if badges:
            status_lbl = QLabel(" ".join(badges), self._poster_frame)
            status_lbl.setFont(_theme.zoomed_font(_theme.FONT_XS, z))
            _theme.style_fn(status_lbl, lambda: f"background: {_theme.OVERLAY_BLACK_60}; border-radius: 3px;"
                f" padding: 1px 3px; color: {_theme.COLOR_ON_FILL_LIGHT};")
            status_lbl.adjustSize()
            status_lbl.move(cw - status_lbl.width() - round(4 * z), round(4 * z))
            status_lbl.raise_()

        # Resume-progress bar — thin strip at the very bottom of the poster frame.
        # Shown only when the movie has been partially watched (not completed).
        # Already-watched cards use the ✓ badge above instead.
        if card.progress_fraction > 0.0 and not card.already_watched:
            bar_h = max(3, round(4 * z))
            progress_bar = QProgressBar(self._poster_frame)
            progress_bar.setRange(0, 100)
            progress_bar.setValue(round(card.progress_fraction * 100))
            progress_bar.setFixedSize(cw, bar_h)
            progress_bar.setTextVisible(False)
            progress_bar.setGeometry(0, ph - bar_h, cw, bar_h)
            progress_bar.setToolTip(f"Resume at {round(card.progress_fraction * 100)}% watched")
            _theme.style_fn(progress_bar, lambda: f"QProgressBar {{ background: {_theme.OVERLAY_BLACK_60}; border: none;"
                f" border-radius: 0px; }}"
                f"QProgressBar::chunk {{ background: {_theme.COLOR_ACCENT_ORANGE};"
                f" border-radius: 0px; }}")
            progress_bar.raise_()

        # Variant-count badge (bottom-left overlay) — shown only when variant_count > 1.
        # Signals that this card represents multiple source/quality copies of the same
        # production.  Uses the ×N glyph (e.g. "×3") with VARIANT_BADGE styling.
        if card.variant_count > 1:
            vc_lbl = QLabel(
                f"{_icons.variant_count_icon}{card.variant_count}",
                self._poster_frame,
            )
            vc_lbl.setFont(_theme.zoomed_font(_theme.FONT_SM, z))
            _theme.style(vc_lbl, "VARIANT_BADGE")
            vc_lbl.adjustSize()
            # Position: bottom-left, below the rating badge (if any).
            # If rating is present, move 2 rows up from the bottom; otherwise 1 row.
            _badge_row = 2 if card.rating else 1
            vc_lbl.move(
                round(4 * z),
                ph - round(_badge_row * 22 * z),
            )
            vc_lbl.setToolTip(
                f"{card.variant_count} source / quality variants of this title available"
            )
            vc_lbl.raise_()

        vl.addWidget(self._poster_frame)

        # Title label (2 lines, word-wrapped) — width and font scale with zoom.
        title_h = ch - ph - 4  # card_h − poster_h − spacing; ≈38px at 1.0×
        self._title_lbl = QLabel(card.title)
        self._title_lbl.setFixedWidth(cw)
        self._title_lbl.setFixedHeight(max(24, title_h))
        self._title_lbl.setWordWrap(True)
        self._title_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._title_lbl.setFont(_theme.zoomed_font(_theme.FONT_MD, z))
        _theme.style_fn(self._title_lbl, lambda: f"color: {_theme.COLOR_TEXT_2};")
        self._title_lbl.setToolTip(card.title)
        vl.addWidget(self._title_lbl)

    def request_image(self) -> None:
        """Request poster image load — idempotent, only fires once.

        Also starts the shimmer and connects the image_loaded / image_failed
        signals here (not in __init__) so collapsed-shelf cards incur zero
        overhead.  Both signals are disconnected when either one fires.
        """
        if not self._image_requested and self._card.thumbnail_url:
            self._image_requested = True
            if self._shimmer:
                self._shimmer.start()
            # subscribe(), NOT the image_loaded broadcast.
            #
            # A shelf builds one card per title, and every card waiting for a
            # poster used to connect to the shared signal — so each arriving
            # image invoked the slot on ALL waiting cards and all but one
            # returned immediately on a url mismatch. Filling a screen of
            # posters cost N² dispatches: 157 ms of pure signal plumbing at
            # 800 cards, before decoding anything. That is the choppy scroll
            # into unloaded posters; scrolling back over loaded ones was
            # smooth because a card left the fan-out once its image arrived.
            self._image_cache.subscribe(
                self._card.thumbnail_url,
                self._on_image_loaded,
                self._on_image_failed,
            )
            self._image_cache.get_image_async(self._card.thumbnail_url)

    def _stop_shimmer(self) -> None:
        """Stop the shimmer animation and reset the poster opacity to 1.0."""
        if self._shimmer:
            self._shimmer.stop()
            effect = self._poster_lbl.graphicsEffect()
            if effect:
                effect.setOpacity(1.0)

    def _on_image_loaded(self, url: str, pixmap: QPixmap) -> None:
        # No disconnect and no url guard needed: subscribe() routes this url to
        # this card only, and drops the subscription once it has fired.
        self._stop_shimmer()
        # Crop to the zoomed card dimensions (stored at construction time so we
        # don't re-derive from config here — the card is already the right size).
        cw, ph = self._zoomed_cw, self._zoomed_ph
        scaled = pixmap.scaled(
            cw, ph,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = (scaled.width() - cw) // 2
        y = (scaled.height() - ph) // 2
        cropped = scaled.copy(x, y, cw, ph)
        self._poster_lbl.setPixmap(cropped)
        self._icon_lbl.setVisible(False)

    def _on_image_failed(self, url: str, error: str) -> None:
        """Handle image-load failure: stop the shimmer and clean up connections.

        The placeholder icon remains visible (it is never hidden on failure),
        so the card shows a meaningful fallback rather than a blank shimmer.
        """
        logger.debug(f"Poster load failed for {url!r}: {error}")
        self._stop_shimmer()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._card.channel_id)
        elif event.button() == Qt.MouseButton.MiddleButton:
            self.middleClicked.emit(self._card.channel_id)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.doubleClicked.emit(self._card.channel_id)
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        self.contextMenuRequested.emit(
            self._card.channel_id, event.globalPos().x(), event.globalPos().y()
        )
        event.accept()
