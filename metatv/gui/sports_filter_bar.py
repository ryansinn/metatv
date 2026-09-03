"""Sports-specific cascade filter bar and hierarchical filter dropdown."""

from typing import Dict, List, Optional

from PyQt6.QtWidgets import (
    QLineEdit,
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QMenu, QCheckBox, QScrollArea, QFrame, QWidgetAction,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QFont

from metatv.gui.filter_bar import (
    DROPDOWN_CLEAR_LABEL, DROPDOWN_SELECT_ALL_LABEL,
)
from metatv.gui import theme as _theme
from metatv.gui.filter_bar import ToggleChip
from metatv.gui.flow_layout import FlowContainer
from metatv.gui.icons import VECTOR_KEYS


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
        _theme.style(self, "FILTER_CONTROL_BTN")

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
            _theme.style_fn(placeholder, lambda: f"color: {_theme.COLOR_TEXT}; padding: 4px;")
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
        select_all = QPushButton(DROPDOWN_SELECT_ALL_LABEL)
        select_all.clicked.connect(self.select_all)
        clear_btn = QPushButton(DROPDOWN_CLEAR_LABEL)
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
        _theme.style_fn(label, lambda: f"color: {_theme.COLOR_LINE}; padding: 4px 0 2px 0;")
        return label

    def _make_subsection_label(self, text: str) -> QLabel:
        label = QLabel(f"  {text}")
        font = QFont()
        font.setItalic(True)
        label.setFont(font)
        _theme.style_fn(label, lambda: f"color: {_theme.COLOR_TEXT}; padding: 1px 0 1px 20px;")
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


#: Stored ``sport_type`` values are snake_case machine tokens; these are the
#: words. "General" rather than "Unknown" — a multi-sport network genuinely has
#: no single sport, which is not a classification failure (mockup Q22).
_SPORT_WORDS = {
    "american_football": "NFL",
    "field_hockey": "Field hockey",
    "mma": "MMA",
    "unknown": "General",
}


def sport_display_name(sport: "str | None") -> str:
    """The human name for a stored ``sport_type``."""
    if not sport:
        return _SPORT_WORDS["unknown"]
    return _SPORT_WORDS.get(sport, sport.replace("_", " ").capitalize())


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

        # The sport axis is a strip of icon buttons, not a dropdown. Owner's
        # call: the cascade "is clunky, it's the old style". An icon carries the
        # facet at a glance, and the SAME vocabulary appears in the row gutter —
        # press the ball and the rows still wearing it are what remain.
        #
        # ToggleChip already renders a tinted vector icon from a `vector_role`,
        # and FlowContainer already wraps and reports its height, so nothing new
        # was built here.
        self._strip_host = QWidget(self)
        self._sport_strip = FlowContainer(self._strip_host, spacing=4)
        self._sport_chips: "dict[str, ToggleChip]" = {}
        self._strip_host.setMinimumHeight(30)
        layout.addWidget(self._strip_host, 1)

        layout.addWidget(QLabel("League:"))
        self.league_dropdown = HierarchicalFilterDropdown("All Leagues")
        self.league_dropdown.filter_changed.connect(self._on_league_changed)
        layout.addWidget(self.league_dropdown)

        # Search narrows WITHIN the active lane and chips (mockup Q6) — a
        # further filter, never a jump to a global result set.
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter results…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMaximumWidth(200)
        self.search_input.textChanged.connect(lambda _t: self.filter_changed.emit())
        layout.addWidget(self.search_input)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _rebuild_sport_chips(self, sports, counts) -> None:
        """Rebuild the strip for the sports present, preserving selections.

        Selections survive a taxonomy reload because a refresh must not silently
        widen the user's filter back to everything.
        """
        selected = {name for name, chip in self._sport_chips.items() if chip.isChecked()}
        self._sport_strip.clear()
        self._sport_chips.clear()
        for sport in sports:
            role = f"sport_{sport}"
            chip = ToggleChip(
                sport_display_name(sport),
                enabled=(sport in selected),
                vector_role=role if role in VECTOR_KEYS else None,
            )
            chip.set_count(counts.get(sport, 0))
            chip.setToolTip(f"Show only {sport_display_name(sport)}")
            chip.clicked.connect(self._on_sport_changed)
            self._sport_chips[sport] = chip
            self._sport_strip.add(chip)
            chip.show()
        self._reflow_strip()

    def _reflow_strip(self) -> None:
        """Lay the chips out for the current width and size the host to fit."""
        width = max(self._strip_host.width(), 200)
        height = self._sport_strip.relayout(width)
        self._strip_host.setMinimumHeight(max(height, 30))

    def resizeEvent(self, event):  # noqa: N802 (Qt override)
        """Reflow on resize — sixteen chips do not fit one line on a narrow window."""
        super().resizeEvent(event)
        self._reflow_strip()

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

        # Biggest first: the strip is read left to right, and the sports the
        # library actually holds should be the ones under the cursor. General
        # sorts with the rest rather than being pinned — it is a real facet.
        order = sorted(counts, key=lambda sp: (-counts.get(sp, 0), sp))
        self._rebuild_sport_chips(order, counts)

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
        sport_sel = [name for name, chip in self._sport_chips.items() if chip.isChecked()]
        sport_total = len(self._sport_chips)
        # None selected and ALL selected both mean "no filter" — the second so a
        # WHERE IN never silently drops rows whose sport_type is NULL.
        sport_types = [] if (not sport_sel or len(sport_sel) == sport_total) else sport_sel

        league_sel = self.league_dropdown.get_selected()
        league_total = len(self.league_dropdown._all_items)
        league_names = [] if (not league_sel or len(league_sel) == league_total) else league_sel

        return {
            'sport_types': sport_types,
            'league_names': league_names,
            'search': self.search_input.text().strip(),
        }

    def clear_filters(self) -> None:
        """Reset every filter to show everything.

        Clearing means UNCHECKING the strip, not checking all of it: none
        selected and all selected both read as "no filter", and an empty strip
        is the one a user can tell at a glance is not filtering.
        """
        for chip in self._sport_chips.values():
            chip.blockSignals(True)
            chip.setChecked(False)
            chip.blockSignals(False)
        self.search_input.blockSignals(True)
        self.search_input.clear()
        self.search_input.blockSignals(False)
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

        # Restore sport selections. A saved sport the taxonomy no longer holds
        # is dropped silently — the source may simply have stopped carrying it.
        for name, chip in self._sport_chips.items():
            chip.blockSignals(True)
            chip.setChecked(name in saved_sports)
            chip.blockSignals(False)
        if (saved_search := state.get("search", "")):
            self.search_input.blockSignals(True)
            self.search_input.setText(saved_search)
            self.search_input.blockSignals(False)

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
        """Selected sports, or every sport when none is picked.

        None selected means "no filter", so the League list must widen to every
        league rather than collapsing to nothing.
        """
        selected = {n for n, c in self._sport_chips.items() if c.isChecked()}
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

