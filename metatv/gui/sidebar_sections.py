"""Modular collapsible sidebar sections"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QSizePolicy, QTreeWidget,
    QTreeWidgetItem, QListWidget, QListWidgetItem
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QTimer
from PyQt6.QtGui import QFont
from loguru import logger

from metatv.core.repositories import RepositoryFactory


class ProviderItemWidget(QWidget):
    """Custom widget for provider items with refresh, edit, and toggle buttons."""

    refreshClicked = pyqtSignal(str)   # provider_id
    editClicked = pyqtSignal(str)      # provider_id
    toggleClicked = pyqtSignal(str)    # provider_id

    def __init__(self, provider_id: str, provider_name: str, is_active: bool = True,
                 icon: str = "", sub_color: str = "", parent=None):
        super().__init__(parent)
        self.provider_id = provider_id
        self._is_active = is_active

        self.setAutoFillBackground(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)

        # Provider icon / emoji (optional)
        if icon:
            icon_lbl = QLabel(icon)
            icon_lbl.setFixedWidth(18)
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(icon_lbl)

        # Active/inactive dot
        self._status_lbl = QLabel("●" if is_active else "○")
        self._status_lbl.setFixedWidth(12)
        self._status_lbl.setStyleSheet(f"color: {'#4CAF50' if is_active else '#555'};")
        layout.addWidget(self._status_lbl)

        # Provider name — colored by subscription time if available
        self._name_lbl = QLabel(provider_name)
        self._name_lbl.setWordWrap(False)
        self._name_lbl.setTextFormat(Qt.TextFormat.PlainText)
        if sub_color:
            self._name_lbl.setStyleSheet(f"color: {sub_color};")
        layout.addWidget(self._name_lbl, 1)

        _btn_style = """
            QPushButton {{
                background: rgba({r},{g},{b},0.15);
                border: 1px solid rgba({r},{g},{b},0.5);
                border-radius: 3px;
                font-size: 10px;
                color: rgb({r},{g},{b});
            }}
            QPushButton:hover {{ background: rgba({r},{g},{b},0.35); }}
        """

        # Toggle (enable/disable)
        self._toggle_btn = QPushButton("●" if is_active else "○")
        self._toggle_btn.setFixedSize(22, 20)
        self._toggle_btn.setToolTip("Enable / Disable this provider")
        self._toggle_btn.setStyleSheet(_btn_style.format(r=180, g=180, b=180))
        self._toggle_btn.clicked.connect(lambda: self.toggleClicked.emit(self.provider_id))
        layout.addWidget(self._toggle_btn)

        # Edit pencil
        edit_btn = QPushButton("✎")
        edit_btn.setFixedSize(22, 20)
        edit_btn.setToolTip("Edit provider settings")
        edit_btn.setStyleSheet(_btn_style.format(r=100, g=160, b=255))
        edit_btn.clicked.connect(lambda: self.editClicked.emit(self.provider_id))
        layout.addWidget(edit_btn)

        # Refresh
        refresh_btn = QPushButton("↻")
        refresh_btn.setFixedSize(22, 20)
        refresh_btn.setToolTip("Refresh channels from provider")
        refresh_btn.setStyleSheet(_btn_style.format(r=68, g=136, b=255))
        refresh_btn.clicked.connect(lambda: self.refreshClicked.emit(self.provider_id))
        layout.addWidget(refresh_btn)

    def update_active(self, is_active: bool):
        self._is_active = is_active
        self._status_lbl.setText("●" if is_active else "○")
        self._status_lbl.setStyleSheet(f"color: {'#4CAF50' if is_active else '#555'};")
        self._toggle_btn.setText("●" if is_active else "○")


class HistoryItemWidget(QWidget):
    """Custom widget for history list items with play next button"""
    
    playNextClicked = pyqtSignal(str)  # channel_id
    
    def __init__(self, channel_id, text, has_next_episode=False, parent=None):
        super().__init__(parent)
        self.channel_id = channel_id
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)
        
        # Text label (series name + episode info)
        text_label = QLabel(text)
        text_label.setWordWrap(False)
        layout.addWidget(text_label, 1)  # Stretch factor 1
        
        # Play next button (only show if there's a next episode)
        if has_next_episode:
            next_btn = QPushButton(">>")
            next_btn.setFixedSize(30, 20)
            next_btn.setToolTip("Play next episode")
            next_btn.clicked.connect(lambda: self.playNextClicked.emit(self.channel_id))
            next_btn.setStyleSheet("""
                QPushButton {
                    background-color: rgba(68, 136, 255, 0.2);
                    border: 1px solid #4488ff;
                    border-radius: 3px;
                    font-size: 11px;
                    font-weight: bold;
                    color: #4488ff;
                }
                QPushButton:hover {
                    background-color: rgba(68, 136, 255, 0.4);
                }
                QPushButton:pressed {
                    background-color: rgba(68, 136, 255, 0.6);
                }
            """)
            layout.addWidget(next_btn)
        
        self.setLayout(layout)


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
        header.setStyleSheet("background-color: rgba(255, 255, 255, 0.05);")
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
            
            # Restore height (if not collapsed)
            if not collapsed:
                height = state.get('height')
                if height:
                    self.setMinimumHeight(height)
    
    def refresh(self):
        """Refresh section content - override in subclasses"""
        pass


class SourcesSection(CollapsibleSection):
    """Sources provider list section"""

    providerSelected = pyqtSignal(str)         # provider_id
    providerRefreshClicked = pyqtSignal(str)   # provider_id
    providerEditClicked = pyqtSignal(str)      # provider_id
    providerToggleClicked = pyqtSignal(str)    # provider_id
    addProviderClicked = pyqtSignal()

    def __init__(self, config, db, parent=None):
        self.db = db
        super().__init__("Sources", config.provider_icon, config, parent)

    def get_section_id(self):
        return "sources"

    def create_header(self):
        """Override to add '+' button in the header instead of bottom buttons."""
        header = QWidget()
        header.setStyleSheet("background-color: rgba(255, 255, 255, 0.05);")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(5, 3, 5, 3)

        self.toggle_btn = QPushButton(self.config.collapse_icon)
        self.toggle_btn.setFixedSize(20, 20)
        self.toggle_btn.clicked.connect(self.toggle_collapse)
        header_layout.addWidget(self.toggle_btn)

        self.title_label = QLabel(f"📡 <b>Sources</b>")
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()

        add_btn = QPushButton("+")
        add_btn.setFixedSize(22, 20)
        add_btn.setToolTip("Add Source…")
        add_btn.setStyleSheet("""
            QPushButton { font-size: 14px; font-weight: bold; border: 1px solid #4488ff;
                          border-radius: 3px; color: #4488ff; background: rgba(68,136,255,0.1); }
            QPushButton:hover { background: rgba(68,136,255,0.3); }
        """)
        add_btn.clicked.connect(self.addProviderClicked.emit)
        header_layout.addWidget(add_btn)

        self.main_layout.addWidget(header)

    def create_content(self):
        """Create sources tree (no bottom buttons — they moved to the header)."""
        from PyQt6.QtWidgets import QTreeWidget
        self.sources_tree = QTreeWidget()
        self.sources_tree.setHeaderHidden(True)
        self.sources_tree.setMaximumHeight(250)
        self.sources_tree.itemClicked.connect(self.on_provider_clicked)
        self.content_layout.addWidget(self.sources_tree)

    def refresh(self):
        """Load providers from database."""
        self.sources_tree.clear()

        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            providers = repos.providers.get_all()
            self.set_empty(len(providers) == 0)

            for provider in providers:
                from PyQt6.QtWidgets import QTreeWidgetItem
                item = QTreeWidgetItem(self.sources_tree)
                item.setText(0, "")
                item.setData(0, Qt.ItemDataRole.UserRole, provider.id)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

                # Subscription color from cached account info
                sub_color = ""
                if provider.account_exp_date:
                    from metatv.gui.provider_editor import subscription_color
                    sub_color = subscription_color(provider.account_exp_date, provider.account_created_at)

                icon = getattr(provider, "icon", "") or ""

                widget = ProviderItemWidget(
                    provider.id, provider.name,
                    is_active=provider.is_active,
                    icon=icon,
                    sub_color=sub_color,
                )
                widget.refreshClicked.connect(
                    lambda pid=provider.id: self.providerRefreshClicked.emit(pid)
                )
                widget.editClicked.connect(
                    lambda pid=provider.id: self.providerEditClicked.emit(pid)
                )
                widget.toggleClicked.connect(
                    lambda pid=provider.id: self.providerToggleClicked.emit(pid)
                )
                self.sources_tree.setItemWidget(item, 0, widget)
        finally:
            session.close()

    def on_provider_clicked(self, item, column):
        provider_id = item.data(0, Qt.ItemDataRole.UserRole)
        if provider_id:
            self.providerSelected.emit(provider_id)

    def update_provider_status(self, provider_id: str, status: str):
        """Legacy method — no-op; widgets now update via refresh()."""
        pass


class WatchAlertsSection(CollapsibleSection):
    """Alerts section — EPG watch alerts + stream retry monitoring."""

    alertClicked = pyqtSignal(str)                         # channel_db_id — double-click to play
    channelContextMenuRequested = pyqtSignal(str, int, int) # channel_db_id, global_x, global_y
    retryRemoveRequested = pyqtSignal(str)                  # entry_id
    retryClearAllRequested = pyqtSignal()
    retryPlayRequested = pyqtSignal(str, str, str)            # channel_id, stream_url, channel_name
    retryContextMenuRequested = pyqtSignal(str, str, int, int)  # entry_id, channel_id, x, y

    def __init__(self, config, db, parent=None):
        self.db = db
        super().__init__("Alerts", config.watch_alerts_icon, config, parent)

    def get_section_id(self):
        return "alerts"

    def create_header(self):
        header = QWidget()
        header.setStyleSheet("background-color: rgba(255, 255, 255, 0.05);")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(5, 3, 5, 3)
        self.toggle_btn = QPushButton(self.config.collapse_icon)
        self.toggle_btn.setFixedSize(20, 20)
        self.toggle_btn.clicked.connect(self.toggle_collapse)
        hl.addWidget(self.toggle_btn)
        self.title_label = QLabel(
            f'<span style="color:#FFB300">{self.icon}</span> <b>{self.title}</b>'
        )
        self.title_label.setTextFormat(Qt.TextFormat.RichText)
        hl.addWidget(self.title_label)
        hl.addStretch()
        self.main_layout.addWidget(header)

    def create_content(self):
        self.alerts_tree = QTreeWidget()
        self.alerts_tree.setHeaderHidden(True)
        self.alerts_tree.setColumnCount(1)
        self.alerts_tree.setMaximumHeight(200)
        self.alerts_tree.setIndentation(12)
        self.alerts_tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.alerts_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.alerts_tree.customContextMenuRequested.connect(self._on_context_menu)
        self.content_layout.addWidget(self.alerts_tree)

        # Stream retry sub-section header row with info tooltip
        retry_hdr_row = QHBoxLayout()
        retry_hdr_row.setContentsMargins(0, 4, 0, 2)
        retry_hdr_row.setSpacing(4)
        self._retry_header = QLabel("Stream Monitoring")
        self._retry_header.setStyleSheet("color: #888; font-size: 11px; font-weight: bold;")
        retry_hdr_row.addWidget(self._retry_header)
        _info_lbl = QLabel(self.config.info_icon)
        _info_lbl.setStyleSheet("color: #555; font-size: 11px;")
        _info_lbl.setToolTip(
            "Stream Monitoring periodically re-checks streams that previously\n"
            "failed to play. When a stream becomes available again you'll\n"
            "receive a notification. Double-click an entry to retry immediately."
        )
        retry_hdr_row.addWidget(_info_lbl)
        retry_hdr_row.addStretch()
        self._retry_hdr_container = QWidget()
        self._retry_hdr_container.setLayout(retry_hdr_row)
        self._retry_hdr_container.hide()
        self.content_layout.addWidget(self._retry_hdr_container)

        self._retry_list = QListWidget()
        self._retry_list.setMaximumHeight(150)
        self._retry_list.setStyleSheet("QListWidget { font-size: 11px; }")
        self._retry_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._retry_list.customContextMenuRequested.connect(self._on_retry_context_menu)
        self._retry_list.itemDoubleClicked.connect(self._on_retry_double_clicked)
        self._retry_list.hide()
        self.content_layout.addWidget(self._retry_list)

        self.set_empty(True)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        if item.parent():  # only child (airing) rows, not group headers
            channel_db_id = item.data(0, Qt.ItemDataRole.UserRole)
            if channel_db_id:
                self.alertClicked.emit(channel_db_id)

    def _on_context_menu(self, pos) -> None:
        item = self.alerts_tree.itemAt(pos)
        if not item or not item.parent():  # skip headers
            return
        channel_db_id = item.data(0, Qt.ItemDataRole.UserRole)
        if channel_db_id:
            gp = self.alerts_tree.viewport().mapToGlobal(pos)
            self.channelContextMenuRequested.emit(channel_db_id, gp.x(), gp.y())

    def refresh(self) -> None:
        from metatv.core.repositories.epg import EpgRepository
        from metatv.core.database import ChannelDB
        from datetime import datetime, timezone

        patterns = self.config.epg_watchlist_patterns
        self.alerts_tree.clear()
        if not patterns:
            self.set_empty(True)
            return

        session = self.db.get_session()
        try:
            repo = EpgRepository(session)
            live     = repo.get_live_for_watchlist(patterns)
            upcoming = repo.get_upcoming_for_watchlist(patterns, hours_ahead=24)

            now = datetime.now(timezone.utc).replace(tzinfo=None)

            # Collect all airings grouped by show title (case-insensitive key).
            # display_title tracks the first seen form for each group.
            by_key: dict[str, list[tuple]] = {}
            display_title: dict[str, str] = {}

            def _title_key(title: str) -> str:
                return " ".join(title.casefold().replace("&", "and").split())

            def _add(title: str, entry: tuple) -> None:
                key = _title_key(title)
                if key not in display_title:
                    display_title[key] = title
                by_key.setdefault(key, []).append(entry)

            for _pattern, progs in live.items():
                for prog in progs:
                    ch = session.query(ChannelDB).filter_by(id=prog.channel_db_id).first()
                    ch_name = ch.name if ch else (prog.channel_epg_id or "Unknown")
                    mins_left = max(0, int((prog.stop_time - now).total_seconds() / 60))
                    time_str = f"{mins_left}m left" if mins_left >= 1 else "ending"
                    _add(prog.title, (0, "🔴", time_str, ch_name, prog.channel_db_id))

            for _pattern, progs in upcoming.items():
                for prog in progs:
                    ch = session.query(ChannelDB).filter_by(id=prog.channel_db_id).first()
                    ch_name = ch.name if ch else (prog.channel_epg_id or "Unknown")
                    mins = int((prog.start_time - now).total_seconds() / 60)
                    if mins < 60:
                        time_str = f"in {mins}m"
                    elif prog.start_time.date() == now.date():
                        local = prog.start_time.replace(tzinfo=timezone.utc).astimezone()
                        time_str = local.strftime("%-I:%M %p")
                    else:
                        local = prog.start_time.replace(tzinfo=timezone.utc).astimezone()
                        time_str = local.strftime("%a %-I:%M %p")
                    _add(prog.title, (prog.start_time.timestamp(), "⏰", time_str, ch_name, prog.channel_db_id))

            if not by_key:
                self.set_empty(True)
                return

            # Sort groups by their earliest airing; live (sort_key=0) floats to top
            def _group_sort_key(airings):
                return min(a[0] for a in airings)

            sorted_titles = sorted(by_key.items(), key=lambda kv: _group_sort_key(kv[1]))

            for key, airings in sorted_titles:
                title = display_title[key]
                airings.sort(key=lambda a: a[0])  # sort children by time within group
                count = len(airings)
                soonest_icon, soonest_time = airings[0][1], airings[0][2]
                summary = f"{soonest_icon} {soonest_time}" if count == 1 else f"{soonest_icon} {soonest_time}  +{count - 1}"
                header = QTreeWidgetItem([f"{title}  {summary}"])
                header.setFlags(header.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                self.alerts_tree.addTopLevelItem(header)

                for _key, icon, time_str, ch_name, channel_db_id in airings[:10]:
                    child = QTreeWidgetItem([f"{icon} {ch_name}  ·  {time_str}"])
                    child.setData(0, Qt.ItemDataRole.UserRole, channel_db_id)
                    child.setToolTip(0, f"{title}\n{ch_name}")
                    header.addChild(child)

            self.set_empty(False)
            QTimer.singleShot(0, self._apply_expansion)
        except Exception as e:
            logger.error(f"WatchAlertsSection refresh error: {e}")
            self.set_empty(True)
        finally:
            session.close()

    def refresh_retry(self, entries: list) -> None:
        """Populate the stream retry sub-list from StreamRetryDB entries."""
        self._retry_list.clear()
        if not entries:
            self._retry_hdr_container.hide()
            self._retry_list.hide()
            return

        from datetime import datetime, timezone
        now = datetime.utcnow()

        for entry in entries:
            icon = self.config.stream_retry_online_icon if entry.status == "online" \
                else self.config.stream_retry_pending_icon
            item = QListWidgetItem(f"{icon}  {entry.channel_name}")
            item.setData(Qt.ItemDataRole.UserRole,     entry.id)
            item.setData(Qt.ItemDataRole.UserRole + 1, entry.channel_id)
            item.setData(Qt.ItemDataRole.UserRole + 2, entry.stream_url)
            item.setData(Qt.ItemDataRole.UserRole + 3, entry.channel_name)

            # Tooltip
            attempts = entry.attempt_count or 0
            error_line = f"Error: {entry.last_error}" if entry.last_error else "No error detail"
            if entry.next_check_at and entry.status == "pending":
                delta = entry.next_check_at - now
                secs = max(0, int(delta.total_seconds()))
                if secs < 3600:
                    next_check = f"{secs // 60}m"
                else:
                    next_check = f"{secs // 3600}h {(secs % 3600) // 60}m"
                timing = f"Next check in {next_check}"
            else:
                timing = "Back online!" if entry.status == "online" else ""

            item.setToolTip(
                f"{entry.channel_name}\n{error_line}\nAttempts: {attempts}\n{timing}"
            )
            self._retry_list.addItem(item)

        self._retry_hdr_container.show()
        self._retry_list.show()

    def _on_retry_double_clicked(self, item: "QListWidgetItem") -> None:
        channel_id   = item.data(Qt.ItemDataRole.UserRole + 1)
        stream_url   = item.data(Qt.ItemDataRole.UserRole + 2)
        channel_name = item.data(Qt.ItemDataRole.UserRole + 3) or ""
        if channel_id and stream_url:
            self.retryPlayRequested.emit(channel_id, stream_url, channel_name)

    def _on_retry_context_menu(self, pos) -> None:
        item = self._retry_list.itemAt(pos)
        if not item:
            return
        entry_id   = item.data(Qt.ItemDataRole.UserRole)
        channel_id = item.data(Qt.ItemDataRole.UserRole + 1)
        gp = self._retry_list.viewport().mapToGlobal(pos)
        self.retryContextMenuRequested.emit(entry_id, channel_id or "", gp.x(), gp.y())

    def _apply_expansion(self) -> None:
        """Expand all items if they all fit in the visible tree height; otherwise expand none."""
        tree = self.alerts_tree
        n = tree.topLevelItemCount()
        if n == 0:
            return
        row_h = tree.sizeHintForRow(0)
        if row_h <= 0:
            row_h = 22
        visible_h = tree.viewport().height()
        if visible_h <= 0:
            visible_h = tree.height()
        if visible_h <= 0:
            return
        max_rows = visible_h // row_h
        total_if_expanded = sum(
            1 + tree.topLevelItem(i).childCount()
            for i in range(n)
        )
        expand_all = total_if_expanded <= max_rows
        for i in range(n):
            tree.topLevelItem(i).setExpanded(expand_all)


class HistorySection(CollapsibleSection):
    """Playback history section"""
    
    historyItemClicked = pyqtSignal(str)  # channel_id (double-click)
    itemSelected = pyqtSignal(str)  # channel_id (single-click)
    clearHistoryClicked = pyqtSignal()
    
    def __init__(self, config, db, parent=None):
        self.db = db
        super().__init__("History", config.history_icon, config, parent)
    
    def get_section_id(self):
        return "history"
    
    def create_content(self):
        """Create history list and clear button"""
        from PyQt6.QtWidgets import QListWidget
        
        # History list
        self.history_list = QListWidget()
        self.history_list.setMaximumHeight(150)
        self.history_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history_list.itemDoubleClicked.connect(self.on_history_item_clicked)
        self.history_list.currentItemChanged.connect(self.on_history_item_selected)
        self.content_layout.addWidget(self.history_list)
        
        # Clear button
        self.clear_btn = QPushButton(f"{self.config.delete_icon} Clear History")
        self.clear_btn.clicked.connect(self.clearHistoryClicked.emit)
        self.content_layout.addWidget(self.clear_btn)
    
    def refresh(self):
        """Load history from database — shows all providers, no filtering"""
        from metatv.core.models import MediaType

        self.history_list.clear()

        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            adult_mode = getattr(self.config, "filter_adult_mode", "all")
            recent = repos.channels.get_recent_history(limit=30, adult_mode=adult_mode)

            self.set_empty(len(recent) == 0)

            if len(recent) == 0:
                return

            for channel in recent:
                from PyQt6.QtWidgets import QListWidgetItem
                item = QListWidgetItem(self.history_list)

                media_icon = self.get_media_icon(channel.media_type)

                if channel.media_type == MediaType.SERIES:
                    last_episode = repos.episodes.get_last_played(
                        series_id=channel.source_id,
                        provider_id=channel.provider_id
                    )
                    if last_episode:
                        episode_code = f"S{last_episode.season_num:02d}E{last_episode.episode_num:02d}"
                        item.setText(f"{media_icon} {channel.name}\n   → {episode_code}")
                    else:
                        item.setText(f"{media_icon} {channel.name}")
                else:
                    item.setText(f"{media_icon} {channel.name}")

                item.setData(Qt.ItemDataRole.UserRole, channel.id)
        finally:
            session.close()
    
    def get_media_icon(self, media_type):
        """Get icon for media type"""
        from metatv.core.models import MediaType
        if media_type == MediaType.LIVE:
            return self.config.live_icon
        elif media_type == MediaType.MOVIE:
            return self.config.movie_icon
        elif media_type == MediaType.SERIES:
            return self.config.series_icon
        return self.config.unknown_icon
    
    def on_history_item_clicked(self, item):
        """Handle history item double-click"""
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        if channel_id:
            self.historyItemClicked.emit(channel_id)
    
    def on_history_item_selected(self, current, previous):
        """Handle history item single-click selection"""
        if not current:
            return
        channel_id = current.data(Qt.ItemDataRole.UserRole)
        if channel_id:
            self.itemSelected.emit(channel_id)


class FavoritesSection(CollapsibleSection):
    """Favorites section"""

    favoriteClicked = pyqtSignal(str)  # channel_id (double-click)
    itemSelected = pyqtSignal(str)  # channel_id (single-click)

    def __init__(self, config, db, parent=None):
        self.db = db
        super().__init__("Favorites", config.favorite_icon, config, parent)

        # Favorites should expand to fill remaining space
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

    def get_section_id(self):
        return "favorites"

    def create_header(self):
        header = QWidget()
        header.setStyleSheet("background-color: rgba(255, 255, 255, 0.05);")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(5, 3, 5, 3)
        self.toggle_btn = QPushButton(self.config.collapse_icon)
        self.toggle_btn.setFixedSize(20, 20)
        self.toggle_btn.clicked.connect(self.toggle_collapse)
        hl.addWidget(self.toggle_btn)
        self.title_label = QLabel(
            f'<span style="color:#FFD700">{self.icon}</span> <b>{self.title}</b>'
        )
        self.title_label.setTextFormat(Qt.TextFormat.RichText)
        hl.addWidget(self.title_label)
        hl.addStretch()
        self.main_layout.addWidget(header)

    def create_content(self):
        """Create favorites list"""
        from PyQt6.QtWidgets import QListWidget
        
        self.favorites_list = QListWidget()
        self.favorites_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.favorites_list.itemDoubleClicked.connect(self.on_favorite_clicked)
        self.favorites_list.currentItemChanged.connect(self.on_favorite_selected)
        self.content_layout.addWidget(self.favorites_list)
    
    def refresh(self):
        """Load favorites from database — shows all providers, no filtering"""
        self.favorites_list.clear()

        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            adult_mode = getattr(self.config, "filter_adult_mode", "all")
            all_favorites = repos.channels.get_favorites(adult_mode=adult_mode)
            
            self.set_empty(len(all_favorites) == 0)
            
            if len(all_favorites) == 0:
                from PyQt6.QtWidgets import QListWidgetItem
                item = QListWidgetItem("No favorites yet")
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                self.favorites_list.addItem(item)
                item = QListWidgetItem("Right-click any channel to add to favorites")
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                self.favorites_list.addItem(item)
                return
            
            # Separate into continue watching and never watched
            continue_watching = [c for c in all_favorites if c.last_played]
            never_watched = [c for c in all_favorites if not c.last_played]
            
            # Sort
            continue_watching.sort(key=lambda c: c.last_played, reverse=True)
            never_watched.sort(key=lambda c: c.name)
            
            # Add headers and items
            if continue_watching:
                self.add_header("Continue Watching")
                for channel in continue_watching:
                    self.add_favorite_item(channel)
            
            if never_watched:
                self.add_header("Never Watched")
                for channel in never_watched:
                    self.add_favorite_item(channel)
        finally:
            session.close()

    def add_header(self, text):
        """Add a section header"""
        from PyQt6.QtWidgets import QListWidgetItem
        from PyQt6.QtGui import QFont
        
        item = QListWidgetItem(text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        font = QFont()
        font.setBold(True)
        item.setFont(font)
        self.favorites_list.addItem(item)
    
    def add_favorite_item(self, channel):
        """Add a favorite channel item"""
        from PyQt6.QtWidgets import QListWidgetItem
        
        item = QListWidgetItem(self.favorites_list)
        
        # Get media type icon
        media_icon = self.get_media_icon(channel.media_type)
        
        item.setText(f"{media_icon} {channel.name}")
        item.setData(Qt.ItemDataRole.UserRole, channel.id)
    
    def get_media_icon(self, media_type):
        """Get icon for media type"""
        from metatv.core.models import MediaType
        if media_type == MediaType.LIVE:
            return self.config.live_icon
        elif media_type == MediaType.MOVIE:
            return self.config.movie_icon
        elif media_type == MediaType.SERIES:
            return self.config.series_icon
        return self.config.unknown_icon
    
    def on_favorite_clicked(self, item):
        """Handle favorite item double-click"""
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        if channel_id:
            self.favoriteClicked.emit(channel_id)
    
    def on_favorite_selected(self, current, previous):
        """Handle favorite item single-click selection"""
        if not current:
            return
        channel_id = current.data(Qt.ItemDataRole.UserRole)
        if channel_id:
            self.itemSelected.emit(channel_id)


class RecommendedSection(CollapsibleSection):
    """Sidebar section showing top VOD recommendations from the preference engine."""

    itemSelected              = pyqtSignal(str, str)  # channel_id, reason
    itemDoubleClicked         = pyqtSignal(str)        # channel_id
    channelContextMenuRequested = pyqtSignal(str, int, int)  # channel_id, gx, gy

    def __init__(self, config, db, parent=None):
        self.db = db
        super().__init__("Recommended", config.preferences_icon, config, parent)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

    def get_section_id(self):
        return "recommended"

    def create_header(self):
        header = QWidget()
        header.setStyleSheet("background-color: rgba(255, 255, 255, 0.05);")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(5, 3, 5, 3)

        self.toggle_btn = QPushButton(self.config.collapse_icon)
        self.toggle_btn.setFixedSize(20, 20)
        self.toggle_btn.clicked.connect(self.toggle_collapse)
        hl.addWidget(self.toggle_btn)

        self.title_label = QLabel(f"{self.config.preferences_icon} <b>Recommended</b>")
        hl.addWidget(self.title_label)
        hl.addStretch()

        refresh_btn = QPushButton(self.config.refresh_icon)
        refresh_btn.setFixedSize(22, 20)
        refresh_btn.setToolTip("Refresh recommendations")
        refresh_btn.clicked.connect(self.refresh)
        hl.addWidget(refresh_btn)

        self.main_layout.addWidget(header)

    def create_content(self):
        self._list = QListWidget()
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.itemDoubleClicked.connect(self._on_double_click)
        self._list.currentItemChanged.connect(self._on_selection_changed)
        self._list.customContextMenuRequested.connect(self._on_context_menu)
        self.content_layout.addWidget(self._list)
        self.set_empty(True)

    def refresh(self):
        from metatv.core.preference_engine import compute_weights, score_candidates
        from metatv.core.filter_utils import get_active_category_filter
        from metatv.core.models import MediaType

        self._list.clear()
        included_prefixes, include_uncategorized = get_active_category_filter(self.config)
        session = self.db.get_session()
        try:
            weights = compute_weights(session)
            if weights.is_empty():
                item = QListWidgetItem("Rate movies/series to get recommendations")
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                self._list.addItem(item)
                self.set_empty(True)
                return
            recs = score_candidates(
                session, weights, limit=20,
                muted_attrs=getattr(self.config, 'muted_attributes', None),
                dedupe_overrides=set(getattr(self.config, 'rec_dedupe_overrides', [])),
                included_prefixes=included_prefixes,
                include_uncategorized=include_uncategorized,
            )
        finally:
            session.close()

        if not recs:
            item = QListWidgetItem("No recommendations yet — rate more content")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(item)
            self.set_empty(True)
            return

        for sc in recs:
            media_icon = (
                self.config.movie_icon if sc.media_type == "movie"
                else self.config.series_icon
            )
            liked_prefix = f"{self.config.like_icon} " if sc.already_liked else ""
            item = QListWidgetItem(f"{liked_prefix}{media_icon} {sc.channel_name}")
            item.setData(Qt.ItemDataRole.UserRole, sc.channel_id)
            item.setData(Qt.ItemDataRole.UserRole + 1, sc.reason)
            item.setData(Qt.ItemDataRole.UserRole + 2, sc.variant_count)
            rating_tip = f"  ★{sc.metadata_rating:.1f}/10" if sc.metadata_rating else ""
            shown_tip = f"\nShown {sc.rec_shown_count}×" if sc.rec_shown_count else ""
            variant_tip = f"\n{sc.variant_count} versions grouped" if sc.variant_count > 1 else ""
            item.setToolTip(
                f"{sc.reason}{rating_tip}{shown_tip}{variant_tip}\n"
                f"Genres: {', '.join(sc.matching_genres) or '—'}"
            )
            self._list.addItem(item)

        # Record impressions after rendering — open a fresh session (prior one is closed)
        imp_session = self.db.get_session()
        try:
            from metatv.core.preference_engine import record_impressions
            record_impressions(imp_session, [sc.channel_id for sc in recs])
        finally:
            imp_session.close()

        self.set_empty(False)

    def _on_double_click(self, item: QListWidgetItem) -> None:
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        if channel_id:
            self.itemDoubleClicked.emit(channel_id)

    def _on_selection_changed(self, current: QListWidgetItem, _previous) -> None:
        if current:
            channel_id = current.data(Qt.ItemDataRole.UserRole)
            reason = current.data(Qt.ItemDataRole.UserRole + 1) or ""
            if channel_id:
                self.itemSelected.emit(channel_id, reason)

    def _on_context_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        if not item:
            return
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        if not channel_id:
            return
        variant_count = item.data(Qt.ItemDataRole.UserRole + 2) or 1
        gp = self._list.viewport().mapToGlobal(pos)
        if variant_count > 1:
            from PyQt6.QtCore import QPoint
            from PyQt6.QtWidgets import QMenu
            menu = QMenu(self)
            sep_action = menu.addAction(f"≠  Show {variant_count} versions separately")
            menu.addSeparator()
            more_action = menu.addAction("More options...")
            chosen = menu.exec(QPoint(gp.x(), gp.y()))
            if chosen == sep_action:
                self._on_show_separately(channel_id)
            elif chosen == more_action:
                self.channelContextMenuRequested.emit(channel_id, gp.x(), gp.y())
        else:
            self.channelContextMenuRequested.emit(channel_id, gp.x(), gp.y())

    def _on_show_separately(self, channel_id: str) -> None:
        overrides: list = list(getattr(self.config, 'rec_dedupe_overrides', []))
        if channel_id not in overrides:
            overrides.append(channel_id)
            self.config.rec_dedupe_overrides = overrides
            self.config.save()
        self.refresh()


class WatchQueueSection(CollapsibleSection):
    """Sidebar section showing the user's ordered watch queue."""

    itemDoubleClicked           = pyqtSignal(str)        # channel_id
    itemSelected                = pyqtSignal(str)        # channel_id
    channelContextMenuRequested = pyqtSignal(str, int, int)  # channel_id, gx, gy
    clearQueueClicked           = pyqtSignal()
    clearWatchedClicked         = pyqtSignal()

    def __init__(self, config, db, parent=None):
        self.db = db
        super().__init__("Watch Queue", config.queue_icon, config, parent)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

    def get_section_id(self):
        return "queue"

    def create_content(self):
        self._list = QListWidget()
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.itemDoubleClicked.connect(self._on_double_click)
        self._list.currentItemChanged.connect(self._on_selection_changed)
        self._list.customContextMenuRequested.connect(self._on_context_menu)
        self.content_layout.addWidget(self._list)

        btn_row = QHBoxLayout()
        self._clear_watched_btn = QPushButton(f"{self.config.watched_icon} Clear Watched")
        self._clear_watched_btn.clicked.connect(self.clearWatchedClicked.emit)
        btn_row.addWidget(self._clear_watched_btn)

        self._clear_all_btn = QPushButton(f"{self.config.delete_icon} Clear All")
        self._clear_all_btn.clicked.connect(self.clearQueueClicked.emit)
        btn_row.addWidget(self._clear_all_btn)
        self.content_layout.addLayout(btn_row)

        self.set_empty(True)

    def _media_icon(self, media_type: str) -> str:
        if media_type == "movie":
            return self.config.movie_icon
        if media_type == "series":
            return self.config.series_icon
        if media_type == "live":
            return self.config.live_icon
        return self.config.unknown_icon

    def _add_header(self, text: str) -> None:
        item = QListWidgetItem(text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        font = QFont()
        font.setBold(True)
        item.setFont(font)
        self._list.addItem(item)

    def refresh(self):
        self._list.clear()
        entries = []
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            entries = repos.queue.get_all()
        except Exception as e:
            logger.error(f"WatchQueueSection refresh error: {e}")
        finally:
            session.close()

        self.set_empty(len(entries) == 0)
        if not entries:
            item = QListWidgetItem("Queue is empty — right-click any channel to add")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(item)
            return

        # Split into continue-watching (has last_played) and not-yet-started.
        # Use e.last_played (eagerly copied) to avoid DetachedInstanceError.
        continue_watching = sorted(
            [e for e in entries if e.last_played],
            key=lambda e: e.last_played,
            reverse=True,
        )
        never_watched = [e for e in entries if not e.last_played]

        if continue_watching:
            self._add_header("Continue Watching")
            for e in continue_watching:
                item = QListWidgetItem(f"{self._media_icon(e.media_type)} {e.channel_name}")
                item.setData(Qt.ItemDataRole.UserRole, e.channel_id)
                self._list.addItem(item)

        if never_watched:
            self._add_header("Never Watched")
            for e in never_watched:
                item = QListWidgetItem(f"{self._media_icon(e.media_type)} {e.channel_name}")
                item.setData(Qt.ItemDataRole.UserRole, e.channel_id)
                self._list.addItem(item)

    def _on_double_click(self, item: QListWidgetItem) -> None:
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        if channel_id:
            self.itemDoubleClicked.emit(channel_id)

    def _on_selection_changed(self, current: QListWidgetItem, _previous) -> None:
        if current:
            channel_id = current.data(Qt.ItemDataRole.UserRole)
            if channel_id:
                self.itemSelected.emit(channel_id)

    def _on_context_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        if not item:
            return
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        if channel_id:
            gp = self._list.viewport().mapToGlobal(pos)
            self.channelContextMenuRequested.emit(channel_id, gp.x(), gp.y())

