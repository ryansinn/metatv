"""CollapsibleSection base class and shared helpers for sidebar sections."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent
from loguru import logger

from metatv.core.channel_name_utils import parse_channel_name
from metatv.gui import theme as _theme

# Minimum height when a section is expanded: header (~26px) + room for ≥2 rows.
# The splitter enforces this so the user cannot drag an expanded section below it.
_MIN_EXPANDED = 80


class _ClickableHeader(QWidget):
    """A QWidget header that emits ``clicked`` on any mouse-press not consumed by a child.

    Child ``QPushButton`` widgets (action buttons, toggle arrow) intercept their own
    clicks via Qt's normal event propagation — they never reach this widget's
    ``mousePressEvent``.  Clicks on the title label or empty header padding do reach it
    and fire ``clicked``, allowing the full header area to act as a collapse/expand toggle.
    """

    clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(_theme.HEADER_TINT)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        self.clicked.emit()
        super().mousePressEvent(event)


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
        self._expanded_height: int = _MIN_EXPANDED  # remembered across collapse/expand cycles

        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.setMinimumHeight(_MIN_EXPANDED)  # splitter enforces this while expanded

        # Main layout
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # Header
        self.create_header()

        # Content container — Expanding so it fills the section's splitter allocation
        self.content_widget = QWidget()
        self.content_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(5, 5, 5, 5)
        self.content_layout.setSpacing(4)
        self.main_layout.addWidget(self.content_widget, 1)

        # Create section-specific content
        self.create_content()

    def _build_clickable_header(self) -> "_ClickableHeader":
        """Create and return a ``_ClickableHeader`` pre-wired with the toggle button.

        Subclasses that override ``create_header`` call this helper to get a header
        widget whose click → ``toggle_collapse`` wiring is already done.  They then
        add their own title label and any extra action buttons into the returned
        header's layout, and finish with::

            self.main_layout.addWidget(header)

        The toggle button is stored as ``self.toggle_btn`` on exit so the existing
        ``set_collapsed`` bookkeeping that updates ``toggle_btn.setText(…)`` continues
        to work unmodified.

        Returns:
            A ``_ClickableHeader`` instance with a ``QHBoxLayout`` (margins 5,3,5,3)
            already containing ``self.toggle_btn``.
        """
        header = _ClickableHeader()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(5, 3, 5, 3)

        self.toggle_btn = QPushButton(self.config.collapse_icon)
        self.toggle_btn.setFixedSize(20, 20)
        self.toggle_btn.setToolTip("Collapse / expand this section")
        self.toggle_btn.clicked.connect(self.toggle_collapse)
        header_layout.addWidget(self.toggle_btn)

        # Clicking anywhere on the header (outside child buttons) also toggles.
        header.clicked.connect(self.toggle_collapse)

        return header

    def create_header(self):
        """Create collapsible header with title and toggle button."""
        header = self._build_clickable_header()
        header_layout = header.layout()

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
        """Set collapsed state.

        Args:
            collapsed: Whether to collapse the section.
            save: Whether to save state and redistribute splitter space (False during restore).
        """
        self.is_collapsed = collapsed
        self.content_widget.setVisible(not collapsed)

        if collapsed:
            self.toggle_btn.setText(self.config.expand_icon)
            h = self.height()
            if h >= _MIN_EXPANDED:
                self._expanded_height = h
            freed = max(0, h - 26)
            self.setMinimumHeight(26)
            self.setMaximumHeight(self.minimumSizeHint().height())
            if save and freed > 0:
                self._release_in_splitter(freed)
        else:
            self.toggle_btn.setText(self.config.collapse_icon)
            self.setMinimumHeight(_MIN_EXPANDED)
            self.setMaximumHeight(16777215)  # Qt's QWIDGETSIZE_MAX
            if save:
                self._grow_in_splitter()

        # Notify parent to adjust layout
        self.updateGeometry()
        self.sizeChanged.emit()

        # Save state (unless explicitly disabled, e.g. during restore)
        if save:
            self.save_state()

    # ------------------------------------------------------------------
    # Splitter redistribution helpers
    # ------------------------------------------------------------------

    def _grow_in_splitter(self) -> None:
        """Grow to saved expanded height, stealing proportionally from neighbors."""
        from PyQt6.QtWidgets import QSplitter
        splitter = self.parentWidget()
        if not isinstance(splitter, QSplitter):
            return

        idx = splitter.indexOf(self)
        sizes = list(splitter.sizes())
        n = len(sizes)
        if idx < 0 or idx >= n:
            return

        target = max(_MIN_EXPANDED, self._expanded_height)
        if sizes[idx] >= target:
            return

        # Floor for each other section: header-only if collapsed, _MIN_EXPANDED if expanded
        floors = [
            26 if getattr(splitter.widget(i), 'is_collapsed', False) else _MIN_EXPANDED
            for i in range(n)
        ]

        others_avail = [
            (i, max(0, sizes[i] - floors[i]))
            for i in range(n)
            if i != idx and sizes[i] > 0
        ]
        total_avail = sum(a for _, a in others_avail)
        if total_avail <= 0:
            return

        delta = min(target - sizes[idx], total_avail)
        new_sizes = list(sizes)
        new_sizes[idx] += delta

        remaining = delta
        for i, avail in sorted(others_avail, key=lambda x: -x[1]):
            if total_avail > 0 and avail > 0:
                take = round(delta * avail / total_avail)
                take = min(take, new_sizes[i] - floors[i], remaining)
                take = max(0, take)
                new_sizes[i] -= take
                remaining -= take

        if remaining > 0:
            for i, avail in others_avail:
                extra = min(remaining, new_sizes[i] - floors[i])
                if extra > 0:
                    new_sizes[i] -= extra
                    remaining -= extra
                if remaining <= 0:
                    break

        splitter.setSizes(new_sizes)

    def _release_in_splitter(self, freed: int) -> None:
        """Distribute freed pixels to other visible sections when this one collapses."""
        from PyQt6.QtWidgets import QSplitter
        splitter = self.parentWidget()
        if not isinstance(splitter, QSplitter):
            return

        idx = splitter.indexOf(self)
        sizes = list(splitter.sizes())
        n = len(sizes)
        if idx < 0 or idx >= n or freed <= 0:
            return

        recipients = [(i, sizes[i]) for i in range(n) if i != idx and sizes[i] > 0]
        if not recipients:
            return

        total_r = sum(s for _, s in recipients)
        new_sizes = list(sizes)
        new_sizes[idx] = 26  # collapsed to header height

        remaining = freed
        for i, s in sorted(recipients, key=lambda x: -x[1]):
            if total_r > 0:
                take = round(freed * s / total_r)
                take = min(take, remaining)
                new_sizes[i] += take
                remaining -= take

        if remaining > 0:
            for i, _ in recipients:
                new_sizes[i] += remaining
                remaining = 0
                break

        splitter.setSizes(new_sizes)

    # ------------------------------------------------------------------
    # Empty / state management
    # ------------------------------------------------------------------

    def show_load_error(self, list_widget, message: str) -> None:
        """Render a distinct, non-selectable error row after a failed background load.

        A failed background refresh must never look like a legitimate empty result
        (see CLAUDE.md "Background refresh failure must be visible"). Keeps the section
        expanded so the message is seen instead of silently blanking the list.
        """
        from PyQt6.QtWidgets import QListWidgetItem
        from metatv.gui import icons as _icons

        list_widget.clear()
        item = QListWidgetItem(f"{_icons.notification_warning_icon} {message}")
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        list_widget.addItem(item)
        self.set_empty(False)

    def show_loading(self, list_widget, message: str = "Loading…") -> None:
        """Render a transient, non-selectable loading row while a background load runs.

        Mirrors ``show_load_error`` exactly (same non-selectable row, same set_empty
        bookkeeping) but uses ``icons.loading_icon`` instead of the warning icon. Keeps
        the section expanded so the placeholder is visible instead of the section
        showing its stale empty/zero state during the load window. Replaced when the
        result slot clears the list and renders rows.
        """
        from PyQt6.QtWidgets import QListWidgetItem
        from metatv.gui import icons as _icons

        list_widget.clear()
        item = QListWidgetItem(f"{_icons.loading_icon} {message}")
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        list_widget.addItem(item)
        self.set_empty(False)

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
            'height': self.height(),
            'expanded_height': self._expanded_height,
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
            # Restore saved expanded height first
            eh = state.get('expanded_height', _MIN_EXPANDED)
            if eh and eh >= _MIN_EXPANDED:
                self._expanded_height = eh
            # Restore collapsed state (don't redistribute during restore — saved sizes handle it)
            collapsed = state.get('collapsed', False)
            if collapsed:
                self._user_collapsed = True  # treat restored-collapsed as explicit user intent
            self.set_collapsed(collapsed, save=False)

    def refresh(self):
        """Refresh section content - override in subclasses"""
        pass
