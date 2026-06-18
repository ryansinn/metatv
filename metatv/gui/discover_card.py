"""Discover view — content card widget and flow layout helper."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QContextMenuEvent, QPixmap
from PyQt6.QtWidgets import (
    QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from loguru import logger
from metatv.core.config import Config
from metatv.core.discovery_engine import ContentCard
from metatv.gui import theme as _theme

if TYPE_CHECKING:
    from metatv.core.image_cache import ImageCache

_CARD_W = 120
_CARD_H = 220
_POSTER_H = 175

_PLACEHOLDER_COLORS = [
    "#1a3a5c", "#2d4a1e", "#4a1e2d", "#2d1e4a", "#1e4a3a", "#3a2d1e",
]


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
    """120 × 220 px poster card with shimmer, status overlay, and title."""

    clicked              = pyqtSignal(str)          # channel_id
    doubleClicked        = pyqtSignal(str)
    contextMenuRequested = pyqtSignal(str, int, int)

    def __init__(self, card: ContentCard, image_cache: "ImageCache",
                 config: Config, parent=None) -> None:
        super().__init__(parent)
        self._card = card
        self._image_cache = image_cache
        self._config = config
        self._image_requested = False

        self.setFixedSize(_CARD_W, _CARD_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        vl = QVBoxLayout(self)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(2)

        # Poster frame
        self._poster_frame = QFrame()
        self._poster_frame.setFixedSize(_CARD_W, _POSTER_H)
        color = _PLACEHOLDER_COLORS[hash(card.channel_id) % len(_PLACEHOLDER_COLORS)]
        self._poster_frame.setStyleSheet(
            f"background: {color}; border-radius: 4px;"
        )

        # Poster image label (fills the frame)
        self._poster_lbl = QLabel(self._poster_frame)
        self._poster_lbl.setGeometry(0, 0, _CARD_W, _POSTER_H)
        self._poster_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._poster_lbl.setStyleSheet("background: transparent; border-radius: 4px;")

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

        # Placeholder media-type icon (centered)
        icon = config.movie_icon if card.media_type == "movie" else config.series_icon
        self._icon_lbl = QLabel(icon, self._poster_frame)
        self._icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_lbl.setGeometry(0, _POSTER_H // 2 - 20, _CARD_W, 40)
        self._icon_lbl.setStyleSheet("background: transparent; font-size: 24px;")

        # Rating badge (bottom-left overlay)
        if card.rating:
            rating_lbl = QLabel(f"{config.rating_star_icon} {card.rating:.1f}", self._poster_frame)
            rating_lbl.setGeometry(4, _POSTER_H - 22, 60, 18)
            rating_lbl.setStyleSheet(
                "background: rgba(0,0,0,0.65); color: #ffd700; font-size: 10px; "
                "border-radius: 3px; padding: 1px 4px;"
            )

        # Category badge (bottom-right overlay) — provider's prefix label
        if card.detected_prefix:
            cat_lbl = QLabel(card.detected_prefix, self._poster_frame)
            cat_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cat_lbl.setStyleSheet(
                "background: rgba(0,0,0,0.55); color: #aad4ff; font-size: 9px; "
                "border-radius: 3px; padding: 1px 3px;"
            )
            cat_lbl.adjustSize()
            cat_lbl.move(_CARD_W - cat_lbl.width() - 4, _POSTER_H - 22)

        # Status overlay (top-right corner)
        badges = []
        if card.is_liked:        badges.append(config.like_icon)
        if card.is_favorite:     badges.append(config.favorite_icon)
        if card.in_queue:        badges.append(config.queue_icon)
        if card.already_watched: badges.append(config.watched_icon)
        if badges:
            status_lbl = QLabel(" ".join(badges), self._poster_frame)
            status_lbl.setStyleSheet(
                "background: rgba(0,0,0,150); border-radius: 3px;"
                " font-size: 9px; padding: 1px 3px; color: white;"
            )
            status_lbl.adjustSize()
            status_lbl.move(_CARD_W - status_lbl.width() - 4, 4)
            status_lbl.raise_()

        vl.addWidget(self._poster_frame)

        # Title label (2 lines, word-wrapped)
        self._title_lbl = QLabel(card.title)
        self._title_lbl.setFixedWidth(_CARD_W)
        self._title_lbl.setFixedHeight(38)
        self._title_lbl.setWordWrap(True)
        self._title_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._title_lbl.setStyleSheet(f"font-size: 11px; color: {_theme.COLOR_TEXT_2};")
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
        scaled = pixmap.scaled(
            _CARD_W, _POSTER_H,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = (scaled.width() - _CARD_W) // 2
        y = (scaled.height() - _POSTER_H) // 2
        cropped = scaled.copy(x, y, _CARD_W, _POSTER_H)
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
