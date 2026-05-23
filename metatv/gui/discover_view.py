"""Discovery view — horizontal shelf browse UI (🧭 Discover chip).

Shelves: Recently Added · Top Rated Movies · Top Rated Series ·
         Featured Actor · Genre shelves · Decade shelves.

Data comes entirely from raw_data (no TMDb API key needed). Poster images
use the TMDb CDN URLs already embedded in stream_icon / cover fields and
load on-demand through the existing ImageCache.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import (
    QObject, QRect, QSize, Qt, QThread, pyqtSignal,
)
from PyQt6.QtGui import QColor, QContextMenuEvent, QFont, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout,
    QWidget,
)
from loguru import logger

from metatv.core.config import Config
from metatv.core.database import Database
from metatv.core.discovery_engine import ContentCard

if TYPE_CHECKING:
    from metatv.core.image_cache import ImageCache


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

_CARD_W = 120
_CARD_H = 210
_POSTER_H = 175

_PLACEHOLDER_COLORS = [
    "#1a3a5c", "#2d4a1e", "#4a1e2d", "#2d1e4a", "#1e4a3a", "#3a2d1e",
]


class _ContentCard(QWidget):
    """120 × 210 px poster card with rating badge and title label."""

    clicked        = pyqtSignal(str)                  # channel_id
    doubleClicked  = pyqtSignal(str)
    contextMenuRequested = pyqtSignal(str, int, int)  # channel_id, gx, gy

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
        self._poster_frame.setStyleSheet("border: none;")

        # Placeholder background (colored rectangle)
        color = _PLACEHOLDER_COLORS[hash(card.channel_id) % len(_PLACEHOLDER_COLORS)]
        self._poster_frame.setStyleSheet(
            f"background: {color}; border-radius: 4px;"
        )

        # Poster image label (fills the frame)
        self._poster_lbl = QLabel(self._poster_frame)
        self._poster_lbl.setGeometry(0, 0, _CARD_W, _POSTER_H)
        self._poster_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._poster_lbl.setStyleSheet("background: transparent; border-radius: 4px;")

        # Placeholder icon (centered in frame)
        icon = config.movie_icon if card.media_type == "movie" else config.series_icon
        self._icon_lbl = QLabel(icon, self._poster_frame)
        self._icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_lbl.setGeometry(0, _POSTER_H // 2 - 20, _CARD_W, 40)
        self._icon_lbl.setStyleSheet("background: transparent; font-size: 24px;")

        # Rating badge (bottom-left overlay)
        if card.rating:
            self._rating_lbl = QLabel(f"★ {card.rating:.1f}", self._poster_frame)
            self._rating_lbl.setGeometry(4, _POSTER_H - 22, 60, 18)
            self._rating_lbl.setStyleSheet(
                "background: rgba(0,0,0,0.65); color: #ffd700; font-size: 10px; "
                "border-radius: 3px; padding: 1px 4px;"
            )

        vl.addWidget(self._poster_frame)

        # Title label
        self._title_lbl = QLabel(card.title)
        self._title_lbl.setFixedWidth(_CARD_W)
        self._title_lbl.setFixedHeight(32)
        self._title_lbl.setWordWrap(False)
        self._title_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._title_lbl.setStyleSheet("font-size: 10px; color: #ddd;")
        fm = self._title_lbl.fontMetrics()
        self._title_lbl.setText(fm.elidedText(card.title, Qt.TextElideMode.ElideRight, _CARD_W))
        self._title_lbl.setToolTip(card.title)
        vl.addWidget(self._title_lbl)

        # Wire image cache once
        self._image_cache.image_loaded.connect(self._on_image_loaded)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._image_requested and self._card.thumbnail_url:
            self._image_requested = True
            self._image_cache.get_image_async(self._card.thumbnail_url)

    def _on_image_loaded(self, url: str, pixmap: QPixmap) -> None:
        if url != self._card.thumbnail_url:
            return
        scaled = pixmap.scaled(
            _CARD_W, _POSTER_H,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        # Crop to exact size
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
    """Header + horizontal scrollable row of content cards."""

    seeAllRequested = pyqtSignal(str)  # shelf_key

    def __init__(self, title: str, shelf_key: str,
                 cards: list[ContentCard], image_cache: "ImageCache",
                 config: Config, parent=None) -> None:
        super().__init__(parent)
        self._shelf_key = shelf_key
        self._cards_widgets: list[_ContentCard] = []

        vl = QVBoxLayout(self)
        vl.setContentsMargins(8, 6, 8, 4)
        vl.setSpacing(4)

        # Header row
        header = QHBoxLayout()
        title_lbl = QLabel(f"<b>{title}</b>")
        title_lbl.setStyleSheet("font-size: 14px;")
        header.addWidget(title_lbl)
        header.addStretch()
        see_all_btn = QPushButton("See all →")
        see_all_btn.setFlat(True)
        see_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        see_all_btn.setStyleSheet(
            "QPushButton { color: #4488ff; border: none; font-size: 11px; }"
            "QPushButton:hover { color: #66aaff; }"
        )
        see_all_btn.clicked.connect(lambda: self.seeAllRequested.emit(self._shelf_key))
        header.addWidget(see_all_btn)
        vl.addLayout(header)

        # Horizontal scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(False)
        scroll.setFixedHeight(_CARD_H + 16)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("QScrollBar:horizontal { height: 6px; }")

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

    def wire(self, on_clicked, on_double_clicked, on_context_menu) -> None:
        for w in self._cards_widgets:
            w.clicked.connect(on_clicked)
            w.doubleClicked.connect(on_double_clicked)
            w.contextMenuRequested.connect(on_context_menu)


# ---------------------------------------------------------------------------
# Browse view (drill-down: "See all →")
# ---------------------------------------------------------------------------

class _BrowseContainer(QWidget):
    """Inner container for flow-layout grid; resizes self on show."""

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
    """Full-panel drill-down view for a shelf with search + grid/list toggle."""

    backRequested        = pyqtSignal()
    cardClicked          = pyqtSignal(str)
    cardDoubleClicked    = pyqtSignal(str)
    cardContextMenu      = pyqtSignal(str, int, int)

    def __init__(self, image_cache: "ImageCache", config: Config,
                 parent=None) -> None:
        super().__init__(parent)
        self._image_cache = image_cache
        self._config = config
        self._all_cards: list[ContentCard] = []
        self._flow: _FlowLayout | None = None
        self._card_widgets: list[_ContentCard] = []
        self._grid_mode = True
        self._setup_ui()

    def _setup_ui(self) -> None:
        vl = QVBoxLayout(self)
        vl.setContentsMargins(8, 8, 8, 8)
        vl.setSpacing(6)

        # Top bar
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

        # Stacked: grid page (0) and list page (1)
        self._stack = QStackedWidget()

        # Grid page
        self._grid_scroll = QScrollArea()
        self._grid_scroll.setWidgetResizable(True)
        self._grid_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._grid_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._grid_container = _BrowseContainer()
        self._grid_scroll.setWidget(self._grid_container)
        self._stack.addWidget(self._grid_scroll)

        # List page
        self._list_widget = QListWidget()
        self._list_widget.itemDoubleClicked.connect(
            lambda item: self.cardDoubleClicked.emit(item.data(Qt.ItemDataRole.UserRole))
        )
        self._list_widget.currentItemChanged.connect(self._on_list_select)
        self._stack.addWidget(self._list_widget)

        vl.addWidget(self._stack)

    def load(self, title: str, cards: list[ContentCard]) -> None:
        self._title_lbl.setText(title)
        self._all_cards = cards
        self._search_box.clear()
        self._rebuild(cards)

    def _rebuild(self, cards: list[ContentCard]) -> None:
        # Grid
        if self._flow:
            self._flow.clear()
        self._card_widgets.clear()
        self._flow = _FlowLayout(self._grid_container, spacing=8)
        self._grid_container.set_flow(self._flow)
        for card in cards:
            w = _ContentCard(card, self._image_cache, self._config)
            w.clicked.connect(self.cardClicked)
            w.doubleClicked.connect(self.cardDoubleClicked)
            w.contextMenuRequested.connect(self.cardContextMenu)
            self._flow.add(w)
            self._card_widgets.append(w)
        self._grid_container.resizeEvent(None)  # trigger initial layout

        # List
        self._list_widget.clear()
        for card in cards:
            icon = (self._config.movie_icon if card.media_type == "movie"
                    else self._config.series_icon)
            rating_str = f"  ★{card.rating:.1f}" if card.rating else ""
            year_str = f"  ({card.year})" if card.year else ""
            item = QListWidgetItem(f"{icon} {card.title}{year_str}{rating_str}")
            item.setData(Qt.ItemDataRole.UserRole, card.channel_id)
            self._list_widget.addItem(item)

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


# ---------------------------------------------------------------------------
# Background loader
# ---------------------------------------------------------------------------

class _ShelfData:
    """Payload emitted per shelf from the loader thread."""
    __slots__ = ("title", "shelf_key", "cards", "is_featured_actor")

    def __init__(self, title: str, shelf_key: str, cards: list[ContentCard],
                 is_featured_actor: bool = False) -> None:
        self.title = title
        self.shelf_key = shelf_key
        self.cards = cards
        self.is_featured_actor = is_featured_actor


class _LoaderWorker(QObject):
    """Runs in a QThread. Emits one shelfReady signal per shelf."""

    shelfReady = pyqtSignal(object)   # _ShelfData
    finished   = pyqtSignal()

    def __init__(self, db: Database, config: Config) -> None:
        super().__init__()
        self._db = db
        self._config = config

    def run(self) -> None:
        from metatv.core.discovery_engine import (
            get_recently_added, get_top_rated, get_by_genre,
            get_by_decade, get_featured_actor, get_all_genres, get_all_decades,
        )
        session = self._db.get_session()
        try:
            # 1. Recently Added
            cards = get_recently_added(session, limit=30)
            if cards:
                self.shelfReady.emit(_ShelfData(
                    f"{self._config.discover_icon} Recently Added",
                    "recently_added", cards,
                ))

            # 2. Top Rated Movies
            cards = get_top_rated(session, "movie", limit=30)
            if cards:
                self.shelfReady.emit(_ShelfData("Top Rated Movies", "top_movies", cards))

            # 3. Top Rated Series
            cards = get_top_rated(session, "series", limit=30)
            if cards:
                self.shelfReady.emit(_ShelfData("Top Rated Series", "top_series", cards))

            # 4. Featured Actor
            try:
                from metatv.core.preference_engine import compute_weights
                weights = compute_weights(session)
            except Exception:
                weights = None
            actor, cards = get_featured_actor(session, weights)
            if actor and cards:
                self.shelfReady.emit(_ShelfData(
                    f"Featured: {actor}", f"actor:{actor}", cards,
                    is_featured_actor=True,
                ))

            # 5. Genre shelves
            for genre in get_all_genres(session, min_count=10):
                cards = get_by_genre(session, genre, limit=30)
                if cards:
                    self.shelfReady.emit(_ShelfData(genre, f"genre:{genre}", cards))

            # 6. Decade shelves
            for decade in get_all_decades(session):
                decade_label = f"{decade}s"
                cards = get_by_decade(session, decade, limit=30)
                if cards:
                    self.shelfReady.emit(_ShelfData(decade_label, f"decade:{decade}", cards))

        except Exception:
            logger.exception("DiscoverView loader error")
        finally:
            session.close()
        self.finished.emit()


# ---------------------------------------------------------------------------
# Main view
# ---------------------------------------------------------------------------

class DiscoverView(QWidget):
    """🧭 Discover — horizontal shelf browse view."""

    playRequested               = pyqtSignal(str)       # channel_id
    channelSelected             = pyqtSignal(str)       # channel_id
    channelContextMenuRequested = pyqtSignal(str, int, int)

    def __init__(self, db: Database, config: Config,
                 image_cache: "ImageCache", parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._config = config
        self._image_cache = image_cache
        self._thread: QThread | None = None
        self._loaded = False
        self._shelf_data_cache: dict[str, list[ContentCard]] = {}
        self._setup_ui()

    def _setup_ui(self) -> None:
        vl = QVBoxLayout(self)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        # Stacked: 0 = shelves page, 1 = browse page
        self._stack = QStackedWidget()

        # --- Shelves page ---
        shelves_outer = QScrollArea()
        shelves_outer.setWidgetResizable(True)
        shelves_outer.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        shelves_outer.setFrameShape(QScrollArea.Shape.NoFrame)

        self._shelves_inner = QWidget()
        self._shelves_layout = QVBoxLayout(self._shelves_inner)
        self._shelves_layout.setContentsMargins(0, 8, 0, 16)
        self._shelves_layout.setSpacing(12)

        self._loading_lbl = QLabel("Loading…")
        self._loading_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_lbl.setStyleSheet("color: #666; font-size: 13px;")
        self._shelves_layout.addWidget(self._loading_lbl)
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

    def on_activate(self) -> None:
        if not self._loaded:
            self.refresh()

    def refresh(self) -> None:
        if self._thread and self._thread.isRunning():
            return
        self._loaded = False
        self._shelf_data_cache.clear()

        # Clear existing shelves except loading label
        while self._shelves_layout.count() > 1:
            item = self._shelves_layout.takeAt(0)
            if item.widget() and item.widget() is not self._loading_lbl:
                item.widget().deleteLater()
        self._loading_lbl.setVisible(True)
        self._loading_lbl.setText("Loading…")

        # Start background loader
        self._thread = QThread()
        self._worker = _LoaderWorker(self._db, self._config)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.shelfReady.connect(self._on_shelf_ready)
        self._worker.finished.connect(self._on_load_finished)
        self._worker.finished.connect(self._thread.quit)
        self._thread.start()

    def _on_shelf_ready(self, data: _ShelfData) -> None:
        """Called on main thread via signal for each completed shelf."""
        if self._loading_lbl.isVisible():
            self._loading_lbl.setVisible(False)
            # Remove the stretch so shelves stack properly
            stretch = self._shelves_layout.takeAt(self._shelves_layout.count() - 1)
            del stretch

        self._shelf_data_cache[data.shelf_key] = data.cards

        shelf = _Shelf(data.title, data.shelf_key, data.cards,
                       self._image_cache, self._config)
        shelf.seeAllRequested.connect(self._on_see_all)
        shelf.wire(self.channelSelected, self.playRequested,
                   self.channelContextMenuRequested)
        self._shelves_layout.addWidget(shelf)

    def _on_load_finished(self) -> None:
        self._loaded = True
        if self._loading_lbl.isVisible():
            self._loading_lbl.setText("No content found")
        else:
            self._shelves_layout.addStretch()

    def _on_see_all(self, shelf_key: str) -> None:
        cards = self._shelf_data_cache.get(shelf_key, [])
        # Determine a human label for the browse view title
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
        self._browse_view.load(title, cards)
        self._stack.setCurrentIndex(1)

    def _on_browse_back(self) -> None:
        self._stack.setCurrentIndex(0)
