"""Filter bar widget for channel filtering"""

from typing import List, Dict, Optional
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QMenu, QCheckBox, QScrollArea, QFrame, QWidgetAction, QComboBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCursor
from loguru import logger


class ToggleChip(QPushButton):
    """Toggle chip button for simple on/off filtering"""

    toggled_changed = pyqtSignal(bool)

    def __init__(self, label: str, enabled: bool = True):
        super().__init__()
        self.label = label
        self._enabled = enabled
        self._count = None
        self.setCheckable(True)
        self.setChecked(enabled)
        self.update_appearance()
        self.clicked.connect(self.on_clicked)

    def on_clicked(self):
        self._enabled = self.isChecked()
        self.update_appearance()
        self.toggled_changed.emit(self._enabled)

    def set_count(self, count: int):
        self._count = count if count > 0 else None
        self.update_appearance()

    def update_appearance(self):
        label_text = self.label
        if self._count is not None:
            label_text = f"{self.label} ({self._count})"

        if self._enabled:
            self.setText(f"{label_text} ●")
            self.setStyleSheet("""
                QPushButton {
                    background-color: #4488ff;
                    color: white;
                    border: none;
                    border-radius: 12px;
                    padding: 6px 14px;
                    font-weight: bold;
                }
                QPushButton:hover { background-color: #5599ff; }
            """)
        else:
            self.setText(f"{label_text} ○")
            self.setStyleSheet("""
                QPushButton {
                    background-color: #e0e0e0;
                    color: #666666;
                    border: 1px solid #cccccc;
                    border-radius: 12px;
                    padding: 6px 14px;
                }
                QPushButton:hover { background-color: #d0d0d0; }
            """)

    def is_enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        self.blockSignals(True)
        self.setChecked(enabled)
        self.blockSignals(False)
        self.update_appearance()


class FilterChip(ToggleChip):
    """Three-state chip for the global content filter.

    States:
      no-filter  — gray ○, click opens dialog
      active     — teal ●, click pauses, right-click opens dialog
      paused     — amber ●, click resumes, right-click opens dialog

    toggled_changed(bool):
      True  = filter should be active (resume)
      False = filter should be paused
    open_dialog_requested = right-click or click-when-no-filters
    """

    open_dialog_requested = pyqtSignal()

    _ACTIVE_STYLE = """
        QPushButton {
            background-color: rgba(42, 157, 143, 0.10);
            color: #2a9d8f;
            border: 1px solid #2a9d8f;
            border-radius: 12px;
            padding: 6px 14px;
            font-weight: bold;
        }
        QPushButton:hover { background-color: rgba(42, 157, 143, 0.18); }
    """
    _PAUSED_STYLE = """
        QPushButton {
            background-color: rgba(240, 160, 64, 0.10);
            color: #f0a040;
            border: 1px solid #f0a040;
            border-radius: 12px;
            padding: 6px 14px;
            font-weight: bold;
        }
        QPushButton:hover { background-color: rgba(240, 160, 64, 0.18); }
    """

    def __init__(self, label: str):
        super().__init__(label, enabled=False)
        self._paused = False
        self._has_filters = False
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda _: self.open_dialog_requested.emit()
        )
        self.setToolTip("Content category filters — click to configure")

    def set_filter_state(self, has_filters: bool, paused: bool) -> None:
        self._has_filters = has_filters
        self._paused = paused
        self.blockSignals(True)
        self.set_enabled(has_filters)
        self.blockSignals(False)
        if has_filters and paused:
            self.setText(f"{self.label} ●")
            self.setStyleSheet(self._PAUSED_STYLE)
            self.setToolTip("Filters paused — click to resume · right-click to edit")
        elif has_filters:
            self.setText(f"{self.label} ●")
            self.setStyleSheet(self._ACTIVE_STYLE)
            self.setToolTip("Filters active — click to pause · right-click to edit")
        else:
            self.update_appearance()   # standard gray ○
            self.setToolTip("Content category filters — click to configure")

    def on_clicked(self) -> None:
        if self._has_filters:
            # Toggle pause/resume — keep chip lit, don't flip _enabled
            self.blockSignals(True)
            self.set_enabled(True)
            self.blockSignals(False)
            # True = resume (un-pause), False = pause
            self.toggled_changed.emit(self._paused)
        else:
            # No filters configured — open dialog
            self.open_dialog_requested.emit()


