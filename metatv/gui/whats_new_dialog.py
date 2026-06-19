"""What's New dialog — displays changelog entries to the user.

Shows a scrollable list of ``WhatsNewEntry`` cards (newest first), one card per
entry, each with a title, version/date meta line, and bulleted item list.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
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
    """Modal dialog that presents a list of What's New changelog entries.

    Args:
        entries: Entries to display, typically newest-first.
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
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        # Header strip
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

        # Scrollable card area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(16, 12, 16, 12)
        content_layout.setSpacing(12)

        if self._entries:
            for entry in self._entries:
                card = self._build_entry_card(entry)
                content_layout.addWidget(card)
        else:
            empty = QLabel("No new changes to show.")
            empty.setStyleSheet(_theme.EMPTY_LABEL)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            content_layout.addWidget(empty)

        content_layout.addStretch()
        scroll.setWidget(content_widget)
        root.addWidget(scroll, stretch=1)

        # Footer with "Got it" button
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
