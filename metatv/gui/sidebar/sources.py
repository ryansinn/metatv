"""Sources sidebar section — provider list with refresh/edit/toggle actions."""

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt, pyqtSignal

from metatv.core.repositories import RepositoryFactory
from metatv.gui import theme as _theme
from metatv.gui.sidebar.base import CollapsibleSection


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


class SourcesSection(CollapsibleSection):
    """Sources provider list section"""

    providerSelected = pyqtSignal(str)         # provider_id
    providerRefreshClicked = pyqtSignal(str)   # provider_id
    providerEditClicked = pyqtSignal(str)      # provider_id
    providerToggleClicked = pyqtSignal(str)    # provider_id
    addProviderClicked = pyqtSignal()
    refreshAllClicked = pyqtSignal()

    def __init__(self, config, db, parent=None):
        self.db = db
        super().__init__("Sources", config.provider_icon, config, parent)

    def get_section_id(self):
        return "sources"

    def create_header(self):
        """Override to add '+' button in the header instead of bottom buttons."""
        header = QWidget()
        header.setStyleSheet(_theme.HEADER_TINT)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(5, 3, 5, 3)

        self.toggle_btn = QPushButton(self.config.collapse_icon)
        self.toggle_btn.setFixedSize(20, 20)
        self.toggle_btn.clicked.connect(self.toggle_collapse)
        header_layout.addWidget(self.toggle_btn)

        self.title_label = QLabel(f"{self.config.provider_icon} <b>Sources</b>")
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()

        _btn_style = (
            "QPushButton {{ font-size: {fs}px; font-weight: bold; border: 1px solid {c};"
            " border-radius: 3px; color: {c}; background: {bg}; }}"
            "QPushButton:hover {{ background: {hbg}; }}"
        )
        refresh_all_btn = QPushButton(self.config.refresh_icon)
        refresh_all_btn.setFixedSize(22, 20)
        refresh_all_btn.setToolTip("Refresh all sources")
        refresh_all_btn.setStyleSheet(_btn_style.format(
            fs=13, c="#aaa",
            bg="rgba(255,255,255,0.05)", hbg="rgba(255,255,255,0.15)",
        ))
        refresh_all_btn.clicked.connect(self.refreshAllClicked.emit)
        header_layout.addWidget(refresh_all_btn)

        add_btn = QPushButton("+")
        add_btn.setFixedSize(22, 20)
        add_btn.setToolTip("Add Source…")
        add_btn.setStyleSheet(_btn_style.format(
            fs=14, c="#4488ff",
            bg="rgba(68,136,255,0.1)", hbg="rgba(68,136,255,0.3)",
        ))
        add_btn.clicked.connect(self.addProviderClicked.emit)
        header_layout.addWidget(add_btn)

        self.main_layout.addWidget(header)

    def create_content(self):
        """Create sources tree (no bottom buttons — they moved to the header)."""
        from PyQt6.QtWidgets import QTreeWidget
        self.sources_tree = QTreeWidget()
        self.sources_tree.setHeaderHidden(True)
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
