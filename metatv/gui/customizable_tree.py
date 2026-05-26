"""
Customizable tree widget with column visibility and reordering support.

This module provides a reusable framework for QTreeWidget views with:
- Right-click header to toggle column visibility
- Drag columns to reorder
- Persist column configuration to config
- Easy integration with any tree view
"""

from PyQt6.QtWidgets import QTreeWidget, QMenu, QHeaderView
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction
from loguru import logger
from typing import List, Dict, Optional


class ColumnConfig:
    """Configuration for a single column"""
    def __init__(self, key: str, label: str, width: int = 100, visible: bool = True):
        self.key = key  # Unique identifier
        self.label = label  # Display name
        self.width = width  # Column width in pixels
        self.visible = visible  # Whether column is currently visible
        self.index = 0  # Current position in tree


class CustomizableTreeWidget(QTreeWidget):
    """
    QTreeWidget with customizable columns.
    
    Usage:
        tree = CustomizableTreeWidget()
        tree.setup_columns([
            ColumnConfig("title", "Title", 400, True),
            ColumnConfig("episode", "Episode", 80, True),
            ColumnConfig("runtime", "Runtime", 80, True),
            ColumnConfig("rating", "Rating", 80, False),  # Hidden by default
            ColumnConfig("year", "Year", 60, False),
        ])
        
        # Populate tree
        item = QTreeWidgetItem(tree)
        tree.set_column_data(item, {
            "title": "Episode Title",
            "episode": "E01",
            "runtime": "45:00",
            "rating": "★ 8.5",
            "year": "2024"
        })
    """
    
    columns_changed = pyqtSignal()  # Emitted when columns are reordered or visibility changes
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.columns: List[ColumnConfig] = []
        self.column_map: Dict[str, ColumnConfig] = {}  # key -> ColumnConfig
        self.view_name: Optional[str] = None  # For config persistence
        
        # Enable header context menu
        header = self.header()
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_header_menu)
        header.setSectionsMovable(True)  # Allow drag-and-drop reordering
        header.sectionMoved.connect(self._on_column_moved)
    
    def setup_columns(self, columns: List[ColumnConfig], view_name: Optional[str] = None):
        """
        Initialize tree with column configuration.
        
        Args:
            columns: List of ColumnConfig objects defining available columns
            view_name: Unique name for this view (for config persistence)
        """
        self.columns = columns
        self.column_map = {col.key: col for col in columns}
        self.view_name = view_name
        
        # Set header labels for visible columns
        visible_cols = [col for col in columns if col.visible]
        labels = [col.label for col in visible_cols]
        self.setHeaderLabels(labels)
        
        # Set column widths
        for i, col in enumerate(visible_cols):
            self.setColumnWidth(i, col.width)
            col.index = i
        
        logger.debug(f"Setup {len(visible_cols)} visible columns out of {len(columns)} total")
    
    def set_column_data(self, item, data: Dict[str, str]):
        """
        Set data for all columns in an item.
        
        Args:
            item: QTreeWidgetItem to populate
            data: Dict mapping column keys to display values
        """
        visible_cols = [col for col in self.columns if col.visible]
        for i, col in enumerate(visible_cols):
            value = data.get(col.key, "")
            if value:
                item.setText(i, str(value))
    
    def _show_header_menu(self, position):
        """Show context menu for column visibility"""
        menu = QMenu(self)
        
        # Add toggle actions for each column
        for col in self.columns:
            action = QAction(col.label, menu)
            action.setCheckable(True)
            action.setChecked(col.visible)
            action.triggered.connect(lambda checked, c=col: self._toggle_column(c, checked))
            menu.addAction(action)
        
        menu.addSeparator()
        
        # Reset to defaults
        reset_action = QAction("Reset to Defaults", menu)
        reset_action.triggered.connect(self._reset_columns)
        menu.addAction(reset_action)
        
        # Show menu at cursor
        menu.exec(self.header().mapToGlobal(position))
    
    def _toggle_column(self, column: ColumnConfig, visible: bool):
        """Toggle column visibility"""
        if column.visible == visible:
            return  # No change
        
        logger.info(f"Toggling column '{column.label}' visibility: {visible}")
        column.visible = visible
        
        # Rebuild the tree with new column configuration
        self._rebuild_columns()
        
        # Emit signal for external listeners
        self.columns_changed.emit()
    
    def _rebuild_columns(self):
        """Rebuild tree widget columns based on current configuration"""
        # Store current data
        stored_data = []
        root = self.invisibleRootItem()
        
        def collect_items(parent_item, level=0):
            """Recursively collect item data"""
            for i in range(parent_item.childCount()):
                item = parent_item.child(i)
                item_data = {
                    "texts": [item.text(col) for col in range(self.columnCount())],
                    "user_data": item.data(0, Qt.ItemDataRole.UserRole),
                    "expanded": item.isExpanded(),
                    "level": level
                }
                stored_data.append(item_data)
                collect_items(item, level + 1)
        
        collect_items(root)
        
        # Clear tree
        self.clear()
        
        # Update headers
        visible_cols = [col for col in self.columns if col.visible]
        labels = [col.label for col in visible_cols]
        self.setHeaderLabels(labels)
        
        # Set column widths
        for i, col in enumerate(visible_cols):
            self.setColumnWidth(i, col.width)
            col.index = i
        
        # Restore data (basic - subclasses should override with proper data mapping)
        logger.debug(f"Column rebuild complete: {len(visible_cols)} visible columns")
    
    def _on_column_moved(self, logical_index: int, old_visual_index: int, new_visual_index: int):
        """Handle column reordering via drag-and-drop"""
        logger.debug(f"Column moved: logical={logical_index}, old={old_visual_index}, new={new_visual_index}")
        
        # Update internal column order
        visible_cols = [col for col in self.columns if col.visible]
        if old_visual_index < len(visible_cols) and new_visual_index < len(visible_cols):
            # Reorder in columns list
            moved_col = visible_cols.pop(old_visual_index)
            visible_cols.insert(new_visual_index, moved_col)
            
            # Update indices
            for i, col in enumerate(visible_cols):
                col.index = i
        
        self.columns_changed.emit()
    
    def _reset_columns(self):
        """Reset columns to default configuration"""
        logger.info("Resetting columns to defaults")
        # This would need default values stored somewhere
        # For now, just show all columns
        for col in self.columns:
            col.visible = True
        
        self._rebuild_columns()
        self.columns_changed.emit()
    
    def get_column_config(self) -> Dict:
        """
        Get current column configuration for persistence.
        
        Returns:
            Dict with column keys, visibility, order, and widths
        """
        visible_cols = [col for col in self.columns if col.visible]
        return {
            "visible_columns": [col.key for col in visible_cols],
            "column_order": [col.key for col in self.columns],
            "column_widths": {col.key: col.width for col in self.columns}
        }
    
    def set_column_config(self, config: Dict):
        """
        Restore column configuration from saved state.
        
        Args:
            config: Dict with visible_columns, column_order, column_widths
        """
        if not config:
            return
        
        visible_keys = config.get("visible_columns", [])
        column_order = config.get("column_order", [])
        widths = config.get("column_widths", {})
        
        # Update visibility
        for col in self.columns:
            col.visible = col.key in visible_keys
            if col.key in widths:
                col.width = widths[col.key]
        
        # Reorder columns if order is specified
        if column_order:
            # Create new ordered list
            ordered = []
            for key in column_order:
                if key in self.column_map:
                    ordered.append(self.column_map[key])
            
            # Add any missing columns at the end
            for col in self.columns:
                if col not in ordered:
                    ordered.append(col)
            
            self.columns = ordered
            self.column_map = {col.key: col for col in self.columns}
        
        self._rebuild_columns()
        logger.info(f"Restored column configuration: {len(visible_keys)} visible columns")


