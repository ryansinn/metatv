"""Discover view — shelf widget (header + horizontal scroll row)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from metatv.core.config import Config
from metatv.core.discovery_engine import ContentCard
from metatv.gui.discover_card import _ContentCard, _CARD_H

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

        # Make the title label clickable (expands when collapsed)
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
            QTimer.singleShot(80, self._load_visible)
            return
        scroll_x = self._scroll_area.horizontalScrollBar().value()
        for card in self._cards_widgets:
            left = card.x()
            if left + card.width() >= scroll_x and left <= scroll_x + vp_w:
                card.request_image()

    def wire(self, on_clicked, on_double_clicked, on_context_menu) -> None:
        for w in self._cards_widgets:
            w.clicked.connect(on_clicked)
            w.doubleClicked.connect(on_double_clicked)
            w.contextMenuRequested.connect(on_context_menu)
