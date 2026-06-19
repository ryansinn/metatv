"""Sports-specific cascade filter bar and hierarchical filter dropdown."""

from typing import Dict, List, Optional

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QMenu, QCheckBox, QScrollArea, QFrame, QWidgetAction,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QFont
from loguru import logger

from metatv.gui.filter_bar import FilterDropdown
from metatv.gui import theme as _theme


class HierarchicalFilterDropdown(QPushButton):
    """Multi-select dropdown with non-selectable section/subsection headers.

    Supports two hierarchy depths:

    - **1-level** ``{section: [item, ...]}`` — used for League dropdown where
      sport names are the non-selectable section headers.
    - **2-level** ``{section: {subsection: [item, ...]}}`` — used for Team
      dropdown where sport is the bold header and league is an indented
      italic subheader.

    Selected items persist across ``update_hierarchy()`` calls so that
    cascade rebuilds (triggered when a parent filter changes) preserve the
    user's current selections.
    """

    filter_changed = pyqtSignal()

    def __init__(self, label: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.label = label
        self.selected_items: set = set()
        self._all_items: list = []
        self._rebuilding: bool = False

        self.setText(f"{label} ▼")
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: white;
                color: {_theme.COLOR_LINE};
                border: 1px solid {_theme.COLOR_TEXT};
                border-radius: 4px;
                padding: 6px 12px;
                text-align: left;
            }}
            QPushButton:hover {{
                background-color: {_theme.COLOR_SURFACE_LIGHT};
                color: {_theme.COLOR_LINE};
            }}
        """)

        self.menu = QMenu(self)
        self.checkboxes: Dict[str, QCheckBox] = {}
        self.clicked.connect(self.show_menu)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_hierarchy(self, hierarchy: Dict) -> None:
        """Rebuild the dropdown menu from a new hierarchy dict.

        Previously selected items that still exist in the new hierarchy are
        kept selected. New items are added as selected by default (inclusive).

        Args:
            hierarchy: Either ``{section: [item, ...]}`` (1-level) or
                       ``{section: {subsection: [item, ...]}}`` (2-level).
        """
        self._rebuilding = True
        try:
            # Determine depth
            is_two_level = (
                bool(hierarchy)
                and isinstance(next(iter(hierarchy.values())), dict)
            )

            # Collect all leaf items
            new_items: List[str] = []
            if is_two_level:
                for _section, subsections in hierarchy.items():
                    for _sub, items in subsections.items():
                        new_items.extend(items)
            else:
                for _section, items in hierarchy.items():
                    new_items.extend(items)

            self._all_items = new_items

            # Determine which items to keep selected:
            # - items that were previously selected AND still exist → keep
            # - new items (not previously selected) → start selected (inclusive)
            existing = set(new_items)
            preserved = self.selected_items & existing
            brand_new = existing - self.selected_items
            self.selected_items = preserved | brand_new

            # Rebuild the menu widget
            self.menu.clear()
            self.checkboxes.clear()
            self._build_menu(hierarchy, is_two_level)

        finally:
            self._rebuilding = False

        self.update_button_label()

    def get_selected(self) -> List[str]:
        """Return currently selected leaf items (not headers/subheaders)."""
        return [item for item in self._all_items if item in self.selected_items]

    def select_all(self) -> None:
        """Select all leaf items."""
        self.selected_items = set(self._all_items)
        for cb in self.checkboxes.values():
            cb.blockSignals(True)
            cb.setChecked(True)
            cb.blockSignals(False)
        self.update_button_label()
        self.filter_changed.emit()

    def clear_all(self) -> None:
        """Deselect all leaf items."""
        self.selected_items.clear()
        for cb in self.checkboxes.values():
            cb.blockSignals(True)
            cb.setChecked(False)
            cb.blockSignals(False)
        self.update_button_label()
        self.filter_changed.emit()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_menu(self, hierarchy: Dict, is_two_level: bool) -> None:
        """Populate self.menu from hierarchy. Call after clearing menu."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(320)
        scroll.setMaximumHeight(420)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        if not hierarchy:
            placeholder = QLabel("No items available")
            placeholder.setStyleSheet(f"color: {_theme.COLOR_MUTED}; padding: 4px;")
            layout.addWidget(placeholder)
        elif is_two_level:
            self._build_two_level(layout, hierarchy)
        else:
            self._build_one_level(layout, hierarchy)

        # Separator + buttons
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep)

        btn_row = QHBoxLayout()
        select_all = QPushButton("Select All")
        select_all.clicked.connect(self.select_all)
        clear_btn = QPushButton("Clear All")
        clear_btn.clicked.connect(self.clear_all)
        btn_row.addWidget(select_all)
        btn_row.addWidget(clear_btn)
        layout.addLayout(btn_row)

        scroll.setWidget(container)
        action = QWidgetAction(self.menu)
        action.setDefaultWidget(scroll)
        self.menu.addAction(action)

    def _build_one_level(self, layout: QVBoxLayout, hierarchy: Dict[str, List[str]]) -> None:
        """Build single-level hierarchy: section header → checkboxes."""
        for section in sorted(hierarchy.keys()):
            items = hierarchy[section]
            if not items:
                continue
            header = self._make_section_label(section.upper())
            layout.addWidget(header)
            for item in sorted(items):
                cb = self._make_checkbox(item, indent=20)
                layout.addWidget(cb)

    def _build_two_level(self, layout: QVBoxLayout, hierarchy: Dict[str, Dict[str, List[str]]]) -> None:
        """Build two-level hierarchy: section → subsection (italic) → checkboxes."""
        for section in sorted(hierarchy.keys()):
            subsections = hierarchy[section]
            if not subsections:
                continue
            header = self._make_section_label(section.upper())
            layout.addWidget(header)
            for subsection in sorted(subsections.keys()):
                items = subsections[subsection]
                if not items:
                    continue
                sublabel = self._make_subsection_label(subsection)
                layout.addWidget(sublabel)
                for item in sorted(items):
                    cb = self._make_checkbox(item, indent=40)
                    layout.addWidget(cb)

    def _make_section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        font = QFont()
        font.setBold(True)
        label.setFont(font)
        label.setStyleSheet(f"color: {_theme.COLOR_LINE}; padding: 4px 0 2px 0;")
        return label

    def _make_subsection_label(self, text: str) -> QLabel:
        label = QLabel(f"  {text}")
        font = QFont()
        font.setItalic(True)
        label.setFont(font)
        label.setStyleSheet(f"color: {_theme.COLOR_FAINT}; padding: 1px 0 1px 20px;")
        return label

    def _make_checkbox(self, item: str, indent: int) -> QCheckBox:
        cb = QCheckBox(item)
        cb.setChecked(item in self.selected_items)
        cb.setStyleSheet(f"padding-left: {indent}px;")
        cb.stateChanged.connect(
            lambda state, name=item: self._on_checkbox_changed(name, state)
        )
        self.checkboxes[item] = cb
        return cb

    def _on_checkbox_changed(self, item_name: str, state: int) -> None:
        if self._rebuilding:
            return
        if state == Qt.CheckState.Checked.value:
            self.selected_items.add(item_name)
        else:
            self.selected_items.discard(item_name)
        self.update_button_label()
        self.filter_changed.emit()

    def update_button_label(self) -> None:
        total = len(self._all_items)
        selected = sum(1 for item in self._all_items if item in self.selected_items)
        if total == 0 or selected == total:
            self.setText(f"{self.label} ▼")
        elif selected == 0:
            self.setText(f"{self.label} (None) ▼")
        else:
            self.setText(f"{self.label} ({selected}/{total}) ▼")

    def show_menu(self) -> None:
        self.menu.exec(QCursor.pos())