class FilterDropdown(QPushButton):
    """Dropdown button with multi-select checkboxes"""

    filter_changed = pyqtSignal()

    def __init__(self, label: str, groups: Dict[str, int], all_selected: bool = True):
        super().__init__()
        self.label = label
        self.groups = groups
        self.selected_groups: set = set(groups.keys()) if all_selected else set()

        self.setText(f"{label} ▼")
        self.setStyleSheet("""
            QPushButton {
                background-color: white;
                color: #333333;
                border: 1px solid #cccccc;
                border-radius: 4px;
                padding: 6px 12px;
                text-align: left;
            }
            QPushButton:hover { background-color: #f5f5f5; color: #333333; }
        """)

        self.menu = QMenu(self)
        self.checkboxes = {}
        self.setup_menu()
        self.clicked.connect(self.show_menu)

    def setup_menu(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(300)
        scroll.setMaximumHeight(400)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        for group_name in sorted(self.groups.keys()):
            count = self.groups[group_name]
            checkbox = QCheckBox(f"{group_name} ({count:,})")
            checkbox.setChecked(group_name in self.selected_groups)
            checkbox.stateChanged.connect(
                lambda state, name=group_name: self.on_checkbox_changed(name, state)
            )
            self.checkboxes[group_name] = checkbox
            layout.addWidget(checkbox)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)

        button_layout = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(self.select_all)
        button_layout.addWidget(select_all_btn)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.clear_all)
        button_layout.addWidget(clear_btn)
        layout.addLayout(button_layout)

        scroll.setWidget(container)
        widget_action = QWidgetAction(self.menu)
        widget_action.setDefaultWidget(scroll)
        self.menu.addAction(widget_action)

    def show_menu(self):
        self.menu.exec(QCursor.pos())

    def on_checkbox_changed(self, group_name: str, state: int):
        if state == Qt.CheckState.Checked.value:
            self.selected_groups.add(group_name)
        else:
            self.selected_groups.discard(group_name)
        self.update_button_label()
        self.filter_changed.emit()

    def select_all(self):
        self.selected_groups = set(self.groups.keys())
        for cb in self.checkboxes.values():
            cb.blockSignals(True)
            cb.setChecked(True)
            cb.blockSignals(False)
        self.update_button_label()
        self.filter_changed.emit()

    def clear_all(self):
        self.selected_groups.clear()
        for cb in self.checkboxes.values():
            cb.blockSignals(True)
            cb.setChecked(False)
            cb.blockSignals(False)
        self.update_button_label()
        self.filter_changed.emit()

    def update_button_label(self):
        total = len(self.groups)
        selected = len(self.selected_groups)
        if selected == total:
            self.setText(f"{self.label} ▼")
        elif selected == 0:
            self.setText(f"{self.label} (None) ▼")
        else:
            self.setText(f"{self.label} ({selected}/{total}) ▼")

    def get_selected(self) -> List[str]:
        return list(self.selected_groups)

    def update_groups(self, groups: Dict[str, int]):
        self.groups = groups
        self.menu.clear()
        self.checkboxes.clear()
        self.setup_menu()
        self.update_button_label()


