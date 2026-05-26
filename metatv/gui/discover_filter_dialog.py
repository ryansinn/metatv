"""Discover shelf management dialog.

Four sections mirroring the zone model:
  1. Pinned shelves  — Move to Top / Up / Down; Unpin
  2. Active shelves  — same reorder; Pin / Collapse
  3. Collapsed shelves — Expand / Pin / Hide
  4. Hidden shelves  — Restore (the only recovery path)

Global actions: Collapse all / Expand all (pinned shelves immune to Collapse all).

All changes are applied to config immediately on each action; a single "Close"
button dismisses the dialog. DiscoverView.refresh() fires once on close if anything
changed (dlg._changed == True).

Cross-section transfers (Hide, Restore, Pin, etc.) are O(1): one row removed from
the source container, one row added to the destination. No full-section rebuilds.
Reorder operations (Up/Down/Top, Collapse All / Expand All) rebuild only the affected
section(s), which are small (pinned/expanded ≤ ~5 items in practice).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)
from loguru import logger

from metatv.core.config import Config
from metatv.core.database import Database

if TYPE_CHECKING:
    from metatv.gui.discover_view import _Shelf

_ZONE_PINNED    = "pinned"
_ZONE_EXPANDED  = "expanded"
_ZONE_COLLAPSED = "collapsed"


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        "font-size: 12px; font-weight: bold; color: #aaa; "
        "padding: 6px 0 2px 0;"
    )
    return lbl


def _divider() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet("color: #444;")
    return line


class _ShelfRow(QWidget):
    """A single row in the manage list — title + action buttons."""

    def __init__(self, shelf_key: str, display_title: str, parent=None) -> None:
        super().__init__(parent)
        self.shelf_key = shelf_key

        hl = QHBoxLayout(self)
        hl.setContentsMargins(4, 2, 4, 2)
        hl.setSpacing(4)

        self._title_lbl = QLabel(display_title)
        self._title_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        hl.addWidget(self._title_lbl)

        self._buttons: list[QPushButton] = []

    def add_button(self, label: str, slot, tooltip: str = "") -> QPushButton:
        btn = QPushButton(label)
        btn.setFixedHeight(22)
        btn.setFlat(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            "QPushButton { background: #333; border: 1px solid #555; "
            "border-radius: 3px; color: #ccc; font-size: 10px; padding: 1px 6px; }"
            "QPushButton:hover { background: #444; color: #fff; }"
        )
        if tooltip:
            btn.setToolTip(tooltip)
        btn.clicked.connect(lambda _checked=False, _s=slot: _s())
        self.layout().addWidget(btn)
        self._buttons.append(btn)
        return btn


class DiscoverManageDialog(QDialog):
    """Shelf management: reorder, pin/collapse/hide, restore hidden.

    All changes write to config immediately. DiscoverView should check
    dlg._changed after exec() and call refresh() if True.
    """

    def __init__(self, db: Database, config: Config,
                 shelf_widgets: dict, shelf_zones: dict,
                 parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._config = config
        self._changed = False

        # Convenience aliases — these ARE the config lists (modified in place)
        self._pinned    = config.discover_pinned_shelves
        self._expanded  = config.discover_expanded_shelves
        self._collapsed = config.discover_collapsed_shelves
        self._hidden    = config.discover_hidden_shelves

        # Display names from live shelf_widgets (already loaded)
        self._titles: dict[str, str] = {}
        for key, shelf in shelf_widgets.items():
            self._titles[key] = shelf._title_lbl.text().replace("<b>", "").replace("</b>", "")

        # Shelves present in zone map but not yet assigned to a list (first launch)
        for key, zone in shelf_zones.items():
            if (key not in self._pinned and key not in self._expanded
                    and key not in self._collapsed and key not in self._hidden):
                if zone == _ZONE_PINNED:
                    self._pinned.append(key)
                elif zone == _ZONE_EXPANDED:
                    self._expanded.append(key)
                else:
                    self._collapsed.append(key)

        # shelf_key → current row widget — enables O(1) cross-section transfers
        self._row_widgets: dict[str, _ShelfRow] = {}

        self.setWindowTitle("Manage Discovery Shelves")
        self.setMinimumSize(500, 600)
        self._setup_ui()

    # ---- Helpers ------------------------------------------------------------

    def _commit(self) -> None:
        """Persist current config state and mark dialog as having changes."""
        self._config.save()
        self._changed = True

    # ---- UI construction ----------------------------------------------------

    def _setup_ui(self) -> None:
        vl = QVBoxLayout(self)
        vl.setSpacing(8)

        # Global actions
        global_row = QHBoxLayout()
        collapse_all_btn = QPushButton("Collapse all")
        collapse_all_btn.clicked.connect(self._collapse_all)
        expand_all_btn = QPushButton("Expand all")
        expand_all_btn.clicked.connect(self._expand_all)
        for btn in (collapse_all_btn, expand_all_btn):
            btn.setStyleSheet(
                "QPushButton { background: #2a2a2a; border: 1px solid #555; "
                "border-radius: 3px; color: #ccc; padding: 3px 10px; }"
                "QPushButton:hover { background: #3a3a3a; }"
            )
        global_row.addWidget(collapse_all_btn)
        global_row.addWidget(expand_all_btn)
        global_row.addStretch()
        vl.addLayout(global_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        inner_vl = QVBoxLayout(inner)
        inner_vl.setSpacing(4)

        inner_vl.addWidget(_section_label("📌 Pinned shelves"))
        self._pinned_list = self._make_list(inner_vl, self._pinned, self._build_pinned_row)
        inner_vl.addWidget(_divider())

        inner_vl.addWidget(_section_label("Active shelves"))
        self._expanded_list = self._make_list(inner_vl, self._expanded, self._build_expanded_row)
        inner_vl.addWidget(_divider())

        inner_vl.addWidget(_section_label("── Collapsed shelves ──"))
        self._collapsed_list = self._make_list(inner_vl, self._collapsed, self._build_collapsed_row)
        inner_vl.addWidget(_divider())

        inner_vl.addWidget(_section_label("🚫 Hidden shelves"))
        self._hidden_list = self._make_list(inner_vl, self._hidden, self._build_hidden_row)
        inner_vl.addStretch()

        scroll.setWidget(inner)
        vl.addWidget(scroll)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.accept)
        vl.addWidget(buttons)

    def _make_list(self, parent_layout: QVBoxLayout,
                   keys: list[str], row_factory) -> QWidget:
        container = QWidget()
        vl = QVBoxLayout(container)
        vl.setContentsMargins(8, 0, 0, 0)
        vl.setSpacing(2)
        for key in keys:
            row = row_factory(key)
            vl.addWidget(row)
            self._row_widgets[key] = row
        if vl.count() == 0:
            self._add_empty_label(container)
        parent_layout.addWidget(container)
        return container

    # ---- Row builders -------------------------------------------------------

    def _build_pinned_row(self, key: str) -> _ShelfRow:
        title = self._titles.get(key, key)
        row = _ShelfRow(key, f"📌 {title}")
        row.add_button("↑↑ Top", lambda k=key: self._move_top(self._pinned, k, self._pinned_list, self._build_pinned_row), "Move to top")
        row.add_button("↑ Up",   lambda k=key: self._move_up(self._pinned, k, self._pinned_list, self._build_pinned_row))
        row.add_button("↓ Down", lambda k=key: self._move_down(self._pinned, k, self._pinned_list, self._build_pinned_row))
        row.add_button("Unpin",  lambda k=key: self._transfer(k, self._pinned, self._pinned_list,
                                                               self._expanded, self._expanded_list,
                                                               self._build_expanded_row))
        return row

    def _build_expanded_row(self, key: str) -> _ShelfRow:
        title = self._titles.get(key, key)
        row = _ShelfRow(key, title)
        row.add_button("↑↑ Top",   lambda k=key: self._move_top(self._expanded, k, self._expanded_list, self._build_expanded_row))
        row.add_button("↑ Up",     lambda k=key: self._move_up(self._expanded, k, self._expanded_list, self._build_expanded_row))
        row.add_button("↓ Down",   lambda k=key: self._move_down(self._expanded, k, self._expanded_list, self._build_expanded_row))
        row.add_button("Pin",      lambda k=key: self._transfer(k, self._expanded, self._expanded_list,
                                                                 self._pinned, self._pinned_list,
                                                                 self._build_pinned_row))
        row.add_button("Collapse", lambda k=key: self._transfer(k, self._expanded, self._expanded_list,
                                                                 self._collapsed, self._collapsed_list,
                                                                 self._build_collapsed_row))
        return row

    def _build_collapsed_row(self, key: str) -> _ShelfRow:
        title = self._titles.get(key, key)
        row = _ShelfRow(key, title)
        row.add_button("Expand", lambda k=key: self._transfer(k, self._collapsed, self._collapsed_list,
                                                               self._expanded, self._expanded_list,
                                                               self._build_expanded_row))
        row.add_button("Pin",    lambda k=key: self._transfer(k, self._collapsed, self._collapsed_list,
                                                               self._pinned, self._pinned_list,
                                                               self._build_pinned_row))
        row.add_button("Hide",   lambda k=key: self._transfer(k, self._collapsed, self._collapsed_list,
                                                               self._hidden, self._hidden_list,
                                                               self._build_hidden_row))
        return row

    def _build_hidden_row(self, key: str) -> _ShelfRow:
        title = self._titles.get(key, key)
        row = _ShelfRow(key, title)
        row.add_button("Restore", lambda k=key: self._transfer(k, self._hidden, self._hidden_list,
                                                                self._collapsed, self._collapsed_list,
                                                                self._build_collapsed_row))
        return row

    # ---- List operations ----------------------------------------------------

    def _move_top(self, lst: list[str], key: str, container: QWidget, row_factory) -> None:
        if key in lst:
            lst.remove(key)
            lst.insert(0, key)
            self._reload_section(container, lst, row_factory)
            self._commit()

    def _move_up(self, lst: list[str], key: str, container: QWidget, row_factory) -> None:
        idx = lst.index(key) if key in lst else -1
        if idx > 0:
            lst[idx], lst[idx - 1] = lst[idx - 1], lst[idx]
            self._reload_section(container, lst, row_factory)
            self._commit()

    def _move_down(self, lst: list[str], key: str, container: QWidget, row_factory) -> None:
        idx = lst.index(key) if key in lst else -1
        if 0 <= idx < len(lst) - 1:
            lst[idx], lst[idx + 1] = lst[idx + 1], lst[idx]
            self._reload_section(container, lst, row_factory)
            self._commit()

    def _transfer(self, key: str,
                  src_list: list[str], src_container: QWidget,
                  dst_list: list[str], dst_container: QWidget,
                  dst_factory) -> None:
        """Move a shelf between sections — O(1): one row removed, one row added."""
        if key in src_list:
            src_list.remove(key)
        if key not in dst_list:
            dst_list.append(key)

        # Remove old row from source container
        old_row = self._row_widgets.pop(key, None)
        if old_row:
            src_container.layout().removeWidget(old_row)
            old_row.setParent(None)
        self._sync_empty_label(src_container)

        # Add new row to destination container, then remove placeholder if one existed
        new_row = dst_factory(key)
        dst_container.layout().addWidget(new_row)
        self._row_widgets[key] = new_row
        self._sync_empty_label(dst_container)

        self._commit()

    # ---- Section helpers ----------------------------------------------------

    def _add_empty_label(self, container: QWidget) -> None:
        empty = QLabel("(none)")
        empty.setObjectName("_empty_placeholder")
        empty.setStyleSheet("color: #555; font-size: 11px; padding: 2px 0;")
        container.layout().addWidget(empty)

    def _sync_empty_label(self, container: QWidget) -> None:
        """Show (none) label when no _ShelfRow children remain; remove it when rows exist."""
        vl = container.layout()
        has_rows = any(
            isinstance(vl.itemAt(i).widget(), _ShelfRow)
            for i in range(vl.count())
        )
        placeholder = container.findChild(QLabel, "_empty_placeholder")
        if has_rows and placeholder:
            placeholder.setParent(None)
        elif not has_rows and not placeholder:
            self._add_empty_label(container)

    def _reload_section(self, container: QWidget,
                        keys: list[str], row_factory) -> None:
        """Full rebuild — used only for reorder (Up/Down/Top) and Collapse/Expand All."""
        vl = container.layout()
        while vl.count():
            item = vl.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        for key in keys:
            row = row_factory(key)
            vl.addWidget(row)
            self._row_widgets[key] = row
        if vl.count() == 0:
            self._add_empty_label(container)

    # ---- Global actions -----------------------------------------------------

    def _collapse_all(self) -> None:
        """Move all expanded shelves to collapsed (pinned are immune)."""
        for key in list(self._expanded):
            self._expanded.remove(key)
            if key not in self._collapsed:
                self._collapsed.append(key)
        self._reload_section(self._expanded_list, self._expanded, self._build_expanded_row)
        self._reload_section(self._collapsed_list, self._collapsed, self._build_collapsed_row)
        self._commit()

    def _expand_all(self) -> None:
        """Move all collapsed shelves to expanded."""
        for key in list(self._collapsed):
            self._collapsed.remove(key)
            if key not in self._expanded:
                self._expanded.append(key)
        self._reload_section(self._collapsed_list, self._collapsed, self._build_collapsed_row)
        self._reload_section(self._expanded_list, self._expanded, self._build_expanded_row)
        self._commit()
