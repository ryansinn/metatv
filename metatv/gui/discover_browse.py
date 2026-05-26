"""Discover view — "See All" browse drill-down (grid + list view)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from metatv.core.config import Config
from metatv.core.discovery_engine import ContentCard
from metatv.gui.discover_card import _ContentCard, _FlowLayout

if TYPE_CHECKING:
    from metatv.core.image_cache import ImageCache

_BROWSE_SCROLL_BATCH = 40


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

        self._create_next_card_batch()
        self._grid_container.resizeEvent(None)
        QTimer.singleShot(80, self._load_visible_browse)

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

        if self._created_count < len(self._all_pending_cards) and self._card_widgets:
            last_bottom = self._card_widgets[-1].y() + self._card_widgets[-1].height()
            if last_bottom < scroll_y + vp_h * 2:
                self._create_next_card_batch()

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