class FilterBar(QWidget):
    """Filter bar with language/quality dropdowns, source chips, and untagged toggle."""

    filter_changed = pyqtSignal()

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.show_excluded_mode = False
        self._restoring_state = False
        self._source_chips: Dict[str, ToggleChip] = {}  # provider_id → chip

        self.setup_ui()
        self.restore_state()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Row 0: source chips (multi-provider only — hidden when ≤1 provider)
        self._source_row_widget = QWidget()
        source_row = QHBoxLayout(self._source_row_widget)
        source_row.setContentsMargins(0, 0, 0, 0)
        source_row.setSpacing(6)
        self._source_chips_label = QLabel("Sources:")
        self._source_chips_label.setStyleSheet("color: #888; font-size: 11px;")
        source_row.addWidget(self._source_chips_label)
        self._source_chips_layout = source_row
        source_row.addStretch()
        self._source_row_widget.hide()
        layout.addWidget(self._source_row_widget)

        # Row 1: filter dropdowns + untagged checkbox
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filters:"))

        self.language_dropdown = FilterDropdown("Categories", {})
        self.language_dropdown.filter_changed.connect(self.on_filter_changed)
        filter_row.addWidget(self.language_dropdown)

        self.quality_dropdown = FilterDropdown("Quality", {})
        self.quality_dropdown.filter_changed.connect(self.on_filter_changed)
        self.quality_dropdown.hide()  # shown only when quality data exists
        filter_row.addWidget(self.quality_dropdown)

        filter_row.addSpacing(12)

        self.include_untagged_check = QCheckBox("Include untagged channels")
        self.include_untagged_check.setChecked(True)
        self.include_untagged_check.setToolTip(
            "When unchecked, channels with no language prefix are hidden.\n"
            "Useful in multi-source setups where one provider uses prefixes and another does not."
        )
        self.include_untagged_check.stateChanged.connect(self.on_filter_changed)
        filter_row.addWidget(self.include_untagged_check)

        filter_row.addSpacing(12)

        # Adult content: hidden by default; shown via set_adult_filter_visible()
        self._adult_filter_widget = QWidget()
        adult_row = QHBoxLayout(self._adult_filter_widget)
        adult_row.setContentsMargins(0, 0, 0, 0)
        adult_row.setSpacing(4)
        adult_row.addWidget(QLabel("Adult content:"))
        self.adult_mode_combo = QComboBox()
        self.adult_mode_combo.addItems(["All", "Hide adult", "Adult only"])
        self.adult_mode_combo.setCurrentIndex(1)  # default: Hide adult
        self.adult_mode_combo.setToolTip(
            "All — show all channels including adult\n"
            "Hide adult — hide channels marked as adult (default)\n"
            "Adult only — show only adult-flagged channels"
        )
        self.adult_mode_combo.currentIndexChanged.connect(self.on_filter_changed)
        adult_row.addWidget(self.adult_mode_combo)
        self._adult_filter_widget.setVisible(False)  # hidden until adult content exists
        filter_row.addWidget(self._adult_filter_widget)

        filter_row.addStretch()
        layout.addLayout(filter_row)

        # Row 2: action buttons
        button_row = QHBoxLayout()

        self.show_excluded_btn = QPushButton("Show Excluded")
        self.show_excluded_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff8844; color: white;
                border: none; border-radius: 4px; padding: 6px 12px;
            }
            QPushButton:hover { background-color: #ff9955; }
        """)
        self.show_excluded_btn.clicked.connect(self.toggle_show_excluded)
        button_row.addWidget(self.show_excluded_btn)

        self.clear_filters_btn = QPushButton("Clear Filters")
        self.clear_filters_btn.setStyleSheet("""
            QPushButton {
                background-color: #e0e0e0; color: #333333;
                border: 1px solid #cccccc; border-radius: 4px; padding: 6px 12px;
            }
            QPushButton:hover { background-color: #d0d0d0; color: #333333; }
        """)
        self.clear_filters_btn.clicked.connect(self.clear_filters)
        button_row.addWidget(self.clear_filters_btn)

        button_row.addStretch()
        layout.addLayout(button_row)

        self.stats_label = QLabel("Showing 0 of 0 channels")
        self.stats_label.setStyleSheet("color: #666666; font-size: 12px;")

    # ── Source chips ──────────────────────────────────────────────────────────

    def update_source_chips(self, providers: list):
        """Rebuild source filter chips from the list of active Provider/ProviderDB objects.

        Each element should have .id, .name, and optionally .icon attributes.
        The row is hidden when len(providers) <= 1.
        """
        # Remove all old chips (keep label + stretch)
        for chip in self._source_chips.values():
            self._source_chips_layout.removeWidget(chip)
            chip.deleteLater()
        self._source_chips.clear()

        if len(providers) <= 1:
            self._source_row_widget.hide()
            return

        # Re-insert chips before the stretch
        stretch_index = self._source_chips_layout.count() - 1  # last item is stretch
        for provider in providers:
            icon = getattr(provider, 'icon', '') or ''
            name = getattr(provider, 'name', str(provider))
            label = f"{icon} {name}".strip() if icon else name
            chip = ToggleChip(label, enabled=True)
            chip.setProperty("provider_id", provider.id)
            chip.toggled_changed.connect(self.on_filter_changed)
            self._source_chips_layout.insertWidget(stretch_index, chip)
            stretch_index += 1
            self._source_chips[provider.id] = chip

        self._source_row_widget.setVisible(True)

    def get_excluded_provider_ids(self) -> List[str]:
        """Return provider IDs whose source chip is deselected."""
        return [pid for pid, chip in self._source_chips.items() if not chip.is_enabled()]

    # ── Filter groups ─────────────────────────────────────────────────────────

    def update_filter_groups(self, language_groups: Dict[str, int],
                             quality_groups: Dict[str, int]):
        """Update language and quality dropdowns; auto-hide quality when empty."""
        self.language_dropdown.update_groups(language_groups)
        self.quality_dropdown.update_groups(quality_groups)
        has_quality = any(v > 0 for v in quality_groups.values())
        self.quality_dropdown.setVisible(has_quality)

    # ── Filter state ──────────────────────────────────────────────────────────

    def update_stats(self, shown: int, total: int, filtered: int):
        self.stats_label.setText(f"Showing {shown:,} of {total:,} · {filtered:,} filtered out")

    def get_filter_state(self) -> Dict:
        return {
            'media_types': [],  # managed by MainWindow chips
            'language_groups': self.language_dropdown.get_selected(),
            'quality_groups': self.quality_dropdown.get_selected(),
            'show_excluded': self.show_excluded_mode,
            'include_untagged': self.include_untagged_check.isChecked(),
            'adult_mode': ['all', 'hide', 'only'][self.adult_mode_combo.currentIndex()],
            'excluded_provider_ids': self.get_excluded_provider_ids(),
        }

    def on_filter_changed(self):
        logger.debug(f"Filter changed: {self.get_filter_state()}")
        if not self._restoring_state:
            self.save_state()
        self.filter_changed.emit()

    def toggle_show_excluded(self):
        self.show_excluded_mode = not self.show_excluded_mode
        if self.show_excluded_mode:
            self.show_excluded_btn.setText("Show Included")
            self.show_excluded_btn.setStyleSheet("""
                QPushButton {
                    background-color: #44ff88; color: black;
                    border: none; border-radius: 4px; padding: 6px 12px; font-weight: bold;
                }
                QPushButton:hover { background-color: #55ff99; }
            """)
        else:
            self.show_excluded_btn.setText("Show Excluded")
            self.show_excluded_btn.setStyleSheet("""
                QPushButton {
                    background-color: #ff8844; color: white;
                    border: none; border-radius: 4px; padding: 6px 12px;
                }
                QPushButton:hover { background-color: #ff9955; }
            """)
        logger.info(f"Show excluded mode: {self.show_excluded_mode}")
        self.filter_changed.emit()

    def clear_filters(self):
        """Reset all filters to default (all enabled)."""
        if self.parent():
            parent = self.parent()
            for attr in ('live_chip', 'movies_chip', 'series_chip'):
                chip = getattr(parent, attr, None)
                if chip:
                    chip.set_enabled(True)

        self.language_dropdown.blockSignals(True)
        self.quality_dropdown.blockSignals(True)
        self.language_dropdown.select_all()
        self.quality_dropdown.select_all()
        self.language_dropdown.blockSignals(False)
        self.quality_dropdown.blockSignals(False)

        self.include_untagged_check.blockSignals(True)
        self.include_untagged_check.setChecked(True)
        self.include_untagged_check.blockSignals(False)

        self.adult_mode_combo.blockSignals(True)
        self.adult_mode_combo.setCurrentIndex(1)  # "Hide adult"
        self.adult_mode_combo.blockSignals(False)

        for chip in self._source_chips.values():
            chip.set_enabled(True)

        if self.show_excluded_mode:
            self.toggle_show_excluded()

        logger.info("Filters cleared — all enabled")
        self.save_state()
        self.filter_changed.emit()

    def save_state(self):
        try:
            state = self.get_filter_state()
            if self.parent() and hasattr(self.parent(), 'get_enabled_media_types'):
                state['media_types'] = self.parent().get_enabled_media_types()

            self.config.filter_enabled_media_types = state['media_types']
            self.config.filter_included_languages = state['language_groups']
            self.config.filter_included_qualities = state['quality_groups']
            self.config.filter_include_untagged = state['include_untagged']
            self.config.filter_adult_mode = state['adult_mode']
            self.config.save()
            logger.debug(f"Saved filter state: {state}")
        except Exception as e:
            logger.warning(f"Could not save filter state: {e}")

    def restore_state(self):
        self._restoring_state = True
        try:
            included_languages = getattr(self.config, 'filter_included_languages', [])
            if included_languages:
                self.language_dropdown.selected_groups = set(included_languages)

            included_qualities = getattr(self.config, 'filter_included_qualities', [])
            if included_qualities:
                self.quality_dropdown.selected_groups = set(included_qualities)

            include_untagged = getattr(self.config, 'filter_include_untagged', True)
            self.include_untagged_check.setChecked(include_untagged)

            adult_mode = getattr(self.config, 'filter_adult_mode', 'hide')
            idx = {'all': 0, 'hide': 1, 'only': 2}.get(adult_mode, 1)
            self.adult_mode_combo.setCurrentIndex(idx)

            logger.info("Restored filter state")
        except Exception as e:
            logger.warning(f"Could not restore filter state: {e}")
        finally:
            self._restoring_state = False

    def set_adult_filter_visible(self, visible: bool) -> None:
        """Show or hide the adult content filter based on whether adult channels exist."""
        self._adult_filter_widget.setVisible(visible)

    def get_enabled_media_types(self) -> List[str]:
        """Kept for backwards compatibility."""
        return []
