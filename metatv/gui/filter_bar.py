"""Filter bar widget for channel filtering"""

from typing import List, Dict, Optional, Callable
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QMenu, QCheckBox, QScrollArea, QFrame, QWidgetAction
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QCursor
from loguru import logger


class ToggleChip(QPushButton):
    """Toggle chip button for simple on/off filtering"""
    
    def __init__(self, label: str, enabled: bool = True):
        super().__init__()
        self.label = label
        self._enabled = enabled
        self._count = None  # Optional count badge
        self.setCheckable(True)
        self.setChecked(enabled)
        self.update_appearance()
        self.clicked.connect(self.on_clicked)
    
    def on_clicked(self):
        """Handle click and update appearance"""
        self._enabled = self.isChecked()
        self.update_appearance()
    
    def set_count(self, count: int):
        """Set badge count to display"""
        self._count = count if count > 0 else None
        self.update_appearance()
    
    def update_appearance(self):
        """Update button appearance based on state"""
        # Build label with optional count badge
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
                QPushButton:hover {
                    background-color: #5599ff;
                }
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
                QPushButton:hover {
                    background-color: #d0d0d0;
                }
            """)
    
    def is_enabled(self) -> bool:
        """Check if chip is enabled"""
        return self._enabled
    
    def set_enabled(self, enabled: bool):
        """Set chip enabled state without triggering signals"""
        self._enabled = enabled
        # Block signals to prevent triggering on_filter_changed during restore
        self.blockSignals(True)
        self.setChecked(enabled)
        self.blockSignals(False)
        self.update_appearance()


class FilterDropdown(QPushButton):
    """Dropdown button with multi-select checkboxes"""
    
    filter_changed = pyqtSignal()
    
    def __init__(self, label: str, groups: Dict[str, int], all_selected: bool = True):
        """
        Args:
            label: Button label (e.g., "Languages", "Quality")
            groups: Dict mapping group name to count (e.g., {"English": 45234, "Arabic": 23156})
            all_selected: Whether all groups start selected (include-by-default)
        """
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
            QPushButton:hover {
                background-color: #f5f5f5;
                color: #333333;
            }
        """)
        
        self.menu = QMenu(self)
        self.checkboxes = {}
        
        self.setup_menu()
        self.clicked.connect(self.show_menu)
    
    def setup_menu(self):
        """Create menu with checkboxes"""
        # Create scroll area for long lists
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(300)
        scroll.setMaximumHeight(400)
        
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        
        # Add checkboxes for each group
        for group_name in sorted(self.groups.keys()):
            count = self.groups[group_name]
            checkbox = QCheckBox(f"{group_name} ({count:,})")
            checkbox.setChecked(group_name in self.selected_groups)
            checkbox.stateChanged.connect(lambda state, name=group_name: self.on_checkbox_changed(name, state))
            self.checkboxes[group_name] = checkbox
            layout.addWidget(checkbox)
        
        # Add separator
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)
        
        # Add Select All / Clear buttons
        button_layout = QHBoxLayout()
        
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(self.select_all)
        button_layout.addWidget(select_all_btn)
        
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.clear_all)
        button_layout.addWidget(clear_btn)
        
        layout.addLayout(button_layout)
        
        scroll.setWidget(container)
        
        # Add scroll area to menu using QWidgetAction
        widget_action = QWidgetAction(self.menu)
        widget_action.setDefaultWidget(scroll)
        self.menu.addAction(widget_action)
    
    def show_menu(self):
        """Show dropdown menu"""
        self.menu.exec(QCursor.pos())
    
    def on_checkbox_changed(self, group_name: str, state: int):
        """Handle checkbox state change"""
        if state == Qt.CheckState.Checked.value:
            self.selected_groups.add(group_name)
        else:
            self.selected_groups.discard(group_name)
        
        self.update_button_label()
        self.filter_changed.emit()
    
    def select_all(self):
        """Select all groups"""
        self.selected_groups = set(self.groups.keys())
        for checkbox in self.checkboxes.values():
            checkbox.setChecked(True)
        self.update_button_label()
        self.filter_changed.emit()
    
    def clear_all(self):
        """Clear all groups"""
        self.selected_groups.clear()
        for checkbox in self.checkboxes.values():
            checkbox.setChecked(False)
        self.update_button_label()
        self.filter_changed.emit()
    
    def update_button_label(self):
        """Update button label to show selection count"""
        total = len(self.groups)
        selected = len(self.selected_groups)
        
        if selected == total:
            self.setText(f"{self.label} ▼")
        elif selected == 0:
            self.setText(f"{self.label} (None) ▼")
        else:
            self.setText(f"{self.label} ({selected}/{total}) ▼")
    
    def get_selected(self) -> List[str]:
        """Get list of selected group names"""
        return list(self.selected_groups)
    
    def update_groups(self, groups: Dict[str, int]):
        """Update available groups and their counts"""
        self.groups = groups
        # Rebuild menu
        self.menu.clear()
        self.checkboxes.clear()
        self.setup_menu()
        self.update_button_label()


