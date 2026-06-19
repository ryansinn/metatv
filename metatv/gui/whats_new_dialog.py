"""What's New dialog — carousel view, one release per screen.

Presents ``WhatsNewEntry`` records one at a time.  Navigation arrows let the
user step back through history (older releases) or forward again to the newest.
The arrow direction follows the user's mental model:

- **left / "‹" arrow** → newer releases (forward in recency; disabled at index 0)
- **right / "›" arrow** → older releases (back in history; disabled at the last index)

Entries are expected newest-first (as returned by ``entries_since`` and
``WHATS_NEW``).  The dialog opens showing index 0 (the newest entry).
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from loguru import logger

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.whats_new import WhatsNewEntry


class WhatsNewDialog(QDialog):
    """Modal dialog that presents What's New changelog entries as a carousel.

    Args:
        entries: Entries to display, newest-first.  If empty the empty-state
            card is shown.  If only one entry is passed the navigation controls
            are hidden.
        parent: Optional parent widget.
    """

    def __init__(self, entries: list[WhatsNewEntry], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("What's New")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.setMinimumHeight(460)
        self.resize(540, 520)
        self._entries = entries
        self._index: int = 0
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        # ── Header strip ──────────────────────────────────────────────
        header_widget = QWidget()
        header_widget.setStyleSheet(_theme.HEADER_TINT)
        header_layout = QVBoxLayout(header_widget)
        header_layout.setContentsMargins(20, 16, 20, 14)
        header_layout.setSpacing(2)

        icon_label = QLabel(f"{_icons.whats_new_icon}  What's New")
        icon_label.setStyleSheet(
            f"font-size: {_theme.FONT_3XL}; font-weight: bold; color: {_theme.COLOR_TEXT_HI};"
        )
        header_layout.addWidget(icon_label)
        root.addWidget(header_widget)

        # ── Card area (swapped by _show_index) ───────────────────────
        self._card_area = QWidget()
        card_area_layout = QVBoxLayout(self._card_area)
        card_area_layout.setContentsMargins(16, 12, 16, 12)
        card_area_layout.setSpacing(0)
        self._card_layout = card_area_layout

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self._card_area)
        root.addWidget(scroll, stretch=1)

        # ── Navigation strip (arrows + position indicator) ────────────
        self._nav_widget = QWidget()
        nav_layout = QHBoxLayout(self._nav_widget)
        nav_layout.setContentsMargins(16, 8, 16, 8)
        nav_layout.setSpacing(8)

        self._btn_newer = QPushButton(_icons.nav_prev_icon)
        self._btn_newer.setStyleSheet(_theme.WHATS_NEW_NAV_BTN)
        self._btn_newer.setToolTip("Newer")
        self._btn_newer.setFixedWidth(44)
        self._btn_newer.clicked.connect(self._go_newer)

        self._pos_label = QLabel()
        self._pos_label.setStyleSheet(_theme.WHATS_NEW_POS_LABEL)
        self._pos_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._btn_older = QPushButton(_icons.nav_next_icon)
        self._btn_older.setStyleSheet(_theme.WHATS_NEW_NAV_BTN)
        self._btn_older.setToolTip("Older")
        self._btn_older.setFixedWidth(44)
        self._btn_older.clicked.connect(self._go_older)

        nav_layout.addStretch()
        nav_layout.addWidget(self._btn_newer)
        nav_layout.addWidget(self._pos_label)
        nav_layout.addWidget(self._btn_older)
        nav_layout.addStretch()

        root.addWidget(self._nav_widget)

        # ── Footer with "Got it" button ───────────────────────────────
        footer_widget = QWidget()
        footer_widget.setStyleSheet(
            f"background: {_theme.COLOR_BG_BAR}; border-top: 1px solid {_theme.COLOR_LINE};"
        )
        footer_layout = QVBoxLayout(footer_widget)
        footer_layout.setContentsMargins(16, 10, 16, 10)

        btn_box = QDialogButtonBox()
        got_it_btn = QPushButton("Got it")
        got_it_btn.setDefault(True)
        got_it_btn.setToolTip("Dismiss this dialog")
        got_it_btn.setStyleSheet(_theme.SAVE_BTN)
        got_it_btn.clicked.connect(self.accept)
        btn_box.addButton(got_it_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        footer_layout.addWidget(btn_box)

        root.addWidget(footer_widget)

        # ── Initial render ────────────────────────────────────────────
        if not self._entries:
            self._nav_widget.hide()
            self._render_empty()
        elif len(self._entries) == 1:
            self._nav_widget.hide()
            self._show_index(0)
        else:
            self._show_index(0)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _go_newer(self) -> None:
        """Step forward (toward index 0, the newest entry)."""
        if self._index > 0:
            self._show_index(self._index - 1)

    def _go_older(self) -> None:
        """Step backward (toward the last index, the oldest entry)."""
        if self._index < len(self._entries) - 1:
            self._show_index(self._index + 1)

    def _show_index(self, index: int) -> None:
        """Render entries[index] in the card area and update navigation state."""
        if index < 0 or index >= len(self._entries):
            logger.warning(
                "WhatsNewDialog._show_index called with out-of-range index {}", index
            )
            return

        self._index = index

        # Clear previous card
        while self._card_layout.count():
            item = self._card_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Render current entry
        card = self._build_entry_card(self._entries[index])
        self._card_layout.addWidget(card)
        self._card_layout.addStretch()

        # Update position indicator
        total = len(self._entries)
        self._pos_label.setText(f"{index + 1} / {total}")

        # Enable/disable arrows based on bounds
        # "newer" (left) arrow — disabled when already at the newest (index 0)
        self._btn_newer.setEnabled(index > 0)
        # "older" (right) arrow — disabled when already at the oldest (last index)
        self._btn_older.setEnabled(index < total - 1)

    # ------------------------------------------------------------------
    # Card construction
    # ------------------------------------------------------------------

    def _render_empty(self) -> None:
        """Show the empty-state label when no entries are passed."""
        empty = QLabel("No new changes to show.")
        empty.setStyleSheet(_theme.EMPTY_LABEL)
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._card_layout.addWidget(empty)
        self._card_layout.addStretch()

    def _build_entry_card(self, entry: WhatsNewEntry) -> QWidget:
        """Build a single entry card widget."""
        card = QWidget()
        card.setStyleSheet(_theme.WHATS_NEW_CARD)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        # Title
        title_label = QLabel(entry.title)
        title_label.setStyleSheet(_theme.WHATS_NEW_TITLE)
        title_label.setWordWrap(True)
        layout.addWidget(title_label)

        # Version + date meta line
        meta_label = QLabel(f"v{entry.version}  ·  {entry.date}")
        meta_label.setStyleSheet(_theme.WHATS_NEW_META)
        layout.addWidget(meta_label)

        # Bullet items
        for item_text in entry.items:
            item_label = QLabel(f"{_icons.bullet_icon}  {item_text}")
            item_label.setStyleSheet(_theme.WHATS_NEW_ITEM)
            item_label.setWordWrap(True)
            layout.addWidget(item_label)

        return card
