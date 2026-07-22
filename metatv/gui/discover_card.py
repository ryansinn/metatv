"""Discover view — content card widget and flow layout helper."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QContextMenuEvent, QPixmap
from PyQt6.QtWidgets import (
    QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget,
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

_PLACEHOLDER_COLORS = _theme.BACKDROP_TINTS


class _FlowLayout:
    """Simple flow-layout helper — arranges widgets left-to-right, wrapping."""

    def __init__(self, container: QWidget, spacing: int = 8) -> None:
        self._container = container
        self._items: list[QWidget] = []
        self._spacing = spacing

    def add(self, widget: QWidget) -> None:
        widget.setParent(self._container)
        self._items.append(widget)

    def relayout(self, available_width: int) -> int:
        """Position all items within available_width. Returns total height."""
        x, y, row_h = 0, 0, 0
        sp = self._spacing
        for w in self._items:
            ww = w.sizeHint().width()
            wh = w.sizeHint().height()
            if x + ww > available_width and x > 0:
                x = 0
                y += row_h + sp
                row_h = 0
            w.setGeometry(QRect(x, y, ww, wh))
            x += ww + sp
            row_h = max(row_h, wh)
        return y + row_h if self._items else 0

    def clear(self) -> None:
        for w in self._items:
            w.deleteLater()
        self._items.clear()


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
        color = _PLACEHOLDER_COLORS[hash(card.channel_id) % len(_PLACEHOLDER_COLORS)]
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
            rating_lbl.setStyleSheet(
                f"background: {_theme.OVERLAY_BLACK_65}; color: {_theme.COLOR_GOLD};"
                " border-radius: 3px; padding: 1px 4px;"
            )

        # Category badge (bottom-right overlay) — provider's prefix label.
        if card.detected_prefix:
            cat_lbl = QLabel(card.detected_prefix, self._poster_frame)
            cat_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cat_lbl.setFont(_theme.zoomed_font(_theme.FONT_XS, z))
            cat_lbl.setStyleSheet(
                f"background: {_theme.OVERLAY_BLACK_55}; color: {_theme.COLOR_ACCENT_BLUE_LIGHT};"
                " border-radius: 3px; padding: 1px 3px;"
            )
            cat_lbl.adjustSize()
            cat_lbl.move(cw - cat_lbl.width() - round(4 * z), ph - round(22 * z))

        # Status overlay (top-right corner) — badges scale with zoom.
        badges = []
        if card.is_liked:        badges.append(config.like_icon)
        if card.is_favorite:     badges.append(config.favorite_icon)
        if card.in_queue:        badges.append(config.queue_icon)
        if card.already_watched: badges.append(config.watched_icon)
        if badges:
            status_lbl = QLabel(" ".join(badges), self._poster_frame)
            status_lbl.setFont(_theme.zoomed_font(_theme.FONT_XS, z))
            status_lbl.setStyleSheet(
                f"background: {_theme.OVERLAY_BLACK_60}; border-radius: 3px;"
                " padding: 1px 3px; color: white;"
            )
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
            progress_bar.setStyleSheet(
                f"QProgressBar {{ background: {_theme.OVERLAY_BLACK_60}; border: none;"
                f" border-radius: 0px; }}"
                f"QProgressBar::chunk {{ background: {_theme.COLOR_ACCENT_ORANGE};"
                f" border-radius: 0px; }}"
            )
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
            vc_lbl.setStyleSheet(_theme.VARIANT_BADGE)
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
        self._title_lbl.setStyleSheet(f"color: {_theme.COLOR_TEXT_2};")
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
            self._image_cache.image_loaded.connect(self._on_image_loaded)
            self._image_cache.image_failed.connect(self._on_image_failed)
            self._image_cache.get_image_async(self._card.thumbnail_url)

    def _stop_shimmer(self) -> None:
        """Stop the shimmer animation and reset the poster opacity to 1.0."""
        if self._shimmer:
            self._shimmer.stop()
            effect = self._poster_lbl.graphicsEffect()
            if effect:
                effect.setOpacity(1.0)

    def _on_image_loaded(self, url: str, pixmap: QPixmap) -> None:
        if url != self._card.thumbnail_url:
            return
        self._image_cache.image_loaded.disconnect(self._on_image_loaded)
        self._image_cache.image_failed.disconnect(self._on_image_failed)
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
        if url != self._card.thumbnail_url:
            return
        logger.debug(f"Poster load failed for {url!r}: {error}")
        self._image_cache.image_loaded.disconnect(self._on_image_loaded)
        self._image_cache.image_failed.disconnect(self._on_image_failed)
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
