"""Discovery view — horizontal shelf browse UI (🧭 Discover chip).

Shelves: Recently Added · Top Rated Movies · Top Rated Series ·
         Featured Actor · Genre shelves · Decade shelves.

Data comes entirely from raw_data (no TMDb API key needed). Poster images
use the TMDb CDN URLs already embedded in stream_icon / cover fields and
load on-demand through the existing ImageCache.

Zone model
----------
  Pinned zone    — always expanded, always at top; immune to "Collapse all"
  Expanded zone  — currently browsing; preference-ranked
  ── More Categories ──  (divider, visible when collapsed zone has items)
  Collapsed zone — header-only strips; expands on click

Hidden shelves are not added to the layout at all; only restorable via
the Manage dialog.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import (
    QEasingCurve, QObject, QPropertyAnimation, QRect, QSize, Qt,
    QThread, QTimer, pyqtSignal,
)
from PyQt6.QtGui import QContextMenuEvent, QPixmap
from PyQt6.QtWidgets import (
    QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QScrollArea, QSizePolicy,
    QStackedWidget, QVBoxLayout, QWidget,
)
from loguru import logger

from metatv.core.config import Config
from metatv.core.database import Database
from metatv.core.discovery_engine import ContentCard

if TYPE_CHECKING:
    from metatv.core.image_cache import ImageCache


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CARD_W = 120
_CARD_H = 220
_POSTER_H = 175

_BROWSE_SCROLL_BATCH = 40   # card widgets created per scroll trigger (also used for initial batch)

_PLACEHOLDER_COLORS = [
    "#1a3a5c", "#2d4a1e", "#4a1e2d", "#2d1e4a", "#1e4a3a", "#3a2d1e",
]

# Shelf keys auto-expanded on first launch (no zone config set yet)
_DEFAULT_EXPANDED = {"recently_added", "top_movies"}

_ZONE_PINNED   = "pinned"
_ZONE_EXPANDED = "expanded"
_ZONE_COLLAPSED = "collapsed"


# ---------------------------------------------------------------------------
# Flow layout (wrapping grid for browse view)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Content card widget
# ---------------------------------------------------------------------------

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
            rating_lbl = QLabel(f"★ {card.rating:.1f}", self._poster_frame)
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
        self._title_lbl.setStyleSheet("font-size: 11px; color: #ddd;")
        self._title_lbl.setToolTip(card.title)
        vl.addWidget(self._title_lbl)

    def request_image(self) -> None:
        """Request poster image load — idempotent, only fires once.

        Also starts the shimmer and connects the image_loaded signal here
        (not in __init__) so collapsed-shelf cards incur zero overhead.
        """
        if not self._image_requested and self._card.thumbnail_url:
            self._image_requested = True
            if self._shimmer:
                self._shimmer.start()
            self._image_cache.image_loaded.connect(self._on_image_loaded)
            self._image_cache.get_image_async(self._card.thumbnail_url)

    def _on_image_loaded(self, url: str, pixmap: QPixmap) -> None:
        if url != self._card.thumbnail_url:
            return
        # Disconnect immediately — we only need this one delivery
        self._image_cache.image_loaded.disconnect(self._on_image_loaded)
        # Stop shimmer and restore full opacity
        if self._shimmer:
            self._shimmer.stop()
            effect = self._poster_lbl.graphicsEffect()
            if effect:
                effect.setOpacity(1.0)
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


# ---------------------------------------------------------------------------
# Shelf widget
# ---------------------------------------------------------------------------

class _Shelf(QWidget):
    """Header + horizontal scrollable row of content cards.

    Signals emitted to DiscoverView for zone management:
      pinRequested / unpinRequested — move to/from pinned zone
      collapseRequested / expandRequested — move to/from collapsed zone
      hideRequested — remove from view entirely
      seeAllRequested — open browse drill-down
    """

    seeAllRequested   = pyqtSignal(str)  # shelf_key
    pinRequested      = pyqtSignal(str)
    unpinRequested    = pyqtSignal(str)
    collapseRequested = pyqtSignal(str)
    expandRequested   = pyqtSignal(str)
    hideRequested     = pyqtSignal(str)

    def __init__(self, title: str, shelf_key: str,
                 cards: list[ContentCard], image_cache: "ImageCache",
                 config: Config, pinned: bool = False, collapsed: bool = False,
                 parent=None) -> None:
        super().__init__(parent)
        self._shelf_key = shelf_key
        self._config = config
        self._cards_widgets: list[_ContentCard] = []
        self._pinned = pinned
        self._collapsed = collapsed
        self._scroll_area: QScrollArea | None = None

        self._build_ui(title, cards, image_cache, config)
        self._apply_state()

    def _build_ui(self, title: str, cards: list[ContentCard],
                  image_cache: "ImageCache", config: Config) -> None:
        vl = QVBoxLayout(self)
        vl.setContentsMargins(8, 4, 8, 4)
        vl.setSpacing(4)

        # --- Header row ---
        header = QHBoxLayout()
        header.setSpacing(2)

        self._title_lbl = QLabel(f"<b>{title}</b>")
        self._title_lbl.setStyleSheet("font-size: 13px;")
        header.addWidget(self._title_lbl)
        header.addStretch()

        btn_ss = (
            "QPushButton { background: transparent; border: none; "
            "color: #777; font-size: 11px; padding: 2px 4px; }"
            "QPushButton:hover { color: #ccc; }"
        )

        self._see_all_btn = QPushButton("See all →")
        self._see_all_btn.setFlat(True)
        self._see_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._see_all_btn.setStyleSheet(
            "QPushButton { color: #4488ff; border: none; font-size: 11px; padding: 2px 4px; }"
            "QPushButton:hover { color: #66aaff; }"
        )
        self._see_all_btn.clicked.connect(lambda: self.seeAllRequested.emit(self._shelf_key))
        header.addWidget(self._see_all_btn)

        self._pin_btn = QPushButton(config.pin_icon)
        self._pin_btn.setFixedSize(24, 22)
        self._pin_btn.setFlat(True)
        self._pin_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pin_btn.setStyleSheet(btn_ss)
        self._pin_btn.clicked.connect(self._on_pin_clicked)
        header.addWidget(self._pin_btn)

        self._collapse_btn = QPushButton(config.collapse_icon)
        self._collapse_btn.setFixedSize(24, 22)
        self._collapse_btn.setFlat(True)
        self._collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._collapse_btn.setStyleSheet(btn_ss)
        self._collapse_btn.clicked.connect(self._on_collapse_clicked)
        header.addWidget(self._collapse_btn)

        self._hide_btn = QPushButton(config.hide_icon)
        self._hide_btn.setFixedSize(24, 22)
        self._hide_btn.setFlat(True)
        self._hide_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hide_btn.setStyleSheet(btn_ss)
        self._hide_btn.clicked.connect(lambda: self.hideRequested.emit(self._shelf_key))
        self._hide_btn.setToolTip("Hide this shelf")
        header.addWidget(self._hide_btn)

        vl.addLayout(header)

        # Make the header row clickable (expands when collapsed)
        self._header_area = QWidget()
        self._header_area.setLayout(QHBoxLayout())  # dummy, layout is vl above
        # We intercept clicks on the title label when collapsed
        self._title_lbl.mousePressEvent = self._on_title_click

        # --- Horizontal scroll area ---
        scroll = QScrollArea()
        scroll.setWidgetResizable(False)
        scroll.setFixedHeight(_CARD_H + 16)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("QScrollBar:horizontal { height: 10px; }")
        self._scroll_area = scroll

        inner = QWidget()
        inner_hl = QHBoxLayout(inner)
        inner_hl.setContentsMargins(0, 0, 16, 0)
        inner_hl.setSpacing(8)

        for card in cards:
            w = _ContentCard(card, image_cache, config, inner)
            inner_hl.addWidget(w)
            self._cards_widgets.append(w)
        inner_hl.addStretch()

        inner.setFixedHeight(_CARD_H + 4)
        inner.adjustSize()
        scroll.setWidget(inner)
        vl.addWidget(scroll)

        # Lazy loading via scroll position.
        # Initial fire is deferred — _apply_state() re-fires on expand if needed.
        scroll.horizontalScrollBar().valueChanged.connect(self._load_visible)
        if not self._collapsed:
            QTimer.singleShot(120, self._load_visible)

    def _apply_state(self) -> None:
        """Sync button icons and scroll-area visibility to current state."""
        if self._scroll_area is None:
            return
        self._scroll_area.setVisible(not self._collapsed)
        self._see_all_btn.setVisible(not self._collapsed)

        if self._collapsed:
            # Collapsed: only the expand arrow is always visible.
            # Pin + hide reveal on hover (enterEvent/leaveEvent).
            self._collapse_btn.setText("▶")
            self._collapse_btn.setToolTip("Expand")
            self._collapse_btn.setStyleSheet(
                "QPushButton { background: transparent; border: none; "
                "color: #999; font-size: 12px; padding: 2px 6px; }"
                "QPushButton:hover { color: #fff; }"
            )
            self._pin_btn.setVisible(False)
            self._hide_btn.setVisible(False)
            self._title_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setStyleSheet("")
        else:
            # Expanded: all controls visible.
            self._collapse_btn.setText("▼")
            self._collapse_btn.setToolTip("Collapse")
            self._collapse_btn.setStyleSheet(
                "QPushButton { background: transparent; border: none; "
                "color: #777; font-size: 12px; padding: 2px 6px; }"
                "QPushButton:hover { color: #ccc; }"
            )
            self._pin_btn.setVisible(True)
            self._hide_btn.setVisible(True)
            self._title_lbl.setCursor(Qt.CursorShape.ArrowCursor)

        if self._pinned:
            self._pin_btn.setText(self._config.pin_icon)
            self._pin_btn.setToolTip("Unpin")
            self._pin_btn.setStyleSheet(
                "QPushButton { background: transparent; border: none; "
                "color: #ffd700; font-size: 11px; padding: 2px 4px; }"
                "QPushButton:hover { color: #ffe566; }"
            )
        else:
            self._pin_btn.setText(self._config.pin_icon)
            self._pin_btn.setToolTip("Pin to top")
            self._pin_btn.setStyleSheet(
                "QPushButton { background: transparent; border: none; "
                "color: #555; font-size: 11px; padding: 2px 4px; }"
                "QPushButton:hover { color: #ccc; }"
            )

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        self._apply_state()
        if not collapsed:
            # Shelf just became visible — trigger image loading after Qt lays it out
            QTimer.singleShot(120, self._load_visible)

    def set_pinned(self, pinned: bool) -> None:
        self._pinned = pinned
        self._apply_state()

    def enterEvent(self, event) -> None:
        """Reveal pin + hide buttons when hovering a collapsed row."""
        if self._collapsed:
            self._pin_btn.setVisible(True)
            self._hide_btn.setVisible(True)
            self.setStyleSheet(
                "QWidget { background: rgba(255,255,255,18); border-radius: 4px; }"
            )
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if self._collapsed:
            self._pin_btn.setVisible(False)
            self._hide_btn.setVisible(False)
            self.setStyleSheet("")
        super().leaveEvent(event)

    def _on_pin_clicked(self) -> None:
        if self._pinned:
            self.unpinRequested.emit(self._shelf_key)
        else:
            self.pinRequested.emit(self._shelf_key)

    def _on_collapse_clicked(self) -> None:
        if self._collapsed:
            self.expandRequested.emit(self._shelf_key)
        else:
            self.collapseRequested.emit(self._shelf_key)

    def _on_title_click(self, event) -> None:
        if self._collapsed:
            self.expandRequested.emit(self._shelf_key)

    def _load_visible(self) -> None:
        """Request images for cards currently visible in the scroll viewport."""
        if self._collapsed or self._scroll_area is None:
            return
        vp_w = self._scroll_area.viewport().width()
        if vp_w == 0:
            # Viewport not laid out yet — retry after Qt processes the event loop
            QTimer.singleShot(80, self._load_visible)
            return
        scroll_x = self._scroll_area.horizontalScrollBar().value()
        for card in self._cards_widgets:
            left = card.x()  # position within inner content widget
            if left + card.width() >= scroll_x and left <= scroll_x + vp_w:
                card.request_image()

    def wire(self, on_clicked, on_double_clicked, on_context_menu) -> None:
        for w in self._cards_widgets:
            w.clicked.connect(on_clicked)
            w.doubleClicked.connect(on_double_clicked)
            w.contextMenuRequested.connect(on_context_menu)


# ---------------------------------------------------------------------------
# Browse view (drill-down: "See all →")
# ---------------------------------------------------------------------------

class _BrowseContainer(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._flow: _FlowLayout | None = None

    def set_flow(self, flow: _FlowLayout) -> None:
        self._flow = flow

    def resizeEvent(self, event) -> None:
        if self._flow:
            h = self._flow.relayout(self.width())
            self.setFixedHeight(max(h + 16, 100))
        super().resizeEvent(event)


class _BrowseView(QWidget):
    backRequested     = pyqtSignal()
    cardClicked       = pyqtSignal(str)
    cardDoubleClicked = pyqtSignal(str)
    cardContextMenu   = pyqtSignal(str, int, int)

    def __init__(self, image_cache: "ImageCache", config: Config,
                 parent=None) -> None:
        super().__init__(parent)
        self._image_cache = image_cache
        self._config = config
        self._all_cards: list[ContentCard] = []
        self._flow: _FlowLayout | None = None
        self._card_widgets: list[_ContentCard] = []
        self._all_pending_cards: list[ContentCard] = []
        self._created_count: int = 0
        self._grid_mode = True
        self._setup_ui()

    def _setup_ui(self) -> None:
        vl = QVBoxLayout(self)
        vl.setContentsMargins(8, 8, 8, 8)
        vl.setSpacing(6)

        top = QHBoxLayout()
        self._back_btn = QPushButton("← Back")
        self._back_btn.setFlat(True)
        self._back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._back_btn.setStyleSheet(
            "QPushButton { color: #4488ff; border: none; font-size: 12px; }"
            "QPushButton:hover { color: #66aaff; }"
        )
        self._back_btn.clicked.connect(self.backRequested)
        top.addWidget(self._back_btn)

        self._title_lbl = QLabel()
        self._title_lbl.setStyleSheet("font-size: 14px; font-weight: bold;")
        top.addWidget(self._title_lbl)
        top.addStretch()

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Filter…")
        self._search_box.setFixedWidth(200)
        self._search_box.textChanged.connect(self._apply_filter)
        top.addWidget(self._search_box)

        self._toggle_btn = QPushButton("☰ List")
        self._toggle_btn.setFlat(True)
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.setStyleSheet(
            "QPushButton { color: #aaa; border: none; font-size: 11px; }"
            "QPushButton:hover { color: #ddd; }"
        )
        self._toggle_btn.clicked.connect(self._toggle_view)
        top.addWidget(self._toggle_btn)
        vl.addLayout(top)

        self._stack = QStackedWidget()

        self._grid_scroll = QScrollArea()
        self._grid_scroll.setWidgetResizable(True)
        self._grid_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._grid_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._grid_container = _BrowseContainer()
        self._grid_scroll.setWidget(self._grid_container)
        self._grid_scroll.verticalScrollBar().valueChanged.connect(self._load_visible_browse)
        self._stack.addWidget(self._grid_scroll)

        self._list_widget = QListWidget()
        self._list_widget.itemDoubleClicked.connect(
            lambda item: self.cardDoubleClicked.emit(item.data(Qt.ItemDataRole.UserRole))
        )
        self._list_widget.currentItemChanged.connect(self._on_list_select)
        self._list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list_widget.customContextMenuRequested.connect(self._on_list_context_menu)
        self._stack.addWidget(self._list_widget)

        vl.addWidget(self._stack)

    def load(self, title: str, cards: list[ContentCard]) -> None:
        self._title_lbl.setText(title)
        self._all_cards = cards
        self._search_box.clear()
        self._rebuild(cards)

    def _rebuild(self, cards: list[ContentCard]) -> None:
        if self._flow:
            self._flow.clear()
        self._card_widgets.clear()
        self._all_pending_cards = list(cards)
        self._created_count = 0

        self._flow = _FlowLayout(self._grid_container, spacing=8)
        self._grid_container.set_flow(self._flow)

        # Create first batch immediately so the screen isn't empty
        self._create_next_card_batch()
        self._grid_container.resizeEvent(None)
        QTimer.singleShot(80, self._load_visible_browse)

        # List view: text-only items — fast regardless of count
        self._list_widget.clear()
        for card in cards:
            icon = (self._config.movie_icon if card.media_type == "movie"
                    else self._config.series_icon)
            rating_str = f"  ★{card.rating:.1f}" if card.rating else ""
            year_str = f"  ({card.year})" if card.year else ""
            item = QListWidgetItem(f"{icon} {card.title}{year_str}{rating_str}")
            item.setData(Qt.ItemDataRole.UserRole, card.channel_id)
            self._list_widget.addItem(item)

    def _create_next_card_batch(self) -> None:
        """Instantiate the next batch of pending card widgets and add to the flow layout."""
        end = min(self._created_count + _BROWSE_SCROLL_BATCH, len(self._all_pending_cards))
        for i in range(self._created_count, end):
            card = self._all_pending_cards[i]
            # Create with _grid_container as parent so setParent() in _flow.add() is a no-op.
            # If parent=None, setParent() converts a top-level to a child which hides the widget.
            w = _ContentCard(card, self._image_cache, self._config,
                             parent=self._grid_container)
            w.clicked.connect(self.cardClicked)
            w.doubleClicked.connect(self.cardDoubleClicked)
            w.contextMenuRequested.connect(self.cardContextMenu)
            self._flow.add(w)
            w.show()
            self._card_widgets.append(w)
        self._created_count = end
        self._grid_container.resizeEvent(None)

    def _load_visible_browse(self) -> None:
        vp_h = self._grid_scroll.viewport().height()
        if vp_h == 0:
            QTimer.singleShot(80, self._load_visible_browse)
            return
        scroll_y = self._grid_scroll.verticalScrollBar().value()

        # Create more card widgets when within 2 viewports of the last created card
        if self._created_count < len(self._all_pending_cards) and self._card_widgets:
            last_bottom = self._card_widgets[-1].y() + self._card_widgets[-1].height()
            if last_bottom < scroll_y + vp_h * 2:
                self._create_next_card_batch()

        # Load images for currently visible cards
        for card in self._card_widgets:
            top = card.y()
            if top + card.height() >= scroll_y and top <= scroll_y + vp_h:
                card.request_image()

    def _apply_filter(self, text: str) -> None:
        q = text.lower()
        filtered = [c for c in self._all_cards if q in c.title.lower()] if q else self._all_cards
        self._rebuild(filtered)

    def _toggle_view(self) -> None:
        self._grid_mode = not self._grid_mode
        if self._grid_mode:
            self._stack.setCurrentIndex(0)
            self._toggle_btn.setText("☰ List")
        else:
            self._stack.setCurrentIndex(1)
            self._toggle_btn.setText("⊞ Grid")

    def _on_list_select(self, current, _prev) -> None:
        if current:
            cid = current.data(Qt.ItemDataRole.UserRole)
            if cid:
                self.cardClicked.emit(cid)

    def _on_list_context_menu(self, pos) -> None:
        item = self._list_widget.itemAt(pos)
        if item:
            cid = item.data(Qt.ItemDataRole.UserRole)
            if cid:
                gp = self._list_widget.mapToGlobal(pos)
                self.cardContextMenu.emit(cid, gp.x(), gp.y())


# ---------------------------------------------------------------------------
# Background loader
# ---------------------------------------------------------------------------

_SEE_ALL_LIMIT = 500  # max cards fetched for the "See All" browse grid


class _SeeAllWorker(QObject):
    """Fetch the full item set for a shelf — runs in a background thread."""

    ready = pyqtSignal(str, list)  # (shelf_key, cards)

    def __init__(self, db: Database, config: Config, shelf_key: str) -> None:
        super().__init__()
        self._db = db
        self._config = config
        self._shelf_key = shelf_key

    def run(self) -> None:
        from metatv.core.database import ChannelDB, WatchQueueDB, UserRatingDB
        from metatv.core.discovery_engine import (
            get_recently_added, get_top_rated, get_by_genre,
            get_by_decade, get_by_actor,
        )
        from metatv.core.filter_utils import get_active_category_filter, get_excluded_prefixes
        session = self._db.get_session()
        try:
            fav_ids = {
                ch.id for ch in session.query(ChannelDB)
                .filter(ChannelDB.is_favorite == True).all()  # noqa: E712
            }
            queue_ids = {r.channel_id for r in session.query(WatchQueueDB).all()}
            watched_ids = {
                ch.id for ch in session.query(ChannelDB)
                .filter(ChannelDB.last_played.isnot(None)).all()
            }
            liked_ids = {
                r.channel_id for r in session.query(UserRatingDB)
                .filter(UserRatingDB.rating > 0).all()
            }
            included_prefixes, include_uncategorized = get_active_category_filter(self._config)
            fk = dict(included_prefixes=included_prefixes,
                      include_uncategorized=include_uncategorized)
            excluded_prefixes = get_excluded_prefixes(self._config)
            sk = dict(fav_ids=fav_ids, queue_ids=queue_ids,
                      watched_ids=watched_ids, liked_ids=liked_ids)

            key = self._shelf_key
            limit = _SEE_ALL_LIMIT
            if key == "recently_added":
                cards = get_recently_added(session, limit=limit, **sk, **fk)
            elif key == "top_movies":
                cards = get_top_rated(session, "movie", limit=limit, **sk, **fk)
            elif key == "top_series":
                cards = get_top_rated(session, "series", limit=limit, **sk, **fk)
            elif key.startswith("genre:"):
                cards = get_by_genre(session, key[6:], limit=limit, **sk, **fk)
            elif key.startswith("decade:"):
                cards = get_by_decade(session, int(key[7:]), limit=limit, **sk, **fk)
            elif key.startswith("actor:"):
                cards = get_by_actor(session, key[6:], limit=limit, **sk, **fk)
            else:
                cards = []
            if excluded_prefixes:
                cards = [c for c in cards if c.detected_prefix not in excluded_prefixes]
        except Exception:
            logger.exception("SeeAllWorker error for %s", self._shelf_key)
            cards = []
        finally:
            session.close()
        self.ready.emit(self._shelf_key, cards)


class _ShelfData:
    __slots__ = ("title", "shelf_key", "cards", "is_featured_actor")

    def __init__(self, title: str, shelf_key: str, cards: list[ContentCard],
                 is_featured_actor: bool = False) -> None:
        self.title = title
        self.shelf_key = shelf_key
        self.cards = cards
        self.is_featured_actor = is_featured_actor


class _LoaderWorker(QObject):
    shelfReady = pyqtSignal(object)   # _ShelfData
    finished   = pyqtSignal()

    def __init__(self, db: Database, config: Config) -> None:
        super().__init__()
        self._db = db
        self._config = config

    def run(self) -> None:
        from metatv.core.database import ChannelDB, WatchQueueDB, UserRatingDB
        from metatv.core.discovery_engine import (
            get_recently_added, get_top_rated, get_by_genre,
            get_by_decade, get_featured_actor, get_all_genres, get_all_decades,
            _rank_genres_by_preference,
        )
        from metatv.core.filter_utils import get_active_category_filter
        session = self._db.get_session()
        try:
            # Preload all status sets once — avoids per-card queries
            fav_ids = {
                ch.id for ch in session.query(ChannelDB)
                .filter(ChannelDB.is_favorite == True).all()  # noqa: E712
            }
            queue_ids = {
                r.channel_id for r in session.query(WatchQueueDB).all()
            }
            watched_ids = {
                ch.id for ch in session.query(ChannelDB)
                .filter(ChannelDB.last_played.isnot(None)).all()
            }
            liked_ids = {
                r.channel_id for r in session.query(UserRatingDB)
                .filter(UserRatingDB.rating > 0).all()
            }

            # Global category filter — applies to all shelf queries
            from metatv.core.filter_utils import get_excluded_prefixes
            included_prefixes, include_uncategorized = get_active_category_filter(self._config)
            fk = dict(included_prefixes=included_prefixes,
                      include_uncategorized=include_uncategorized)
            excluded_prefixes = get_excluded_prefixes(self._config)

            sk = dict(fav_ids=fav_ids, queue_ids=queue_ids,
                      watched_ids=watched_ids, liked_ids=liked_ids)

            hidden = set(self._config.discover_hidden_shelves)

            def emit(data: _ShelfData) -> None:
                if data.shelf_key not in hidden and data.cards:
                    cards = data.cards
                    if excluded_prefixes:
                        cards = [c for c in cards if c.detected_prefix not in excluded_prefixes]
                    if cards:
                        self.shelfReady.emit(_ShelfData(data.title, data.shelf_key, cards))

            # Fixed shelves
            emit(_ShelfData(
                "Recently Added", "recently_added",
                get_recently_added(session, limit=30, **sk, **fk),
            ))
            emit(_ShelfData(
                "Top Rated Movies", "top_movies",
                get_top_rated(session, "movie", limit=30, **sk, **fk),
            ))
            emit(_ShelfData(
                "Top Rated Series", "top_series",
                get_top_rated(session, "series", limit=30, **sk, **fk),
            ))

            # Featured Actor
            try:
                from metatv.core.preference_engine import compute_weights
                weights = compute_weights(session)
            except Exception:
                weights = None
            actor, cards = get_featured_actor(session, weights, **sk, **fk)
            if actor:
                emit(_ShelfData(f"Featured: {actor}", f"actor:{actor}", cards,
                                is_featured_actor=True))

            # Genre shelves — preference-ranked, no hard cap
            genres = get_all_genres(session, min_count=10, **fk)
            genres = _rank_genres_by_preference(genres, liked_ids, session, **fk)
            for genre in genres:
                key = f"genre:{genre}"
                if key not in hidden:
                    cards = get_by_genre(session, genre, limit=30, **sk, **fk)
                    emit(_ShelfData(genre, key, cards))

            # Decade shelves — no hard cap
            for decade in get_all_decades(session, **fk):
                key = f"decade:{decade}"
                if key not in hidden:
                    cards = get_by_decade(session, decade, limit=30, **sk, **fk)
                    emit(_ShelfData(f"{decade}s", key, cards))

        except Exception:
            logger.exception("DiscoverView loader error")
        finally:
            session.close()
        self.finished.emit()


# ---------------------------------------------------------------------------
# Main view
# ---------------------------------------------------------------------------

class DiscoverView(QWidget):
    """🧭 Discover — horizontal shelf browse view with two-zone layout."""

    playRequested               = pyqtSignal(str)
    channelSelected             = pyqtSignal(str)
    channelContextMenuRequested = pyqtSignal(str, int, int)

    def __init__(self, db: Database, config: Config,
                 image_cache: "ImageCache", parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._config = config
        self._image_cache = image_cache
        self._thread: QThread | None = None
        self._see_all_thread: QThread | None = None
        self._see_all_worker: "_SeeAllWorker | None" = None
        self._loaded = False
        self._shelf_data_cache: dict[str, list[ContentCard]] = {}
        # shelf_key → _Shelf widget
        self._shelf_widgets: dict[str, _Shelf] = {}
        # shelf_key → zone string
        self._shelf_zones: dict[str, str] = {}
        self._setup_ui()

    def _setup_ui(self) -> None:
        vl = QVBoxLayout(self)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        # Header bar (manage button)
        header_bar = QWidget()
        header_bar.setFixedHeight(36)
        hbl = QHBoxLayout(header_bar)
        hbl.setContentsMargins(8, 4, 8, 4)
        hbl.addStretch()
        manage_btn = QPushButton(f"{self._config.manage_icon} Manage")
        manage_btn.setFlat(True)
        manage_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        manage_btn.setStyleSheet(
            "QPushButton { color: #888; border: none; font-size: 11px; }"
            "QPushButton:hover { color: #ccc; }"
        )
        manage_btn.clicked.connect(self._open_manage_dialog)
        hbl.addWidget(manage_btn)
        vl.addWidget(header_bar)

        # Stacked: 0 = shelves page, 1 = browse page
        self._stack = QStackedWidget()

        # --- Shelves page ---
        shelves_outer = QScrollArea()
        shelves_outer.setWidgetResizable(True)
        shelves_outer.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        shelves_outer.setFrameShape(QScrollArea.Shape.NoFrame)

        self._shelves_inner = QWidget()
        self._shelves_layout = QVBoxLayout(self._shelves_inner)
        self._shelves_layout.setContentsMargins(0, 4, 0, 16)
        self._shelves_layout.setSpacing(8)

        # Loading label
        self._loading_lbl = QLabel("Loading…")
        self._loading_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_lbl.setStyleSheet("color: #666; font-size: 13px; padding: 20px;")
        self._shelves_layout.addWidget(self._loading_lbl)

        # Zone containers
        self._pinned_zone = QWidget()
        self._pinned_layout = QVBoxLayout(self._pinned_zone)
        self._pinned_layout.setContentsMargins(0, 0, 0, 0)
        self._pinned_layout.setSpacing(8)
        self._pinned_zone.setVisible(False)
        self._shelves_layout.addWidget(self._pinned_zone)

        self._expanded_zone = QWidget()
        self._expanded_layout = QVBoxLayout(self._expanded_zone)
        self._expanded_layout.setContentsMargins(0, 0, 0, 0)
        self._expanded_layout.setSpacing(8)
        self._expanded_zone.setVisible(False)
        self._shelves_layout.addWidget(self._expanded_zone)

        # "More Categories" section header — a large-target toggle button.
        # Always 36 px tall so it's easy to click even when the list is hidden.
        self._more_btn = QPushButton("▶  More Categories")
        self._more_btn.setFixedHeight(36)
        self._more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._more_btn.setStyleSheet(
            "QPushButton {"
            "  background: rgba(255,255,255,8);"
            "  border: none;"
            "  border-radius: 4px;"
            "  color: #888;"
            "  font-size: 12px;"
            "  text-align: left;"
            "  padding: 0 12px;"
            "}"
            "QPushButton:hover {"
            "  background: rgba(255,255,255,16);"
            "  color: #ccc;"
            "}"
        )
        self._more_btn.clicked.connect(self._toggle_more_categories)
        self._more_btn.setVisible(False)
        self._more_expanded = True  # collapsed zone starts visible when shown
        self._bulk_loading = False  # suppresses per-shelf zone visibility during initial load
        self._shelves_layout.addWidget(self._more_btn)

        self._collapsed_zone = QWidget()
        self._collapsed_layout = QVBoxLayout(self._collapsed_zone)
        self._collapsed_layout.setContentsMargins(4, 0, 0, 0)
        self._collapsed_layout.setSpacing(2)
        self._collapsed_zone.setVisible(False)
        self._shelves_layout.addWidget(self._collapsed_zone)

        self._shelves_layout.addStretch()

        shelves_outer.setWidget(self._shelves_inner)
        self._stack.addWidget(shelves_outer)

        # --- Browse page ---
        self._browse_view = _BrowseView(self._image_cache, self._config)
        self._browse_view.backRequested.connect(self._on_browse_back)
        self._browse_view.cardClicked.connect(self.channelSelected)
        self._browse_view.cardDoubleClicked.connect(self.playRequested)
        self._browse_view.cardContextMenu.connect(self.channelContextMenuRequested)
        self._stack.addWidget(self._browse_view)

        vl.addWidget(self._stack)

    # ---- Zone helpers -------------------------------------------------------

    def _is_first_launch(self) -> bool:
        cfg = self._config
        return (not cfg.discover_pinned_shelves
                and not cfg.discover_expanded_shelves
                and not cfg.discover_collapsed_shelves
                and not cfg.discover_hidden_shelves)

    def _determine_zone(self, shelf_key: str) -> str:
        cfg = self._config
        if shelf_key in cfg.discover_pinned_shelves:
            return _ZONE_PINNED
        if shelf_key in cfg.discover_expanded_shelves:
            return _ZONE_EXPANDED
        if shelf_key in cfg.discover_collapsed_shelves:
            return _ZONE_COLLAPSED
        # First-launch default: auto-expand a small set
        if self._is_first_launch():
            return _ZONE_EXPANDED if shelf_key in _DEFAULT_EXPANDED else _ZONE_COLLAPSED
        return _ZONE_COLLAPSED

    def _zone_layout(self, zone: str):
        return {
            _ZONE_PINNED:    self._pinned_layout,
            _ZONE_EXPANDED:  self._expanded_layout,
            _ZONE_COLLAPSED: self._collapsed_layout,
        }[zone]

    def _add_to_zone(self, shelf: _Shelf, zone: str) -> None:
        self._zone_layout(zone).addWidget(shelf)
        if zone == _ZONE_PINNED:
            self._pinned_zone.setVisible(True)
        elif zone == _ZONE_EXPANDED:
            self._expanded_zone.setVisible(True)
        elif zone == _ZONE_COLLAPSED and not self._bulk_loading:
            # Defer collapsed-zone visibility until load finishes — genre/decade shelves
            # arrive in rapid succession and each setVisible() would thrash the layout,
            # causing pinned/expanded shelves above to bounce. Pinned and expanded zones
            # are shown immediately (they populate slowly and don't cause bounce).
            self._collapsed_zone.setVisible(True)
            self._update_more_btn()

    def _remove_from_zone(self, shelf: _Shelf, zone: str) -> None:
        self._zone_layout(zone).removeWidget(shelf)
        # Hide zone container if now empty
        if zone == _ZONE_PINNED and self._pinned_layout.count() == 0:
            self._pinned_zone.setVisible(False)
        elif zone == _ZONE_EXPANDED and self._expanded_layout.count() == 0:
            self._expanded_zone.setVisible(False)
        elif zone == _ZONE_COLLAPSED and self._collapsed_layout.count() == 0:
            self._collapsed_zone.setVisible(False)
            self._update_more_btn()

    def _update_more_btn(self) -> None:
        """Sync the More Categories button label and visibility."""
        count = self._collapsed_layout.count()
        visible = count > 0
        self._more_btn.setVisible(visible)
        if not visible:
            self._collapsed_zone.setVisible(False)
            return
        arrow = "▼" if self._more_expanded else "▶"
        self._more_btn.setText(f"{arrow}  More Categories  ({count})")
        self._collapsed_zone.setVisible(self._more_expanded)

    def _toggle_more_categories(self) -> None:
        self._more_expanded = not self._more_expanded
        self._update_more_btn()

    def _move_shelf(self, shelf_key: str, new_zone: str) -> None:
        shelf = self._shelf_widgets.get(shelf_key)
        if shelf is None:
            return
        old_zone = self._shelf_zones.get(shelf_key)
        if old_zone == new_zone:
            return
        if old_zone:
            self._remove_from_zone(shelf, old_zone)
        self._shelf_zones[shelf_key] = new_zone
        shelf.set_collapsed(new_zone == _ZONE_COLLAPSED)
        shelf.set_pinned(new_zone == _ZONE_PINNED)
        self._add_to_zone(shelf, new_zone)

    def _save_zone_config(self) -> None:
        cfg = self._config
        cfg.discover_pinned_shelves   = [k for k, z in self._shelf_zones.items() if z == _ZONE_PINNED]
        cfg.discover_expanded_shelves = [k for k, z in self._shelf_zones.items() if z == _ZONE_EXPANDED]
        cfg.discover_collapsed_shelves = [k for k, z in self._shelf_zones.items() if z == _ZONE_COLLAPSED]
        cfg.save()

    # ---- Shelf signal handlers ----------------------------------------------

    def _on_pin_requested(self, shelf_key: str) -> None:
        self._move_shelf(shelf_key, _ZONE_PINNED)
        self._save_zone_config()

    def _on_unpin_requested(self, shelf_key: str) -> None:
        self._move_shelf(shelf_key, _ZONE_EXPANDED)
        self._save_zone_config()

    def _on_collapse_requested(self, shelf_key: str) -> None:
        self._move_shelf(shelf_key, _ZONE_COLLAPSED)
        self._save_zone_config()

    def _on_expand_requested(self, shelf_key: str) -> None:
        self._move_shelf(shelf_key, _ZONE_EXPANDED)
        self._save_zone_config()

    def _on_hide_requested(self, shelf_key: str) -> None:
        shelf = self._shelf_widgets.pop(shelf_key, None)
        if shelf is None:
            return
        old_zone = self._shelf_zones.pop(shelf_key, None)
        if old_zone:
            self._remove_from_zone(shelf, old_zone)
        shelf.deleteLater()
        cfg = self._config
        if shelf_key not in cfg.discover_hidden_shelves:
            cfg.discover_hidden_shelves.append(shelf_key)
        # Remove from all zone lists
        for lst in (cfg.discover_pinned_shelves, cfg.discover_expanded_shelves,
                    cfg.discover_collapsed_shelves):
            if shelf_key in lst:
                lst.remove(shelf_key)
        cfg.save()

    # ---- Load lifecycle -----------------------------------------------------

    def on_activate(self) -> None:
        if not self._loaded:
            self.refresh()

    def reload(self) -> None:
        """Force a full reload — used when global filters change."""
        self._loaded = False
        self.refresh()

    def refresh(self) -> None:
        if self._thread and self._thread.isRunning():
            return
        self._loaded = False
        self._shelf_data_cache.clear()
        self._shelf_widgets.clear()
        self._shelf_zones.clear()

        # Clear zone containers
        for layout in (self._pinned_layout, self._expanded_layout, self._collapsed_layout):
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
        self._pinned_zone.setVisible(False)
        self._expanded_zone.setVisible(False)
        self._collapsed_zone.setVisible(False)
        self._update_more_btn()

        self._bulk_loading = True
        self._loading_lbl.setVisible(True)
        self._loading_lbl.setText("Loading…")

        self._thread = QThread()
        self._worker = _LoaderWorker(self._db, self._config)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.shelfReady.connect(self._on_shelf_ready)
        self._worker.finished.connect(self._on_load_finished)
        self._worker.finished.connect(self._thread.quit)
        self._thread.start()

    def _on_shelf_ready(self, data: _ShelfData) -> None:
        if self._loading_lbl.isVisible():
            self._loading_lbl.setVisible(False)

        self._shelf_data_cache[data.shelf_key] = data.cards
        zone = self._determine_zone(data.shelf_key)

        shelf = _Shelf(
            data.title, data.shelf_key, data.cards,
            self._image_cache, self._config,
            pinned=(zone == _ZONE_PINNED),
            collapsed=(zone == _ZONE_COLLAPSED),
        )
        shelf.seeAllRequested.connect(self._on_see_all)
        shelf.pinRequested.connect(self._on_pin_requested)
        shelf.unpinRequested.connect(self._on_unpin_requested)
        shelf.collapseRequested.connect(self._on_collapse_requested)
        shelf.expandRequested.connect(self._on_expand_requested)
        shelf.hideRequested.connect(self._on_hide_requested)
        shelf.wire(self.channelSelected, self.playRequested,
                   self.channelContextMenuRequested)

        self._shelf_widgets[data.shelf_key] = shelf
        self._shelf_zones[data.shelf_key] = zone
        self._add_to_zone(shelf, zone)

    def _on_load_finished(self) -> None:
        self._bulk_loading = False
        self._loaded = True
        if self._loading_lbl.isVisible():
            self._loading_lbl.setText("No content found")
        # Pinned/expanded zones are already visible (shown as each shelf arrived).
        # Collapsed zone was deferred — reveal it now atomically so all genre/decade
        # shelves appear at once without bouncing the expanded shelves above.
        self._update_more_btn()
        # Trigger image loading for any shelves whose layout settled during the load
        QTimer.singleShot(300, self._trigger_image_load_all)

    def _trigger_image_load_all(self) -> None:
        """Fire image loading for all pinned/expanded shelves after zones become visible."""
        for shelf_key, zone in self._shelf_zones.items():
            if zone in (_ZONE_PINNED, _ZONE_EXPANDED):
                shelf = self._shelf_widgets.get(shelf_key)
                if shelf:
                    shelf._load_visible()

    # ---- Browse drill-down --------------------------------------------------

    def _on_see_all(self, shelf_key: str) -> None:
        if shelf_key.startswith("genre:"):
            title = shelf_key[6:]
        elif shelf_key.startswith("decade:"):
            title = f"{shelf_key[7:]}s"
        elif shelf_key.startswith("actor:"):
            title = f"Featuring {shelf_key[6:]}"
        elif shelf_key == "recently_added":
            title = "Recently Added"
        elif shelf_key == "top_movies":
            title = "Top Rated Movies"
        elif shelf_key == "top_series":
            title = "Top Rated Series"
        else:
            title = shelf_key

        # Show browse view immediately with the preview cards so it's instant,
        # then replace with the full result set once the background fetch completes.
        preview_cards = self._shelf_data_cache.get(shelf_key, [])
        self._browse_view.load(title, preview_cards)
        self._stack.setCurrentIndex(1)

        # Cancel any previous see-all fetch
        if self._see_all_thread and self._see_all_thread.isRunning():
            self._see_all_thread.quit()
            self._see_all_thread.wait(500)

        self._see_all_thread = QThread()
        self._see_all_worker = _SeeAllWorker(self._db, self._config, shelf_key)
        self._see_all_worker.moveToThread(self._see_all_thread)
        self._see_all_thread.started.connect(self._see_all_worker.run)

        def _on_ready(key: str, cards: list) -> None:
            if self._stack.currentIndex() == 1:  # still in browse view
                self._browse_view.load(title, cards)

        self._see_all_worker.ready.connect(_on_ready)
        self._see_all_worker.ready.connect(lambda *_: self._see_all_thread.quit())
        self._see_all_thread.start()

    def _on_browse_back(self) -> None:
        self._stack.setCurrentIndex(0)

    # ---- Manage dialog ------------------------------------------------------

    def _open_manage_dialog(self) -> None:
        from metatv.gui.discover_filter_dialog import DiscoverManageDialog
        dlg = DiscoverManageDialog(
            self._db, self._config,
            self._shelf_widgets, self._shelf_zones,
            parent=self,
        )
        if dlg.exec():
            # Dialog saved config — rebuild view to reflect changes
            self.refresh()
