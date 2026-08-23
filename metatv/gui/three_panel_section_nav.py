"""Left-nav / center-stack / right-help three-panel section switcher.

A small, dialog-agnostic composite widget: a ``QListWidget`` of section labels
on the left, a ``QStackedWidget`` of section pages in the center, and a
contextual-help ``QTextBrowser`` on the right whose text follows the selected
section. Built for :class:`~metatv.gui.settings_dialog.SettingsDialog`'s
three-panel rework and split out (rather than inlined there) so that file
stays under the 1000-line ceiling and because the container is a genuinely
separate concern from the five Settings tab builders — this widget knows
nothing about Config, Playback, or any other Settings-specific content, so a
future multi-section surface can reuse it directly.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QListWidget, QListWidgetItem, QStackedWidget, QTextBrowser, QWidget,
)

from metatv.gui import theme as _theme


class ThreePanelSectionNav(QWidget):
    """Left-nav section list + center stacked pages + right contextual help.

    Call :meth:`add_section` once per section (in display order) to append a
    left-nav row and its center page, then :meth:`set_current_row` to select
    the initial section. ``sectionChanged`` fires whenever the user picks a
    different row; the center page and help text are already synced by the
    time it fires.
    """

    sectionChanged = pyqtSignal(int)  # new row, only for user-driven changes

    def __init__(self, help_text_by_id: dict[str, str], parent: QWidget | None = None):
        super().__init__(parent)
        self._help_text_by_id = help_text_by_id
        self._section_ids: list[str] = []

        layout = QHBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        self.section_list = QListWidget()
        self.section_list.setFixedWidth(160)
        self.section_list.setToolTip("Choose a settings section.")
        _theme.style_fn(self.section_list, lambda: "QListWidget { border: none; border-right: 1px solid "
            f"{_theme.COLOR_LINE}; background: transparent; font-size: {_theme.FONT_XL};"
            " outline: none; }"
            f"QListWidget::item {{ padding: 8px 12px; color: {_theme.COLOR_TEXT_LOW}; }}"
            "QListWidget::item:hover { background: "
            f"{_theme.COLOR_LINE_DARK}; color: {_theme.COLOR_TEXT_2}; }}")
        # Shared "coloured-text item view" selection chokepoint (soft tint +
        # left accent bar) — appends onto the base stylesheet above.
        _theme.apply_list_selection(self.section_list)

        self.stack = QStackedWidget()

        self.help_panel = QTextBrowser()
        self.help_panel.setFixedWidth(220)
        self.help_panel.setOpenExternalLinks(False)
        self.help_panel.setReadOnly(True)
        self.help_panel.setToolTip("Help for the selected settings section.")
        _theme.style_fn(self.help_panel, lambda: "QTextBrowser { border: none; border-left: 1px solid "
            f"{_theme.COLOR_LINE}; background: transparent; color: {_theme.COLOR_TEXT};"
            f" font-size: {_theme.FONT_MD}; padding: 10px; }}")

        layout.addWidget(self.section_list)
        layout.addWidget(self.stack, 1)
        layout.addWidget(self.help_panel)

        self.section_list.currentRowChanged.connect(self._on_row_changed)

    def add_section(self, section_id: str, label: str, page: QWidget) -> None:
        """Append a left-nav row labeled *label* and its center *page*."""
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, section_id)
        item.setToolTip(f"Show {label} settings")
        self.section_list.addItem(item)
        self.stack.addWidget(page)
        self._section_ids.append(section_id)

    def count(self) -> int:
        return self.section_list.count()

    def current_row(self) -> int:
        return self.section_list.currentRow()

    def set_current_row(self, row: int, *, block_signal: bool = False) -> None:
        """Programmatically select *row*.

        Pass ``block_signal=True`` during a restore-from-config so this does
        not fire ``sectionChanged`` (CLAUDE.md: signal blocking during UI
        state restoration) — the page/help sync still happens either way.
        """
        if block_signal:
            self.section_list.blockSignals(True)
            self.section_list.setCurrentRow(row)
            self.section_list.blockSignals(False)
            self._sync_page(row)
        else:
            self.section_list.setCurrentRow(row)

    def select_by_label(self, label_substring: str) -> bool:
        """Select the first section whose label contains *label_substring*
        (case-insensitive). Returns True if a match was found and selected."""
        want = label_substring.strip().lower()
        for i in range(self.section_list.count()):
            if want in self.section_list.item(i).text().lower():
                self.section_list.setCurrentRow(i)
                return True
        return False

    def _on_row_changed(self, row: int) -> None:
        self._sync_page(row)
        self.sectionChanged.emit(row)

    def _sync_page(self, row: int) -> None:
        if row < 0 or row >= self.stack.count():
            return
        self.stack.setCurrentIndex(row)
        self.help_panel.setText(self._help_text_by_id.get(self._section_ids[row], ""))
