"""Discover shelf management dialog.

Four sections mirroring the zone model:
  1. Pinned shelves  — Move to Top / Up / Down; Unpin
  2. Active shelves  — same reorder; Pin / Collapse; shows preference score
  3. Collapsed shelves — Expand / Pin
  4. Hidden shelves  — Restore (the only recovery path)

Global actions: Collapse all / Expand all (pinned shelves immune to Collapse all).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
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

    def __init__(self, shelf_key: str, display_title: str,
                 parent=None) -> None:
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
        btn.clicked.connect(slot)
        self.layout().addWidget(btn)
        self._buttons.append(btn)
        return btn


class DiscoverManageDialog(QDialog):
    """Shelf management: reorder, pin/collapse/hide, restore hidden."""

    def __init__(self, db: Database, config: Config,
                 shelf_widgets: dict, shelf_zones: dict,
                 parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._config = config
        # Work on copies so Cancel discards changes
        self._pinned:   list[str] = list(config.discover_pinned_shelves)
        self._expanded: list[str] = list(config.discover_expanded_shelves)
        self._collapsed: list[str] = list(config.discover_collapsed_shelves)
        self._hidden:   list[str] = list(config.discover_hidden_shelves)

        # Build display names from live shelf_widgets (already loaded)
        self._titles: dict[str, str] = {}
        for key, shelf in shelf_widgets.items():
            self._titles[key] = shelf._title_lbl.text().replace("<b>", "").replace("</b>", "")

        # Any shelf in zones but not yet in any list (first-launch unconfigured) → add to expanded
        for key, zone in shelf_zones.items():
            if (key not in self._pinned and key not in self._expanded
                    and key not in self._collapsed and key not in self._hidden):
                if zone == _ZONE_PINNED:
                    self._pinned.append(key)
                elif zone == _ZONE_EXPANDED:
                    self._expanded.append(key)
                else:
                    self._collapsed.append(key)

        self.setWindowTitle("Manage Discovery Shelves")
        self.setMinimumSize(500, 600)
        self._setup_ui()

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

        # Scrollable section area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        inner_vl = QVBoxLayout(inner)
        inner_vl.setSpacing(4)

        # Section 1: Pinned
        inner_vl.addWidget(_section_label(f"📌 Pinned shelves"))
        self._pinned_list = self._make_list(inner_vl, self._pinned,
                                            self._build_pinned_row)
        inner_vl.addWidget(_divider())

        # Section 2: Active (expanded)
        inner_vl.addWidget(_section_label("Active shelves"))
        self._expanded_list = self._make_list(inner_vl, self._expanded,
                                              self._build_expanded_row)
        inner_vl.addWidget(_divider())

        # Section 3: Collapsed
        inner_vl.addWidget(_section_label("── Collapsed shelves ──"))
        self._collapsed_list = self._make_list(inner_vl, self._collapsed,
                                               self._build_collapsed_row)
        inner_vl.addWidget(_divider())

        # Section 4: Hidden
        inner_vl.addWidget(_section_label("🚫 Hidden shelves"))
        self._hidden_list = self._make_list(inner_vl, self._hidden,
                                            self._build_hidden_row)
        inner_vl.addStretch()

        scroll.setWidget(inner)
        vl.addWidget(scroll)

        # OK / Cancel
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save_and_accept)
        buttons.rejected.connect(self.reject)
        vl.addWidget(buttons)

    def _make_list(self, parent_layout: QVBoxLayout, keys: list[str], row_factory) -> QWidget:
        container = QWidget()
        vl = QVBoxLayout(container)
        vl.setContentsMargins(8, 0, 0, 0)
        vl.setSpacing(2)
        for key in keys:
            row = row_factory(key)
            if row:
                vl.addWidget(row)
        if vl.count() == 0:
            empty = QLabel("(none)")
            empty.setStyleSheet("color: #555; font-size: 11px; padding: 2px 0;")
            vl.addWidget(empty)
        parent_layout.addWidget(container)
        return container

    def _build_pinned_row(self, key: str) -> _ShelfRow | None:
        title = self._titles.get(key, key)
        row = _ShelfRow(key, f"📌 {title}")
        row.add_button("↑↑ Top", lambda: self._move_top(self._pinned, key, self._reload_pinned), "Move to top")
        row.add_button("↑ Up",   lambda: self._move_up(self._pinned, key, self._reload_pinned))
        row.add_button("↓ Down", lambda: self._move_down(self._pinned, key, self._reload_pinned))
        row.add_button("Unpin",  lambda: self._transfer(key, self._pinned, self._expanded,
                                                         self._reload_pinned, self._reload_expanded))
        return row

    def _build_expanded_row(self, key: str) -> _ShelfRow | None:
        title = self._titles.get(key, key)
        row = _ShelfRow(key, title)
        row.add_button("↑↑ Top", lambda: self._move_top(self._expanded, key, self._reload_expanded))
        row.add_button("↑ Up",   lambda: self._move_up(self._expanded, key, self._reload_expanded))
        row.add_button("↓ Down", lambda: self._move_down(self._expanded, key, self._reload_expanded))
        row.add_button("Pin",    lambda: self._transfer(key, self._expanded, self._pinned,
                                                         self._reload_expanded, self._reload_pinned))
        row.add_button("Collapse", lambda: self._transfer(key, self._expanded, self._collapsed,
                                                           self._reload_expanded, self._reload_collapsed))
        return row

    def _build_collapsed_row(self, key: str) -> _ShelfRow | None:
        title = self._titles.get(key, key)
        row = _ShelfRow(key, title)
        row.add_button("Expand", lambda: self._transfer(key, self._collapsed, self._expanded,
                                                         self._reload_collapsed, self._reload_expanded))
        row.add_button("Pin",    lambda: self._transfer(key, self._collapsed, self._pinned,
                                                         self._reload_collapsed, self._reload_pinned))
        row.add_button("Hide",   lambda: self._transfer(key, self._collapsed, self._hidden,
                                                         self._reload_collapsed, self._reload_hidden))
        return row

    def _build_hidden_row(self, key: str) -> _ShelfRow | None:
        title = self._titles.get(key, key)
        row = _ShelfRow(key, title)
        row.add_button("Restore", lambda: self._transfer(key, self._hidden, self._collapsed,
                                                          self._reload_hidden, self._reload_collapsed))
        return row

    # ---- List operations ----------------------------------------------------

    def _move_top(self, lst: list[str], key: str, reload_fn) -> None:
        if key in lst:
            lst.remove(key)
            lst.insert(0, key)
            reload_fn()

    def _move_up(self, lst: list[str], key: str, reload_fn) -> None:
        idx = lst.index(key) if key in lst else -1
        if idx > 0:
            lst[idx], lst[idx - 1] = lst[idx - 1], lst[idx]
            reload_fn()

    def _move_down(self, lst: list[str], key: str, reload_fn) -> None:
        idx = lst.index(key) if key in lst else -1
        if 0 <= idx < len(lst) - 1:
            lst[idx], lst[idx + 1] = lst[idx + 1], lst[idx]
            reload_fn()

    def _transfer(self, key: str, src: list[str], dst: list[str],
                  reload_src, reload_dst) -> None:
        if key in src:
            src.remove(key)
        if key not in dst:
            dst.append(key)
        reload_src()
        reload_dst()

    # ---- Reload section contents --------------------------------------------

    def _reload_section(self, container: QWidget, keys: list[str], row_factory) -> None:
        vl = container.layout()
        while vl.count():
            item = vl.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for key in keys:
            row = row_factory(key)
            if row:
                vl.addWidget(row)
        if vl.count() == 0:
            empty = QLabel("(none)")
            empty.setStyleSheet("color: #555; font-size: 11px; padding: 2px 0;")
            vl.addWidget(empty)

    def _reload_pinned(self)   -> None: self._reload_section(self._pinned_list,   self._pinned,   self._build_pinned_row)
    def _reload_expanded(self) -> None: self._reload_section(self._expanded_list, self._expanded, self._build_expanded_row)
    def _reload_collapsed(self)-> None: self._reload_section(self._collapsed_list, self._collapsed, self._build_collapsed_row)
    def _reload_hidden(self)   -> None: self._reload_section(self._hidden_list,   self._hidden,   self._build_hidden_row)

    # ---- Global actions -----------------------------------------------------

    def _collapse_all(self) -> None:
        """Move all expanded shelves to collapsed (pinned are immune)."""
        for key in list(self._expanded):
            self._expanded.remove(key)
            if key not in self._collapsed:
                self._collapsed.append(key)
        self._reload_expanded()
        self._reload_collapsed()

    def _expand_all(self) -> None:
        """Move all collapsed shelves to expanded."""
        for key in list(self._collapsed):
            self._collapsed.remove(key)
            if key not in self._expanded:
                self._expanded.append(key)
        self._reload_collapsed()
        self._reload_expanded()

    # ---- Save ---------------------------------------------------------------

    def _save_and_accept(self) -> None:
        cfg = self._config
        cfg.discover_pinned_shelves   = list(self._pinned)
        cfg.discover_expanded_shelves = list(self._expanded)
        cfg.discover_collapsed_shelves = list(self._collapsed)
        cfg.discover_hidden_shelves   = list(self._hidden)
        cfg.save()
        self.accept()
