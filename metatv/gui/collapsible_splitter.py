"""Collapsible splitter widget with click-to-collapse functionality"""
from PyQt6.QtWidgets import QSplitter, QSplitterHandle
from PyQt6.QtCore import Qt, QPointF, QSize, pyqtSignal
from PyQt6.QtGui import QColor, QMouseEvent, QPainter

from metatv.gui import theme as _theme
from metatv.gui.cursor_affordance import set_clickable


class CollapsibleSplitterHandle(QSplitterHandle):
    """Custom splitter handle that collapses panels on click.

    The click-to-collapse gesture used to be invisible: a bare, near-zero-width
    handle with no affordance.  It now advertises itself — a minimum thickness
    (:data:`GRIP_THICKNESS`), a painted row of muted grip dots
    (:meth:`paintEvent`), a pointing-hand cursor (via the ``cursor_affordance``
    chokepoint), and a tooltip — so the collapse gesture is discoverable.
    """

    # Signal when handle is clicked (not dragged)
    clicked = pyqtSignal()

    #: Minimum handle thickness (px) so the grip dots have room to show — a bare
    #: QSplitterHandle is near-zero-width on most styles.
    GRIP_THICKNESS = 7
    #: Number / geometry of the centred grip dots painted on the handle.
    _GRIP_DOTS = 3
    _GRIP_DOT_RADIUS = 1.0
    _GRIP_DOT_GAP = 4.0

    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self.drag_started = False
        self.click_pos = None
        # Discoverability: tooltip + pointing-hand cursor.  A QSplitterHandle is
        # not a QAbstractButton, so it must opt into the hand via the single
        # cursor_affordance chokepoint — never a hand-rolled setCursor call here.
        self.setToolTip("Click to collapse/expand")
        set_clickable(self)

    def sizeHint(self) -> QSize:
        """Guarantee enough thickness across the handle to show the grip dots."""
        hint = super().sizeHint()
        if self.orientation() == Qt.Orientation.Horizontal:
            # Horizontal splitter → vertical handle strip: thickness is the WIDTH.
            hint.setWidth(max(hint.width(), self.GRIP_THICKNESS))
        else:
            hint.setHeight(max(hint.height(), self.GRIP_THICKNESS))
        return hint

    def paintEvent(self, event) -> None:
        """Draw the default handle, then a centred row of muted grip dots.

        The dots run along the handle's long axis (a horizontal splitter has
        vertical handle strips → dots stack vertically) so the affordance reads
        the same on every orientation.
        """
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(_theme.COLOR_SPLITTER_GRIP))

        rect = self.rect()
        cx = rect.center().x()
        cy = rect.center().y()
        span = self._GRIP_DOT_GAP * (self._GRIP_DOTS - 1)
        r = self._GRIP_DOT_RADIUS
        if self.orientation() == Qt.Orientation.Horizontal:
            # Vertical strip → stack the dots vertically, centred.
            top = cy - span / 2.0
            for i in range(self._GRIP_DOTS):
                painter.drawEllipse(QPointF(cx, top + i * self._GRIP_DOT_GAP), r, r)
        else:
            # Horizontal strip → lay the dots out horizontally, centred.
            left = cx - span / 2.0
            for i in range(self._GRIP_DOTS):
                painter.drawEllipse(QPointF(left + i * self._GRIP_DOT_GAP, cy), r, r)
        painter.end()

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
        # Give handles a real thickness so the discoverable grip (see
        # CollapsibleSplitterHandle.paintEvent) has room to show; the handle's
        # sizeHint enforces the same floor.
        self.setHandleWidth(CollapsibleSplitterHandle.GRIP_THICKNESS)
    
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

            # Collapse by setting size to 0.  childrenCollapsible is kept False to
            # stop *drag* from collapsing panels, but that same flag also clamps
            # setSizes() to a panel's minimumWidth — so a min-width panel (e.g. the
            # 200px sidebar) would stick at ~200 instead of 0.  Lift the flag only
            # around this programmatic collapse, then restore it so drag protection
            # stays intact.
            was_collapsible = self.childrenCollapsible()
            self.setChildrenCollapsible(True)
            try:
                sizes[index] = 0
                self.setSizes(sizes)
            finally:
                self.setChildrenCollapsible(was_collapsible)
    
    def expand_panel(self, index: int):
        """Expand a collapsed panel back to the width it was collapsed from.

        The space has to be TAKEN BACK from the panels that absorbed it when
        this one collapsed. Writing the remembered width in and leaving the
        others alone asks the splitter for more room than it has, so Qt scales
        every panel down to fit and the restored panel comes back narrower than
        it went — visibly shrinking a little more on each collapse/expand cycle
        (a 416px sidebar returned as 327px). Same family as the #280 filter
        panel bug: a size request the splitter is free to ignore.

        Args:
            index: Panel index to restore.
        """
        if index < 0 or index >= self.count():
            return

        # Get previous size or use default
        previous_size = self.collapsed_panels.get(index, 300)

        sizes = self.sizes()
        deficit = previous_size - sizes[index]
        if deficit > 0:
            # Reclaim from the WIDEST panel first, not proportionally from all
            # of them. The slack went to whichever panel grew when this one
            # collapsed — normally the centre content pane — so that is who
            # should give it back. Splitting the cost across every panel takes
            # width from the other flank too, which matters when both flanks
            # are restored in turn (leaving an Explore view does exactly that):
            # restoring the first would quietly shrink the second.
            for i in sorted(
                (i for i in range(len(sizes)) if i != index),
                key=lambda i: sizes[i],
                reverse=True,
            ):
                if deficit <= 0:
                    break
                take = min(deficit, sizes[i])
                sizes[i] -= take
                deficit -= take
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