class SeriesTreeWidget(CustomizableTreeWidget):
    """
    Specialized tree widget for series/season/episode display.
    
    This extends CustomizableTreeWidget with series-specific functionality
    like proper data handling and refresh logic.
    """
    
    def __init__(self, parent=None, config=None):
        super().__init__(parent)
        self._config = config

        # Define series-specific columns
        self.setup_columns([
            ColumnConfig("title", "Title", 400, True),
            ColumnConfig("episode", "Episode", 80, True),
            ColumnConfig("runtime", "Runtime", 80, True),
            ColumnConfig("rating", "Rating", 80, True),
            ColumnConfig("year", "Year", 60, False),  # Hidden by default
            ColumnConfig("added", "Added", 100, False),  # Hidden by default
        ], view_name="series_tree")
    
    def populate_season(self, season_item, season_data, episodes_data):
        """
        Populate a season item with proper column data.
        
        Args:
            season_item: QTreeWidgetItem for the season
            season_data: Season database model
            episodes_data: List of episode database models
        """
        # Season data
        data = {
            "title": f"📁 {season_data.name}",
            "episode": f"{len(episodes_data)} episodes",
        }
        
        # Extract rating from season raw_data if available
        if season_data.raw_data and isinstance(season_data.raw_data, dict):
            rating = season_data.raw_data.get("rating", "")
            if rating:
                star = self._config.rating_star_icon if self._config else "★"
                data["rating"] = f"{star} {rating}"

        self.set_column_data(season_item, data)
        season_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "season", "data": season_data})
    
    def populate_episode(self, episode_item, episode_data, parent_season):
        """
        Populate an episode item with proper column data.
        
        Args:
            episode_item: QTreeWidgetItem for the episode
            episode_data: Episode database model
            parent_season: Parent season item
        """
        watched_indicator = "✓ " if episode_data.is_watched else ""
        
        ep_icon = self._config.episode_icon if self._config else "▶"
        data = {
            "title": f"  {ep_icon} {watched_indicator}{episode_data.title}",
            "episode": f"E{episode_data.episode_num}",
            "runtime": episode_data.duration or "",
        }

        if episode_data.raw_data and isinstance(episode_data.raw_data, dict):
            info = episode_data.raw_data.get("info", {})
            if isinstance(info, dict):
                rating = info.get("rating", "")
                if rating:
                    star = self._config.rating_star_icon if self._config else "★"
                    data["rating"] = f"{star} {rating}"
        
        self.set_column_data(episode_item, data)
        episode_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "episode", "data": episode_data})


# Example usage for future channel list tree
class ChannelTreeWidget(CustomizableTreeWidget):
    """Tree widget for channel list with customizable columns"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Define channel-specific columns
        self.setup_columns([
            ColumnConfig("name", "Channel Name", 300, True),
            ColumnConfig("category", "Category", 150, True),
            ColumnConfig("quality", "Quality", 80, True),
            ColumnConfig("language", "Language", 80, False),
            ColumnConfig("rating", "Rating", 80, False),
            ColumnConfig("added", "Added", 100, False),
        ], view_name="channel_tree")
