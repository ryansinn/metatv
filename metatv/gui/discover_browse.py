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
from metatv.gui import theme as _theme
from metatv.gui import icons as _icons

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
    # Emitted when the user scrolls near the bottom AND every known card has been
    # rendered AND the caller has flagged that more pages remain (set_has_more).
    # Discover never connects this — it loads a one-shot capped set via load() and
    # never calls set_has_more(True), so its behaviour is unchanged.  The recipe
    # "Show all" page connects it to fetch the next DB page.
    loadMoreRequested = pyqtSignal()
    # Emitted when the user changes the filter text.  Carries the new filter string
    # (empty string = cleared).  Callers that page from the DB (recipe "Show all")
    # connect this to trigger a fresh page-1 fetch with the filter applied at the
    # SQL level, so every subsequent lazy-loaded page also respects the filter.
    # Discover leaves this unconnected — its _apply_filter already operates on the
    # fully-loaded in-memory card list, so no DB refetch is needed.
    filterChanged     = pyqtSignal(str)

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
        # Pagination state for callers that page from the DB (recipe "Show all").
        # _has_more gates whether a near-bottom scroll may emit loadMoreRequested;
        # _load_more_pending debounces it so we emit once per near-bottom, not on
        # every scroll tick while the request is in flight.
        self._has_more: bool = False
        self._load_more_pending: bool = False
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
            f"QPushButton {{ color: {_theme.COLOR_ACCENT_BLUE}; border: none; font-size: {_theme.FONT_LG}; }}"
            f"QPushButton:hover {{ color: {_theme.COLOR_ACCENT_HOVER}; }}"
        )
        self._back_btn.clicked.connect(self.backRequested)
        top.addWidget(self._back_btn)

        self._title_lbl = QLabel()
        self._title_lbl.setStyleSheet(f"font-size: {_theme.FONT_2XL}; font-weight: bold;")
        top.addWidget(self._title_lbl)
        top.addStretch()

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Filter…")
        self._search_box.setFixedWidth(200)
        self._search_box.textChanged.connect(self._apply_filter)
        top.addWidget(self._search_box)

        self._toggle_btn = QPushButton(f"{self._config.list_view_icon} List")
        self._toggle_btn.setFlat(True)
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.setStyleSheet(
            f"QPushButton {{ color: {_theme.COLOR_DIM}; border: none; font-size: {_theme.FONT_MD}; }}"
            f"QPushButton:hover {{ color: {_theme.COLOR_TEXT_2}; }}"
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
        # The LIST view scrolls independently of the grid; wire it to the same
        # near-bottom check so paging (loadMoreRequested) works in list mode too.
        self._list_widget.verticalScrollBar().valueChanged.connect(
            self._maybe_request_more_list
        )
        self._stack.addWidget(self._list_widget)

        vl.addWidget(self._stack)

    def load(self, title: str, cards: list[ContentCard], *, preserve_filter: bool = False) -> None:
        """Replace the browse contents with *cards* (the fresh page-1 / replace path).

        Resets pagination state so a subsequent caller starts clean — Discover's
        one-shot use never touches has_more, so its behaviour is unchanged.

        Args:
            title: Header label for the browse page.
            cards: Cards to display (page-1 seed).
            preserve_filter: When ``True``, the current filter text is kept so
                that a filter-triggered DB reseed preserves the user's search
                string across the reload.  When ``False`` (default, Discover +
                fresh recipe entry / recipe-change reseeds), the search box is
                cleared so the new page starts unfiltered.  The Discover path
                never passes ``preserve_filter=True``, so its behaviour is
                unchanged.
        """
        self._title_lbl.setText(title)
        self._all_cards = cards
        if not preserve_filter:
            self._search_box.clear()
        # A fresh load starts clean: no pending page request, and no "more"
        # until the caller opts in via set_has_more(True).
        self._has_more = False
        self._load_more_pending = False
        self._rebuild(cards)

    def set_has_more(self, has_more: bool) -> None:
        """Tell the view whether more DB pages remain to be appended.

        Only when True does a near-bottom scroll emit :attr:`loadMoreRequested`.
        Setting it True clears the in-flight debounce so the next near-bottom can
        fire again (the caller calls this after appending a page).
        """
        self._has_more = has_more
        if has_more:
            self._load_more_pending = False

    def append(self, cards: list[ContentCard]) -> None:
        """Append a freshly-fetched DB page WITHOUT clearing existing cards.

        Extends both the grid's pending-card list and the list widget, then
        triggers the grid's lazy batch creation so the new cards render as they
        scroll into view.  The complement of :meth:`load` (the replace path).
        """
        if not cards:
            return
        self._all_cards = self._all_cards + list(cards)
        self._all_pending_cards.extend(cards)

        # Grow the LIST widget immediately (cheap text rows).
        for card in cards:
            icon = (self._config.movie_icon if card.media_type == "movie"
                    else self._config.series_icon)
            rating_str = f"  ★{card.rating:.1f}" if card.rating else ""
            year_str = f"  ({card.year})" if card.year else ""
            variant_str = f"  ·{_icons.variant_count_icon}{card.variant_count}" if card.variant_count > 1 else ""
            item = QListWidgetItem(f"{icon} {card.title}{year_str}{rating_str}{variant_str}")
            item.setData(Qt.ItemDataRole.UserRole, card.channel_id)
            if card.variant_count > 1:
                item.setToolTip(f"{card.variant_count} source / quality variants of this title available")
            self._list_widget.addItem(item)

        # Let the grid create the next visible batch from the grown pending list.
        self._load_visible_browse()

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
            variant_str = f"  ·{_icons.variant_count_icon}{card.variant_count}" if card.variant_count > 1 else ""
            item = QListWidgetItem(f"{icon} {card.title}{year_str}{rating_str}{variant_str}")
            item.setData(Qt.ItemDataRole.UserRole, card.channel_id)
            if card.variant_count > 1:
                item.setToolTip(f"{card.variant_count} source / quality variants of this title available")
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

        # All known cards rendered + near the bottom + caller has more → page.
        if self._created_count >= len(self._all_pending_cards):
            sb = self._grid_scroll.verticalScrollBar()
            self._maybe_request_more(sb)

    def _maybe_request_more_list(self) -> None:
        """List-view scroll handler: emit loadMoreRequested when near the bottom."""
        self._maybe_request_more(self._list_widget.verticalScrollBar())

    def _maybe_request_more(self, scrollbar) -> None:
        """Emit :attr:`loadMoreRequested` once when scrolled near *scrollbar*'s end.

        Gated on ``_has_more`` (the caller flags that more DB pages remain) and
        debounced via ``_load_more_pending`` so a single near-bottom fires one
        request, not one per scroll tick.  ``set_has_more(True)`` re-arms it after
        the caller appends the page.
        """
        if not self._has_more or self._load_more_pending:
            return
        maximum = scrollbar.maximum()
        # "Near bottom": within ~1.5 viewport-pages of the end (or already at it).
        threshold = max(maximum - scrollbar.pageStep() * 3 // 2, 0)
        if scrollbar.value() >= threshold:
            self._load_more_pending = True
            self.loadMoreRequested.emit()

    def current_filter(self) -> str:
        """Return the current filter text (empty string when no filter is active)."""
        return self._search_box.text()

    def _apply_filter(self, text: str) -> None:
        q = text.lower()
        filtered = [c for c in self._all_cards if q in c.title.lower()] if q else self._all_cards
        self._rebuild(filtered)
        # Notify callers that page from the DB (recipe "Show all") so they can
        # trigger a fresh SQL-filtered fetch.  Discover leaves this unconnected.
        self.filterChanged.emit(text)

    def _toggle_view(self) -> None:
        self._grid_mode = not self._grid_mode
        if self._grid_mode:
            self._stack.setCurrentIndex(0)
            self._toggle_btn.setText(f"{self._config.list_view_icon} List")
        else:
            self._stack.setCurrentIndex(1)
            self._toggle_btn.setText(f"{self._config.grid_view_icon} Grid")

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
