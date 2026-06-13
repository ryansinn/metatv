"""CollapsibleSection base class and shared helpers for sidebar sections."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal
from loguru import logger

from metatv.core.channel_name_utils import parse_channel_name
from metatv.gui import theme as _theme


def _fmt_channel_name(name: str, fallback_year: str = "") -> str:
    """Format a raw channel name for text-only lists: 'bare_name · year [REGION] [QUALITY]'.

    Title first, year as immediate qualifier, tags at the right margin.
    fallback_year is used when no year is embedded in the channel name itself (e.g. from MetadataDB).
    """
    p = parse_channel_name(name)
    parts = [p.bare_name or name]

    year = p.year or fallback_year
    if year:
        parts.append(f"· {year}")

    tags = []
    if p.region:
        tags.append(f"[{p.region}]")
    if p.audio:
        tags.append(f"[{p.audio}]")
    if p.lang:
        tags.append(f"[{p.lang}]")
    if p.quality:
        tags.append(f"[{p.quality[0]}]")
    if tags:
        parts.append(" ".join(tags))

    return " ".join(parts)


class CollapsibleSection(QFrame):
    """Base class for collapsible sidebar sections with resize support"""

    # Signal when section wants to update its size
    sizeChanged = pyqtSignal()

    def __init__(self, title: str, icon: str, config, parent=None):
        super().__init__(parent)
        self.title = title
        self.icon = icon
        self.config = config
        self.is_collapsed = False
        self.is_empty = True
        self._user_collapsed = False  # True when user (or restore) explicitly collapsed

        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

        # Main layout
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # Header
        self.create_header()

        # Content container
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(5, 5, 5, 5)
        self.main_layout.addWidget(self.content_widget)

        # Create section-specific content
        self.create_content()

    def create_header(self):
        """Create collapsible header with title and toggle button"""
        header = QWidget()
        header.setStyleSheet(_theme.HEADER_TINT)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(5, 3, 5, 3)

        # Collapse/expand button
        self.toggle_btn = QPushButton(self.config.collapse_icon)
        self.toggle_btn.setFixedSize(20, 20)
        self.toggle_btn.clicked.connect(self.toggle_collapse)
        header_layout.addWidget(self.toggle_btn)

        # Title with icon
        self.title_label = QLabel(f"{self.icon} <b>{self.title}</b>")
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()

        self.main_layout.addWidget(header)

    def create_content(self):
        """Override in subclasses to add section-specific content"""
        pass

    def toggle_collapse(self):
        """Toggle collapsed/expanded state"""
        self._user_collapsed = not self.is_collapsed  # record user intent before toggling
        self.set_collapsed(not self.is_collapsed)

    def set_collapsed(self, collapsed: bool, save: bool = True):
        """Set collapsed state

        Args:
            collapsed: Whether to collapse the section
            save: Whether to save state to config (default: True)
        """
        self.is_collapsed = collapsed
        self.content_widget.setVisible(not collapsed)

        # Update button icon
        if collapsed:
            self.toggle_btn.setText(self.config.expand_icon)
        else:
            self.toggle_btn.setText(self.config.collapse_icon)

        # Force size update
        if collapsed:
            self.setMaximumHeight(self.minimumSizeHint().height())
        else:
            self.setMaximumHeight(16777215)  # Qt's QWIDGETSIZE_MAX

        # Notify parent to adjust layout
        self.updateGeometry()
        self.sizeChanged.emit()

        # Save state (unless explicitly disabled, e.g. during restore)
        if save:
            self.save_state()

    def set_empty(self, empty: bool):
        """Set empty state and auto-collapse if empty"""
        was_empty = self.is_empty
        self.is_empty = empty

        # Auto-collapse when becoming empty
        if empty and not was_empty:
            self.set_collapsed(True)
        # Auto-expand only when section was empty-collapsed (not user/restore-collapsed)
        elif not empty and was_empty and self.is_collapsed and not self._user_collapsed:
            self.set_collapsed(False)

    def get_section_id(self):
        """Get unique ID for this section (for saving state)"""
        # Override in subclasses or use title as default
        return self.title.lower().replace(" ", "_")

    def save_state(self):
        """Save section state to config"""
        section_id = self.get_section_id()

        # Get or create section states dict in config
        if not hasattr(self.config, 'sidebar_section_states'):
            self.config.sidebar_section_states = {}

        self.config.sidebar_section_states[section_id] = {
            'collapsed': self.is_collapsed,
            'height': self.height()
        }

        # Save config to disk
        try:
            self.config.save()
        except Exception as e:
            logger.warning(f"Could not save section state: {e}")

    def restore_state(self):
        """Restore section state from config"""
        section_id = self.get_section_id()

        if not hasattr(self.config, 'sidebar_section_states'):
            return

        state = self.config.sidebar_section_states.get(section_id)
        if state:
            # Restore collapsed state (don't save during restore)
            collapsed = state.get('collapsed', False)
            if collapsed:
                self._user_collapsed = True  # treat restored-collapsed as explicit user intent
            self.set_collapsed(collapsed, save=False)

    def refresh(self):
        """Refresh section content - override in subclasses"""
        pass
