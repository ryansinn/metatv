"""Collapsible splitter widget with click-to-collapse functionality"""
from PyQt6.QtWidgets import QSplitter, QSplitterHandle
from PyQt6.QtCore import Qt, QEvent, QPoint, pyqtSignal
from PyQt6.QtGui import QMouseEvent


class CollapsibleSplitterHandle(QSplitterHandle):
    """Custom splitter handle that collapses panels on click"""
    
    # Signal when handle is clicked (not dragged)
    clicked = pyqtSignal()
    
    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self.drag_started = False
        self.click_pos = None
    
    def mousePressEvent(self, event: QMouseEvent):
        """Track mouse press for click detection"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_started = False
            self.click_pos = event.pos()
        super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event: QMouseEvent):
        """Detect if user is dragging"""
        if self.click_pos:
            # If moved more than 5 pixels, consider it a drag
            if (event.pos() - self.click_pos).manhattanLength() > 5:
                self.drag_started = True
        super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        """Handle click vs drag"""
        if event.button() == Qt.MouseButton.LeftButton:
            # If not dragged, emit clicked signal
            if not self.drag_started and self.click_pos:
                self.clicked.emit()
            self.drag_started = False
            self.click_pos = None
        super().mouseReleaseEvent(event)


class CollapsibleSplitter(QSplitter):
    """Splitter with click-to-collapse functionality
    
    Features:
    - Click on handle to collapse/expand panels
    - Drag handle to manually resize (standard behavior)
    - Remembers panel sizes before collapse
    """
    
    def __init__(self, orientation=Qt.Orientation.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.collapsed_panels = {}  # index -> previous_size
        # Prevent Qt from collapsing panels to zero on drag — our click-to-collapse
        # logic calls setSizes() directly and still works with this off.
        self.setChildrenCollapsible(False)
    
    def createHandle(self):
        """Create custom handle with click detection"""
        handle = CollapsibleSplitterHandle(self.orientation(), self)
        handle.clicked.connect(lambda: self._on_handle_clicked(handle))
        return handle
    
    def _on_handle_clicked(self, handle: CollapsibleSplitterHandle):
        """Handle click on splitter handle - toggle collapse"""
        # Find which panels are adjacent to this handle
        handle_index = self.indexOf(handle)
        
        # Determine which panel to collapse (prioritize left/top panel)
        panel_index = handle_index
        
        if panel_index < 0 or panel_index >= self.count():
            return
        
        # Toggle collapse state
        if self.is_panel_collapsed(panel_index):
            self.expand_panel(panel_index)
        else:
            # Check if right/bottom panel is collapsed, expand it instead
            next_panel_index = panel_index + 1
            if next_panel_index < self.count() and self.is_panel_collapsed(next_panel_index):
                self.expand_panel(next_panel_index)
            else:
                self.collapse_panel(panel_index)
    
    def is_panel_collapsed(self, index: int) -> bool:
        """Check if a panel is collapsed"""
        if index < 0 or index >= self.count():
            return False
        
        sizes = self.sizes()
        return sizes[index] == 0
    
    def collapse_panel(self, index: int):
        """Collapse a panel and remember its size"""
        if index < 0 or index >= self.count():
            return
        
        sizes = self.sizes()
        current_size = sizes[index]
        
        if current_size > 0:
            # Remember current size
            self.collapsed_panels[index] = current_size
            
            # Collapse by setting size to 0
            sizes[index] = 0
            self.setSizes(sizes)
    
    def expand_panel(self, index: int):
        """Expand a collapsed panel to its previous size"""
        if index < 0 or index >= self.count():
            return
        
        # Get previous size or use default
        previous_size = self.collapsed_panels.get(index, 300)
        
        sizes = self.sizes()
        sizes[index] = previous_size
        self.setSizes(sizes)
        
        # Clear remembered size
        if index in self.collapsed_panels:
            del self.collapsed_panels[index]
    
    def toggle_panel(self, index: int):
        """Toggle panel collapsed state"""
        if self.is_panel_collapsed(index):
            self.expand_panel(index)
        else:
            self.collapse_panel(index)
