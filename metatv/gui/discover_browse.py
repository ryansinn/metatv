"""Discover view — "See All" browse drill-down (grid + list view)."""

from __future__ import annotations
from metatv.gui.row_activation import connect_row_activation

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from metatv.core.config import Config
from metatv.core.discovery_engine import ContentCard
from metatv.gui.discover_card import UniformCardGrid, card_metrics, _ContentCard
from metatv.gui import theme as _theme
from metatv.gui import icons as _icons

if TYPE_CHECKING:
    from metatv.core.image_cache import ImageCache


class _BrowseContainer(QWidget):
    """Host for the virtualized card grid.

    Its height is computed from the card COUNT rather than from the widgets
    that exist, so the scrollbar is correct for the whole result set while only
    a viewport's worth of cards is alive.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._on_resize = None

    def set_resize_handler(self, handler) -> None:
        self._on_resize = handler

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._on_resize is not None:
            self._on_resize()


class _BrowseView(QWidget):
    backRequested     = pyqtSignal()
    cardClicked       = pyqtSignal(str)
    cardDoubleClicked = pyqtSignal(str)
    cardMiddleClicked = pyqtSignal(str)   # channel_id — configured middle-click play
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
        self._all_pending_cards: list[ContentCard] = []
        self._grid: UniformCardGrid | None = None
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
        _theme.style_fn(self._back_btn, lambda: f"QPushButton {{ color: {_theme.COLOR_ACCENT_BLUE}; border: none; font-size: {_theme.FONT_LG}; }}"
            f"QPushButton:hover {{ color: {_theme.COLOR_ACCENT_HOVER}; }}")
        self._back_btn.clicked.connect(self.backRequested)
        top.addWidget(self._back_btn)

        self._title_lbl = QLabel()
        _theme.style_fn(self._title_lbl, lambda: f"font-size: {_theme.FONT_2XL}; font-weight: bold;")
        top.addWidget(self._title_lbl)
        top.addStretch()

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Filter…")
        self._search_box.setFixedWidth(200)
        self._search_box.setClearButtonEnabled(True)
        self._search_box.textChanged.connect(self._apply_filter)
        top.addWidget(self._search_box)

        self._toggle_btn = QPushButton(f"{self._config.list_view_icon} List")
        self._toggle_btn.setFlat(True)
        _theme.style_fn(self._toggle_btn, lambda: f"QPushButton {{ color: {_theme.COLOR_TEXT}; border: none; font-size: {_theme.FONT_MD}; }}"
            f"QPushButton:hover {{ color: {_theme.COLOR_TEXT_2}; }}")
        self._toggle_btn.clicked.connect(self._toggle_view)
        top.addWidget(self._toggle_btn)
        vl.addLayout(top)

        self._stack = QStackedWidget()

        self._grid_scroll = QScrollArea()
        self._grid_scroll.setWidgetResizable(True)
        self._grid_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._grid_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._grid_container = _BrowseContainer()
        m = card_metrics(getattr(self._config, "discover_zoom", 1.0))
        self._grid = UniformCardGrid(
            self._grid_container, item_w=m.card_w, item_h=m.card_h,
            spacing=8, factory=self._build_card,
        )
        self._grid_container.set_resize_handler(self._relayout_grid)
        self._grid_scroll.setWidget(self._grid_container)
        self._grid_scroll.verticalScrollBar().valueChanged.connect(self._load_visible_browse)
        self._stack.addWidget(self._grid_scroll)

        self._list_widget = QListWidget()
        self._list_widget.itemDoubleClicked.connect(
            lambda item: self.cardDoubleClicked.emit(item.data(Qt.ItemDataRole.UserRole))
        )
        connect_row_activation(self._list_widget, self._on_list_select)
        self._list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list_widget.customContextMenuRequested.connect(self._on_list_context_menu)
        # Middle-click on a list row plays the configured action — same reusable
        # helper the sidebar sections use, so the grid card and the list row agree.
        from metatv.gui.list_middle_click import install_list_middle_click
        self._list_mc = install_list_middle_click(self._list_widget)
        self._list_mc.middleClicked.connect(self.cardMiddleClicked)
        # The LIST view scrolls independently of the grid; wire it to the same
        # near-bottom check so paging (loadMoreRequested) works in list mode too.
        self._list_widget.verticalScrollBar().valueChanged.connect(
            self._maybe_request_more_list
        )
        self._stack.addWidget(self._list_widget)

        vl.addWidget(self._stack)

    def set_back_label(self, text: str, tooltip: str | None = None) -> None:
        """Override the Back link's label + tooltip.

        Discover keeps the default ``"← Back"`` (returns to the shelf list); the
        recipe view relabels it (e.g. ``"✦ Build recipe"``) because the same link
        returns to the recipe *builder* there. Only the label/tooltip change — the
        emitted :attr:`backRequested` signal and its wiring are untouched.

        Args:
            text: New button label.
            tooltip: Optional tooltip; unchanged when ``None``.
        """
        self._back_btn.setText(text)
        if tooltip is not None:
            self._back_btn.setToolTip(tooltip)

    def refresh_theme(self) -> None:
        """Re-apply the active palette to this view's own persistent chrome
        (Back link, title, and the grid/list toggle button) — all styled once
        at construction and never touched again. Shared by ``DiscoverView``
        and ``RecipeView``'s "Show all" drill-down, each of which forwards to
        this from their own ``refresh_theme()``.
        """
        _theme.style_fn(self._back_btn, lambda: f"QPushButton {{ color: {_theme.COLOR_ACCENT_BLUE}; border: none; font-size: {_theme.FONT_LG}; }}"
            f"QPushButton:hover {{ color: {_theme.COLOR_ACCENT_HOVER}; }}")
        _theme.style_fn(self._title_lbl, lambda: f"font-size: {_theme.FONT_2XL}; font-weight: bold;")
        _theme.style_fn(self._toggle_btn, lambda: f"QPushButton {{ color: {_theme.COLOR_TEXT}; border: none; font-size: {_theme.FONT_MD}; }}"
            f"QPushButton:hover {{ color: {_theme.COLOR_TEXT_2}; }}")

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
        self._all_pending_cards = list(cards)
        self._grid.set_cards(self._all_pending_cards)
        self._relayout_grid()
        self._grid_scroll.verticalScrollBar().setValue(0)
        QTimer.singleShot(0, self._load_visible_browse)

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

    def _build_card(self, card: ContentCard) -> "_ContentCard":
        """Make one card widget. Called by the grid when a card scrolls in.

        May be called again for the same card after it scrolls out and back —
        the widget carries no user-editable state, and the shared image cache
        makes the second build free.
        """
        w = _ContentCard(card, self._image_cache, self._config,
                         parent=self._grid_container)
        w.clicked.connect(self.cardClicked)
        w.doubleClicked.connect(self.cardDoubleClicked)
        w.middleClicked.connect(self.cardMiddleClicked)
        w.contextMenuRequested.connect(self.cardContextMenu)
        return w

    def _relayout_grid(self) -> None:
        """Re-height the container for the CARD COUNT and re-window the grid.

        The height comes from the count, not from the widgets that happen to
        exist, so the scrollbar spans the whole result set immediately.
        """
        width = self._grid_scroll.viewport().width()
        if width <= 0:
            return
        self._grid_container.setFixedHeight(
            max(self._grid.total_height(width) + 16, 100))
        self._grid.sync(
            self._grid_scroll.verticalScrollBar().value(),
            self._grid_scroll.viewport().height(),
            width,
        )

    def _load_visible_browse(self) -> None:
        """Re-window the grid, hydrate what is on screen, page if near the end.

        The image request goes only to the LIVE widgets — the window — rather
        than to every card ever created, so this is a viewport-sized loop
        whatever the result count is.
        """
        vp_h = self._grid_scroll.viewport().height()
        if vp_h == 0:
            QTimer.singleShot(80, self._load_visible_browse)
            return

        self._relayout_grid()
        for card in self._grid.live_widgets():
            card.request_image()

        self._maybe_request_more(self._grid_scroll.verticalScrollBar())

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
