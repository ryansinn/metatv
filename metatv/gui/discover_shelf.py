"""Discover view — shelf widget (header + horizontal scroll row)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from metatv.core.config import Config
from metatv.core.discovery_engine import ContentCard
from metatv.gui.discover_card import _ContentCard, _CARD_H, _CARD_W, card_metrics
from metatv.gui import cursor_affordance
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme

if TYPE_CHECKING:
    from metatv.core.image_cache import ImageCache


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
        # Kept so DiscoverView's shelf filter can match on what the user SEES,
        # not on the internal key ("collection:Apple+ Kids" vs "Apple+ Kids").
        self._title = title
        self._config = config
        self._image_cache = image_cache
        self._cards_widgets: list[_ContentCard] = []
        self._pinned = pinned
        self._collapsed = collapsed
        self._scroll_area: QScrollArea | None = None
        self._inner_layout = None   # set by _build_ui
        self._inner_widget = None   # set by _build_ui
        # List of (on_clicked, on_double_clicked, on_context_menu, on_middle_click)
        # tuples so set_cards() can wire late-added card widgets to the same slots.
        self._pending_wires: list[tuple] = []
        # Loading/error placeholder shown in the card row during a lazy-expand
        # fetch (header-only shelf with no cards yet); cleared by set_cards().
        self._placeholder_lbl: QLabel | None = None

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
        _theme.style_fn(self._title_lbl, lambda: f"font-size: {_theme.FONT_XL};")
        header.addWidget(self._title_lbl)
        header.addStretch()

        btn_ss = (
            "QPushButton { background: transparent; border: none; "
            f"color: {_theme.COLOR_DISABLED}; font-size: {_theme.FONT_MD}; padding: 2px 4px; }}"
            f"QPushButton:hover {{ color: {_theme.COLOR_TEXT}; }}"
        )

        self._see_all_btn = QPushButton("See all →")
        self._see_all_btn.setFlat(True)
        _theme.style_fn(self._see_all_btn, lambda: f"QPushButton {{ color: {_theme.COLOR_ACCENT_BLUE}; border: none; font-size: {_theme.FONT_MD}; padding: 2px 4px; }}"
            f"QPushButton:hover {{ color: {_theme.COLOR_ACCENT_HOVER}; }}")
        self._see_all_btn.clicked.connect(lambda: self.seeAllRequested.emit(self._shelf_key))
        header.addWidget(self._see_all_btn)

        self._pin_btn = QPushButton(config.pin_icon)
        self._pin_btn.setFixedSize(24, 22)
        self._pin_btn.setFlat(True)
        self._pin_btn.setStyleSheet(btn_ss)
        self._pin_btn.clicked.connect(self._on_pin_clicked)
        header.addWidget(self._pin_btn)

        self._hide_btn = QPushButton(config.hide_icon)
        self._hide_btn.setFixedSize(24, 22)
        self._hide_btn.setFlat(True)
        self._hide_btn.setStyleSheet(btn_ss)
        self._hide_btn.clicked.connect(lambda: self.hideRequested.emit(self._shelf_key))
        self._hide_btn.setToolTip("Hide this shelf")
        header.addWidget(self._hide_btn)

        # collapse_btn is added LAST so it is always the rightmost control.
        # pin_btn and hide_btn are hover-revealed to its left — this prevents the
        # expand click target from shifting when the hover controls appear (D3).
        self._collapse_btn = QPushButton(config.collapse_icon)
        self._collapse_btn.setFixedSize(24, 22)
        self._collapse_btn.setFlat(True)
        self._collapse_btn.setStyleSheet(btn_ss)
        self._collapse_btn.clicked.connect(self._on_collapse_clicked)
        header.addWidget(self._collapse_btn)

        vl.addLayout(header)

        # Make the title label clickable (expands when collapsed)
        self._title_lbl.mousePressEvent = self._on_title_click

        # --- Horizontal scroll area ---
        # Height is derived from the zoomed card height so the scroll row scales
        # with the user's zoom preference — same source-of-truth as _size_card_row().
        _m = card_metrics(config.discover_zoom)
        scroll = QScrollArea()
        scroll.setWidgetResizable(False)
        scroll.setFixedHeight(_m.card_h + 16)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("QScrollBar:horizontal { height: 10px; }")
        self._scroll_area = scroll

        inner = QWidget()
        inner_hl = QHBoxLayout(inner)
        inner_hl.setContentsMargins(0, 0, 16, 0)
        inner_hl.setSpacing(8)

        # Assign refs early so _size_card_row() can be called below.
        self._inner_layout = inner_hl
        self._inner_widget = inner

        for card in cards:
            w = _ContentCard(card, image_cache, config, inner)
            inner_hl.addWidget(w)
            self._cards_widgets.append(w)
        inner_hl.addStretch()

        self._size_card_row()
        scroll.setWidget(inner)
        vl.addWidget(scroll)

        scroll.horizontalScrollBar().valueChanged.connect(self._load_visible)
        if not self._collapsed:
            QTimer.singleShot(120, self._load_visible)

    def _size_card_row(self) -> None:
        """Size the inner card row from the zoomed card dimensions (timing-independent).

        Uses deterministic math rather than ``sizeHint()`` so the result is
        correct whether called from the eager build path or from ``set_cards()``
        after layout activation.  Both paths converge here and both read the
        same ``card_metrics(config.discover_zoom)`` helper, eliminating both
        the smoosh bug (D1) and any card/shelf divergence when zoom changes.
        """
        n = len(self._cards_widgets)
        m = self._inner_layout.contentsMargins()
        spacing = self._inner_layout.spacing()
        metrics = card_metrics(self._config.discover_zoom)
        width = m.left() + m.right() + n * metrics.card_w + max(0, n - 1) * spacing
        inner_h = metrics.card_h + 4
        self._inner_widget.setFixedHeight(inner_h)
        self._inner_widget.resize(width, inner_h)

    def _apply_state(self) -> None:
        """Sync button icons and scroll-area visibility to current state."""
        if self._scroll_area is None:
            return
        self._scroll_area.setVisible(not self._collapsed)
        self._see_all_btn.setVisible(not self._collapsed)

        if self._collapsed:
            self._collapse_btn.setText(self._config.expand_icon)
            self._collapse_btn.setToolTip("Expand")
            _theme.style_fn(self._collapse_btn, lambda: "QPushButton { background: transparent; border: none; "
                f"color: {_theme.COLOR_DIM_2}; font-size: {_theme.FONT_LG}; padding: 2px 6px; }}"
                f"QPushButton:hover {{ color: {_theme.COLOR_TEXT_HI}; }}")
            self._pin_btn.setVisible(False)
            self._hide_btn.setVisible(False)
            cursor_affordance.set_clickable(self._title_lbl, True)
            self.setStyleSheet("")
        else:
            self._collapse_btn.setText(self._config.collapse_icon)
            self._collapse_btn.setToolTip("Collapse")
            _theme.style_fn(self._collapse_btn, lambda: "QPushButton { background: transparent; border: none; "
                f"color: {_theme.COLOR_DISABLED}; font-size: {_theme.FONT_LG}; padding: 2px 6px; }}"
                f"QPushButton:hover {{ color: {_theme.COLOR_TEXT}; }}")
            self._pin_btn.setVisible(True)
            self._hide_btn.setVisible(True)
            cursor_affordance.set_clickable(self._title_lbl, False)
            # Clear any collapsed-row hover background left over from expanding
            # while hovered — leaveEvent's clear is guarded by _collapsed, which
            # is already False by the time the mouse leaves, so it would stick.
            self.setStyleSheet("")

        if self._pinned:
            self._pin_btn.setText(self._config.pin_icon)
            self._pin_btn.setToolTip("Unpin")
            _theme.style_fn(self._pin_btn, lambda: "QPushButton { background: transparent; border: none; "
                f"color: {_theme.COLOR_GOLD}; font-size: {_theme.FONT_MD}; padding: 2px 4px; }}"
                f"QPushButton:hover {{ color: {_theme.COLOR_GOLD_LIGHT}; }}")
        else:
            self._pin_btn.setText(self._config.pin_icon)
            self._pin_btn.setToolTip("Pin to top")
            _theme.style_fn(self._pin_btn, lambda: "QPushButton { background: transparent; border: none; "
                f"color: {_theme.COLOR_TEXT}; font-size: {_theme.FONT_MD}; padding: 2px 4px; }}"
                f"QPushButton:hover {{ color: {_theme.COLOR_TEXT}; }}")

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        self._apply_state()
        if not collapsed:
            QTimer.singleShot(120, self._load_visible)

    def set_pinned(self, pinned: bool) -> None:
        self._pinned = pinned
        self._apply_state()

    def enterEvent(self, event) -> None:
        """Reveal pin + hide buttons when hovering a collapsed row."""
        if self._collapsed:
            self._pin_btn.setVisible(True)
            self._hide_btn.setVisible(True)
            _theme.style_fn(self, lambda: f"QWidget {{ background: {_theme.OVERLAY_18}; border-radius: 4px; }}")
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if self._collapsed:
            self._pin_btn.setVisible(False)
            self._hide_btn.setVisible(False)
        # Always clear the hover background — never guard this on _collapsed, or
        # a shelf expanded mid-hover keeps the gray strip (the reported bug).
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
            QTimer.singleShot(80, self._load_visible)
            return
        scroll_x = self._scroll_area.horizontalScrollBar().value()
        for card in self._cards_widgets:
            left = card.x()
            if left + card.width() >= scroll_x and left <= scroll_x + vp_w:
                card.request_image()

    def _clear_placeholder(self) -> None:
        """Remove any loading/error placeholder row from the card row."""
        if self._placeholder_lbl is not None:
            self._inner_layout.removeWidget(self._placeholder_lbl)
            self._placeholder_lbl.deleteLater()
            self._placeholder_lbl = None

    def set_loading(self) -> None:
        """Show a muted "Loading…" placeholder while a lazy-expand fetch is in flight.

        Owner-reported perf bug: expanding/pinning a header-only (not-yet-fetched)
        shelf used to just sit empty for the 15-20s the old raw_data genre scan
        took, with no feedback at all.  Called by DiscoverView the instant a
        card fetch is kicked off (``_start_expand_fetch``); replaced by real
        cards on success (``set_cards``) or an error row on failure
        (``show_load_error``).  No-ops if cards are already present.
        """
        if self._cards_widgets:
            return
        self._clear_placeholder()
        self._placeholder_lbl = QLabel(f"{_icons.loading_icon} Loading…")
        _theme.style(self._placeholder_lbl, "DISCOVER_SHELF_LOADING")
        self._inner_layout.insertWidget(0, self._placeholder_lbl)

    def show_load_error(self, message: str = "Couldn't load this shelf") -> None:
        """Render a visible, non-selectable error row after a failed lazy-expand fetch.

        Per CLAUDE.md's async-background-DB-reads rule, a failed background load
        must never look like a silently-empty result — never ``clear(); return``.
        """
        self._clear_placeholder()
        self._placeholder_lbl = QLabel(f"{_icons.notification_warning_icon} {message}")
        _theme.style(self._placeholder_lbl, "DISCOVER_SHELF_ERROR")
        self._inner_layout.insertWidget(0, self._placeholder_lbl)

    def set_cards(self, cards: list, image_cache=None, config=None,
                  replace: bool = False) -> None:
        """Populate this shelf with *cards* after construction.

        The single card-build path used by both the lazy-expand flow (on a
        header-only shelf created empty) and the zoom-rebuild flow (``replace``).
        The existing scroll-area inner widget is reused — cards are added before
        the trailing stretch, the row is re-sized via ``_size_card_row()``, and
        the new widgets are wired to any connected slots.

        Args:
            cards:       The ``ContentCard`` list fetched by ``_ShelfCardsWorker``.
            image_cache: The ``ImageCache`` instance.  When *None* the instance
                         stored at construction time is reused (pass it if you
                         have it, otherwise the shelf stores it).
            config:      The ``Config`` instance.  Same fallback.
            replace:     When True, drop any existing card widgets first (used
                         when re-rendering the same cards at a new zoom level).
        """
        if not hasattr(self, "_inner_layout") or self._inner_layout is None:
            return  # layout not yet built (should not happen in practice)

        # A successful fetch replaces any loading/error placeholder from a
        # prior lazy-expand attempt.
        self._clear_placeholder()

        _ic  = image_cache if image_cache is not None else self._image_cache
        _cfg = config      if config      is not None else self._config

        if replace:
            # Zoom rebuild: discard the current card widgets (the trailing
            # stretch is removed below) before adding the re-sized ones.
            for w in self._cards_widgets:
                self._inner_layout.removeWidget(w)
                w.deleteLater()
            self._cards_widgets.clear()

        # Remove the trailing stretch so we can append cards before it.
        count = self._inner_layout.count()
        if count > 0:
            last = self._inner_layout.itemAt(count - 1)
            if last and last.spacerItem():
                self._inner_layout.removeItem(last)

        for card in cards:
            w = _ContentCard(card, _ic, _cfg, self._inner_widget)
            self._inner_layout.addWidget(w)
            self._cards_widgets.append(w)

        self._inner_layout.addStretch()

        # Re-size the inner widget so the scroll area reflects the true content
        # width.  Uses the deterministic _size_card_row() helper (same math as
        # the eager build path) instead of sizeHint() whose value is unreliable
        # before the layout has fully settled — that was the smoosh bug (D1).
        self._inner_layout.activate()
        self._size_card_row()

        # Wire the new card widgets to any already-connected slots.
        for slot in self._pending_wires:
            on_clicked, on_double_clicked, on_context_menu, on_middle_click = slot
            for w in self._cards_widgets[-len(cards):]:
                w.clicked.connect(on_clicked)
                w.doubleClicked.connect(on_double_clicked)
                w.contextMenuRequested.connect(on_context_menu)
                w.middleClicked.connect(on_middle_click)

        # Keep the scroll-area height in sync with the (possibly re-zoomed) cards.
        if self._scroll_area is not None:
            self._scroll_area.setFixedHeight(card_metrics(_cfg.discover_zoom).card_h + 16)

        # Trigger image loading for the newly added cards if we're expanded.
        if not self._collapsed:
            QTimer.singleShot(120, self._load_visible)

    def wire(self, on_clicked, on_double_clicked, on_context_menu, on_middle_click) -> None:
        self._pending_wires.append(
            (on_clicked, on_double_clicked, on_context_menu, on_middle_click)
        )
        for w in self._cards_widgets:
            w.clicked.connect(on_clicked)
            w.doubleClicked.connect(on_double_clicked)
            w.contextMenuRequested.connect(on_context_menu)
            w.middleClicked.connect(on_middle_click)