class SportsFilterBar(QWidget):
    """Two-level cascade filter bar for the Sports view: Sport → League.

    Selecting sports narrows the League list. Empty selection in either
    dropdown is treated as "no filter — show all", which also ensures
    channels with no classified league are never hidden.

    Signals:
        filter_changed: Emitted when any filter selection changes. Consumers
                        should call ``get_filter_state()`` to get current values.
    """

    filter_changed = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.taxonomy: Dict[str, Dict[str, List[str]]] = {}
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(8)

        layout.addWidget(QLabel("Sport:"))
        self.sport_dropdown = FilterDropdown("All Sports", {}, all_selected=True)
        self.sport_dropdown.filter_changed.connect(self._on_sport_changed)
        layout.addWidget(self.sport_dropdown)

        layout.addWidget(QLabel("League:"))
        self.league_dropdown = HierarchicalFilterDropdown("All Leagues")
        self.league_dropdown.filter_changed.connect(self._on_league_changed)
        layout.addWidget(self.league_dropdown)

        layout.addStretch()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_taxonomy(
        self,
        taxonomy: Dict[str, Dict[str, List[str]]],
        sport_counts: Dict[str, int] = None,
    ) -> None:
        """Populate filter dropdowns from a sports taxonomy dict.

        Args:
            taxonomy: ``{sport: {league: [team, ...]}}`` from
                      ``ChannelRepository.get_sports_taxonomy()``.
            sport_counts: Optional ``{sport: channel_count}`` for dropdown
                          badges. Falls back to league count per sport.
        """
        self.taxonomy = taxonomy

        counts = sport_counts or {
            sport: len(leagues) for sport, leagues in taxonomy.items()
        }

        # Preserve current sport selections through taxonomy reload (refresh case).
        # First load: groups dict is empty → select_all() for inclusive default.
        # Subsequent loads (refresh): restore whatever was selected, intersected
        # with sports that still exist in the new taxonomy.
        is_first_load = not bool(self.sport_dropdown.groups)
        prev_sports = set(self.sport_dropdown.get_selected())

        self.sport_dropdown.blockSignals(True)
        self.sport_dropdown.update_groups(counts)
        if is_first_load or not prev_sports:
            self.sport_dropdown.select_all()
        else:
            existing = set(counts.keys())
            to_restore = prev_sports & existing or existing
            self.sport_dropdown.selected_groups = to_restore
            for key, cb in self.sport_dropdown.checkboxes.items():
                cb.blockSignals(True)
                cb.setChecked(key in to_restore)
                cb.blockSignals(False)
            self.sport_dropdown.update_button_label()
        self.sport_dropdown.blockSignals(False)

        # League dropdown (HierarchicalFilterDropdown) self-preserves selected_items
        # across update_hierarchy() calls — no special handling needed here.
        self._rebuild_league_dropdown()

    def get_filter_state(self) -> Dict:
        """Return current filter selections for DB queries.

        When all items in a dropdown are selected (or none are selected),
        an empty list is returned so callers treat it as "no filter".
        This prevents the common mistake of passing all league names to a
        WHERE IN clause, which would silently exclude channels with no league.

        Returns:
            Dict with keys ``sport_types`` and ``league_names``.
            Empty list means "no active filter — show all".
        """
        sport_sel = self.sport_dropdown.get_selected()
        sport_total = len(self.sport_dropdown.groups)
        sport_types = [] if (not sport_sel or len(sport_sel) == sport_total) else sport_sel

        league_sel = self.league_dropdown.get_selected()
        league_total = len(self.league_dropdown._all_items)
        league_names = [] if (not league_sel or len(league_sel) == league_total) else league_sel

        return {
            'sport_types': sport_types,
            'league_names': league_names,
        }

    def clear_filters(self) -> None:
        """Reset all filters to show everything."""
        self.sport_dropdown.blockSignals(True)
        self.sport_dropdown.select_all()
        self.sport_dropdown.blockSignals(False)
        self._rebuild_league_dropdown()
        self.filter_changed.emit()

    def restore_filter_state(self, state: Dict) -> None:
        """Apply a previously saved filter state (e.g. from config).

        Called once after the first taxonomy load to restore the user's
        last session selections. Items from the saved state that no longer
        exist in the current taxonomy are silently ignored.

        Args:
            state: Dict with keys ``sport_types`` and ``league_names``
                   as returned by ``get_filter_state()``. Empty lists
                   mean "no active filter — show all" (i.e. all selected).
        """
        saved_sports = set(state.get('sport_types', []))
        saved_leagues = set(state.get('league_names', []))

        # Restore sport selections
        self.sport_dropdown.blockSignals(True)
        if saved_sports:
            existing = set(self.sport_dropdown.groups.keys())
            to_restore = saved_sports & existing
            if to_restore:
                self.sport_dropdown.selected_groups = to_restore
                for key, cb in self.sport_dropdown.checkboxes.items():
                    cb.blockSignals(True)
                    cb.setChecked(key in to_restore)
                    cb.blockSignals(False)
                self.sport_dropdown.update_button_label()
        self.sport_dropdown.blockSignals(False)

        # Inject saved league selection before rebuild so update_hierarchy()
        # preserves them (it keeps items in selected_items that still exist).
        if saved_leagues:
            self.league_dropdown.selected_items = saved_leagues

        self._rebuild_league_dropdown()

    # ------------------------------------------------------------------
    # Cascade logic
    # ------------------------------------------------------------------

    def _on_sport_changed(self) -> None:
        self._rebuild_league_dropdown()
        self.filter_changed.emit()

    def _on_league_changed(self) -> None:
        self.filter_changed.emit()

    def _active_sports(self) -> set:
        """Return selected sports, or all sports when nothing is deselected."""
        selected = set(self.sport_dropdown.get_selected())
        return selected if selected else set(self.taxonomy.keys())

    def _rebuild_league_dropdown(self) -> None:
        """Rebuild League dropdown to show only leagues for active sports."""
        active = self._active_sports()
        hierarchy: Dict[str, List[str]] = {
            sport: sorted(self.taxonomy[sport].keys())
            for sport in active
            if sport in self.taxonomy and self.taxonomy[sport]
        }
        self.league_dropdown.blockSignals(True)
        self.league_dropdown.update_hierarchy(hierarchy)
        self.league_dropdown.blockSignals(False)