class FilterBar(QWidget):
    """Filter bar widget with toggle chips, dropdowns, and stats"""
    
    filter_changed = pyqtSignal()
    
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.show_excluded_mode = False
        self._restoring_state = False  # Flag to prevent save during restore
        
        self.setup_ui()
        self.restore_state()
    
    def setup_ui(self):
        """Setup filter bar UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # Row 1: Complex filter dropdowns
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filters:"))
        
        # These will be populated with actual data later
        self.language_dropdown = FilterDropdown("Languages", {})
        self.language_dropdown.filter_changed.connect(self.on_filter_changed)
        filter_row.addWidget(self.language_dropdown)
        
        self.quality_dropdown = FilterDropdown("Quality", {})
        self.quality_dropdown.filter_changed.connect(self.on_filter_changed)
        filter_row.addWidget(self.quality_dropdown)
        
        self.platform_dropdown = FilterDropdown("Platforms", {})
        self.platform_dropdown.filter_changed.connect(self.on_filter_changed)
        filter_row.addWidget(self.platform_dropdown)
        
        filter_row.addStretch()
        layout.addLayout(filter_row)
        
        # Row 2: Action buttons
        button_row = QHBoxLayout()
        
        self.show_excluded_btn = QPushButton("Show Excluded")
        self.show_excluded_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff8844;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background-color: #ff9955;
            }
        """)
        self.show_excluded_btn.clicked.connect(self.toggle_show_excluded)
        button_row.addWidget(self.show_excluded_btn)
        
        self.clear_filters_btn = QPushButton("Clear Filters")
        self.clear_filters_btn.setStyleSheet("""
            QPushButton {
                background-color: #e0e0e0;
                color: #333333;
                border: 1px solid #cccccc;
                border-radius: 4px;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background-color: #d0d0d0;
                color: #333333;
            }
        """)
        self.clear_filters_btn.clicked.connect(self.clear_filters)
        button_row.addWidget(self.clear_filters_btn)
        
        button_row.addStretch()
        layout.addLayout(button_row)
        
        # Create stats label for external use (displayed in main window)
        self.stats_label = QLabel("Showing 0 of 0 channels")
        self.stats_label.setStyleSheet("color: #666666; font-size: 12px;")
    
    def update_stats(self, shown: int, total: int, filtered: int):
        """Update filter statistics display"""
        self.stats_label.setText(f"Showing {shown:,} of {total:,} · {filtered:,} filtered out")
    
    def update_filter_groups(self, language_groups: Dict[str, int],
                            quality_groups: Dict[str, int],
                            platform_groups: Dict[str, int]):
        """Update available filter groups with counts"""
        self.language_dropdown.update_groups(language_groups)
        self.quality_dropdown.update_groups(quality_groups)
        self.platform_dropdown.update_groups(platform_groups)
    
    def get_enabled_media_types(self) -> List[str]:
        """Get list of enabled media types (deprecated - now in MainWindow)"""
        # This method is kept for backwards compatibility but is no longer used
        # Media types are now managed by MainWindow's chips
        return []
    
    def get_filter_state(self) -> Dict:
        """Get current filter state
        
        Returns:
            Dict with filter configuration:
            - media_types: Empty list (managed by MainWindow)
            - language_groups: List of selected language groups
            - quality_groups: List of selected quality groups
            - platform_groups: List of selected platform groups
            - show_excluded: Whether in show excluded mode
        """
        return {
            'media_types': [],  # Managed by MainWindow chips
            'language_groups': self.language_dropdown.get_selected(),
            'quality_groups': self.quality_dropdown.get_selected(),
            'platform_groups': self.platform_dropdown.get_selected(),
            'show_excluded': self.show_excluded_mode
        }
    
    def on_filter_changed(self):
        """Handle any filter change"""
        logger.debug(f"Filter changed: {self.get_filter_state()}")
        if not self._restoring_state:
            self.save_state()
        self.filter_changed.emit()
    
    def toggle_show_excluded(self):
        """Toggle show excluded mode"""
        self.show_excluded_mode = not self.show_excluded_mode
        
        if self.show_excluded_mode:
            self.show_excluded_btn.setText("Show Included")
            self.show_excluded_btn.setStyleSheet("""
                QPushButton {
                    background-color: #44ff88;
                    color: black;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 12px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #55ff99;
                }
            """)
        else:
            self.show_excluded_btn.setText("Show Excluded")
            self.show_excluded_btn.setStyleSheet("""
                QPushButton {
                    background-color: #ff8844;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 12px;
                }
                QPushButton:hover {
                    background-color: #ff9955;
                }
            """)
        
        logger.info(f"Show excluded mode: {self.show_excluded_mode}")
        self.filter_changed.emit()
    
    def clear_filters(self):
        """Reset all filters to default (all enabled)"""
        # Note: Media type chips are in MainWindow and need to be reset there
        # Signal main window to reset chips through parent
        if self.parent():
            parent = self.parent()
            if hasattr(parent, 'live_chip'):
                parent.live_chip.set_enabled(True)
            if hasattr(parent, 'movies_chip'):
                parent.movies_chip.set_enabled(True)
            if hasattr(parent, 'series_chip'):
                parent.series_chip.set_enabled(True)
        
        # Reset complex filters to all selected
        self.language_dropdown.select_all()
        self.quality_dropdown.select_all()
        self.platform_dropdown.select_all()
        
        # Reset show excluded mode
        if self.show_excluded_mode:
            self.toggle_show_excluded()
        
        logger.info("Filters cleared - all enabled")
        self.save_state()
        self.filter_changed.emit()
    
    def save_state(self):
        """Save current filter state to config"""
        try:
            state = self.get_filter_state()
            
            # Get media types from parent MainWindow
            if self.parent() and hasattr(self.parent(), 'get_enabled_media_types'):
                state['media_types'] = self.parent().get_enabled_media_types()
            
            self.config.filter_enabled_media_types = state['media_types']
            self.config.filter_included_languages = state['language_groups']
            self.config.filter_included_qualities = state['quality_groups']
            self.config.filter_included_platforms = state['platform_groups']
            self.config.save()
            logger.debug(f"Saved filter state: {state}")
        except Exception as e:
            logger.warning(f"Could not save filter state: {e}")
    
    def restore_state(self):
        """Restore filter state from config"""
        self._restoring_state = True
        try:
            # Note: Media types are restored in MainWindow
            
            # Restore dropdown selections (only if checkboxes exist)
            # Note: The actual checkbox update happens in update_filter_groups when data is available
            included_languages = getattr(self.config, 'filter_included_languages', [])
            if included_languages:
                self.language_dropdown.selected_groups = set(included_languages)
            
            included_qualities = getattr(self.config, 'filter_included_qualities', [])
            if included_qualities:
                self.quality_dropdown.selected_groups = set(included_qualities)
            
            included_platforms = getattr(self.config, 'filter_included_platforms', [])
            if included_platforms:
                self.platform_dropdown.selected_groups = set(included_platforms)
            
            logger.info("Restored filter state")
        except Exception as e:
            logger.warning(f"Could not restore filter state: {e}")
        finally:
            self._restoring_state = False
