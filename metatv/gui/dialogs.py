"""Dialogs for various operations"""

from datetime import datetime
from typing import Optional
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QComboBox, QPushButton, QLabel,
    QProgressBar, QTextEdit, QDialogButtonBox,
    QListWidget, QListWidgetItem, QWidget
)
from loguru import logger

from metatv.core.config import Config
from metatv.core.database import Database, ProviderDB
from metatv.core.models import Provider
from metatv.core.notifications import NotificationManager
from metatv.core.provider_loader import ProviderTestThread
from metatv.core.repositories import RepositoryFactory


class AddProviderDialog(QDialog):
    """Dialog for adding a new IPTV provider"""
    
    def __init__(self, parent, config: Config, db: Database, notification_manager: NotificationManager):
        super().__init__(parent)
        self.config = config
        self.db = db
        self.notification_manager = notification_manager
        self.test_thread: Optional[ProviderTestThread] = None
        self._fetched_account_info: Optional[dict] = None
        self.setup_ui()
    
    def setup_ui(self):
        """Set up dialog UI"""
        self.setWindowTitle("Add IPTV Provider")
        self.setMinimumWidth(500)
        
        layout = QVBoxLayout(self)
        
        # Form
        form = QFormLayout()
        
        self.name_input = QLineEdit()
        form.addRow("Name:", self.name_input)
        
        self.type_combo = QComboBox()
        self.type_combo.addItems(["Xtream", "M3U (coming soon)"])
        form.addRow("Type:", self.type_combo)
        
        # Multiple URL entries
        url_container = QWidget()
        url_layout = QVBoxLayout(url_container)
        url_layout.setContentsMargins(0, 0, 0, 0)
        
        # URL list with priorities
        self.url_list = QListWidget()
        self.url_list.setMaximumHeight(100)
        url_layout.addWidget(QLabel("DNS/URLs (priority order):"))
        url_layout.addWidget(self.url_list)
        
        # URL input and buttons
        url_input_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("http://example.com:8000")
        url_input_layout.addWidget(self.url_input)
        
        add_url_btn = QPushButton("+")
        add_url_btn.setFixedWidth(30)
        add_url_btn.setToolTip("Add URL")
        add_url_btn.clicked.connect(self.add_url)
        url_input_layout.addWidget(add_url_btn)
        
        remove_url_btn = QPushButton("-")
        remove_url_btn.setFixedWidth(30)
        remove_url_btn.setToolTip("Remove selected URL")
        remove_url_btn.clicked.connect(self.remove_url)
        url_input_layout.addWidget(remove_url_btn)
        
        url_layout.addLayout(url_input_layout)
        form.addRow("", url_container)
        
        self.username_input = QLineEdit()
        form.addRow("Username:", self.username_input)
        
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Password:", self.password_input)
        
        layout.addLayout(form)
        
        # Progress area
        self.progress_label = QLabel("")
        self.progress_label.hide()
        layout.addWidget(self.progress_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)
        
        # Status text
        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setMaximumHeight(100)
        self.status_text.hide()
        layout.addWidget(self.status_text)
        
        # Buttons
        button_box = QDialogButtonBox()
        
        self.test_button = button_box.addButton("Test Connection", QDialogButtonBox.ButtonRole.ActionRole)
        self.test_button.clicked.connect(self.test_connection)
        
        self.add_button = button_box.addButton("Add Provider", QDialogButtonBox.ButtonRole.AcceptRole)
        self.add_button.clicked.connect(self.add_provider)
        self.add_button.setEnabled(False)
        
        cancel_button = button_box.addButton(QDialogButtonBox.StandardButton.Cancel)
        cancel_button.clicked.connect(self.reject)
        
        layout.addWidget(button_box)
    
    def add_url(self):
        """Add URL to list"""
        url = self.url_input.text().strip()
        if url:
            self.url_list.addItem(url)
            self.url_input.clear()
    
    def remove_url(self):
        """Remove selected URL from list"""
        current_row = self.url_list.currentRow()
        if current_row >= 0:
            self.url_list.takeItem(current_row)
    
    def get_urls(self):
        """Get list of URLs with priorities"""
        urls = []
        for i in range(self.url_list.count()):
            urls.append(self.url_list.item(i).text())
        return urls
    
    def test_connection(self):
        """Test connection to provider"""
        provider_type = "xtream" if self.type_combo.currentIndex() == 0 else "m3u"
        
        # Get URLs (try list first, then input field)
        urls = self.get_urls()
        if not urls:
            url = self.url_input.text().strip()
            if not url:
                self.status_text.show()
                self.status_text.setText("Please enter at least one URL")
                return
            urls = [url]
        
        # Test with first URL
        url = urls[0]
        username = self.username_input.text().strip()
        password = self.password_input.text().strip()
        
        self.progress_label.setText("Testing connection...")
        self.progress_label.show()
        self.status_text.show()
        self.status_text.clear()
        self.test_button.setEnabled(False)
        
        # Run test in thread
        self.test_thread = ProviderTestThread(provider_type, url, username, password)
        self.test_thread.progress.connect(self.on_test_progress)
        self.test_thread.result.connect(self.on_test_result)
        self.test_thread.start()
    
    def on_test_progress(self, message: str):
        """Handle test progress update"""
        self.status_text.append(f"• {message}")
    
    def on_test_result(self, success: bool, message: str):
        """Handle test result — on success, fetch and display account info."""
        self.test_button.setEnabled(True)
        self.progress_label.hide()

        if success:
            self.status_text.append(f"\n✓ {message}")
            self.add_button.setEnabled(True)
            self._fetch_account_info()
        else:
            self.status_text.append(f"\n✗ {message}")
            self.add_button.setEnabled(False)

    def _fetch_account_info(self):
        """Fetch account/subscription info and append to status log."""
        urls = self.get_urls()
        if not urls:
            url = self.url_input.text().strip()
            if url:
                urls = [url]
        if not urls:
            return

        username = self.username_input.text().strip()
        password = self.password_input.text().strip()

        from metatv.core.models import ProviderURL
        from metatv.gui.provider_editor import FetchAccountInfoThread

        temp_provider = Provider(
            id="__temp__",
            name="temp",
            type="xtream",
            url=urls[0],
            urls=[ProviderURL(url=u) for u in urls],
            username=username,
            password=password,
        )

        self.status_text.append("\n⟳ Fetching account info…")
        self._acct_thread = FetchAccountInfoThread(temp_provider)
        self._acct_thread.finished.connect(self._on_account_info)
        self._acct_thread.start()

    def _on_account_info(self, success: bool, result):
        """Append parsed account info to the status log."""
        if not success:
            self.status_text.append(f"  ⚠ Account info unavailable: {result}")
            return

        info = result
        self._fetched_account_info = info  # stored for saving with the provider

        status = info.get("status", "Unknown")
        status_icon = self.config.notification_success_icon if status.lower() == "active" else self.config.notification_warning_icon
        lines = [f"\n{status_icon} Account: {status}"]

        exp_ts = info.get("exp_date")
        if exp_ts:
            try:
                exp_dt = datetime.fromtimestamp(int(exp_ts))
                days_left = (exp_dt - datetime.now()).days
                lines.append(f"  Expires:     {exp_dt.strftime('%Y-%m-%d')}  ({days_left} days remaining)")
            except Exception:
                pass

        created_ts = info.get("created_at")
        if created_ts:
            try:
                created_dt = datetime.fromtimestamp(int(created_ts))
                lines.append(f"  Created:     {created_dt.strftime('%Y-%m-%d')}")
            except Exception:
                pass

        active = info.get("active_cons", 0)
        max_c = info.get("max_connections", 1)
        lines.append(f"  Connections: {active} active / {max_c} max")

        if info.get("is_trial"):
            lines.append("  ⚠ Trial account")

        server = info.get("server_info", {})
        if server.get("timezone"):
            lines.append(f"  Server TZ:   {server['timezone']}")

        self.status_text.append("\n".join(lines))
    
    def add_provider(self):
        """Add the provider"""
        provider_type = "xtream" if self.type_combo.currentIndex() == 0 else "m3u"
        
        # Get URLs
        urls = self.get_urls()
        if not urls:
            url = self.url_input.text().strip()
            if url:
                urls = [url]
        
        if not urls:
            self.status_text.show()
            self.status_text.setText("Please enter at least one URL")
            return
        
        # Create provider
        import uuid
        from metatv.core.models import ProviderURL
        provider = Provider(
            id=str(uuid.uuid4()),
            name=self.name_input.text().strip() or "Unnamed Provider",
            type=provider_type,
            url=urls[0],  # Primary URL
            username=self.username_input.text().strip(),
            password=self.password_input.text().strip()
        )
        
        # Create ProviderURL objects for all URLs
        provider_urls = []
        for i, url in enumerate(urls):
            provider_urls.append({
                'url': url,
                'priority': i,
                'success_count': 0,
                'failure_count': 0,
                'last_success': None,
                'last_failure': None,
                'recent_attempts': [],
                'failed_client_ips': {}
            })
        
        # Auto-assign a colored icon if none is set
        from metatv.gui.icons import pick_next_icon
        icon_session = self.db.get_session()
        try:
            icon_repos = RepositoryFactory(icon_session)
            used_icons = icon_repos.providers.get_used_icons()
        finally:
            icon_session.close()
        assigned_icon = pick_next_icon(used_icons)

        # Save to database
        session = self.db.get_session()
        try:
            db_provider = ProviderDB(
                id=provider.id,
                name=provider.name,
                type=provider.type,
                url=provider.url,
                urls=provider_urls,
                username=provider.username,
                password=provider.password,
                icon=assigned_icon,
            )
            # Persist account info fetched during test (if available)
            if self._fetched_account_info:
                info = self._fetched_account_info
                db_provider.account_status = info.get("status")
                db_provider.max_connections = info.get("max_connections", 1)
                db_provider.account_active_cons = info.get("active_cons", 0)
                try:
                    exp_ts = info.get("exp_date")
                    if exp_ts:
                        db_provider.account_exp_date = datetime.fromtimestamp(int(exp_ts))
                    created_ts = info.get("created_at")
                    if created_ts:
                        db_provider.account_created_at = datetime.fromtimestamp(int(created_ts))
                except Exception:
                    pass
            session.add(db_provider)
            session.commit()
        finally:
            session.close()
        
        # Close dialog immediately
        self.accept()
        
        # Signal main window to refresh the provider (which will load channels)
        if self.parent():
            # Refresh sidebar to show new provider
            self.parent().load_providers()
            # Start loading channels from this provider
            self.parent().refresh_provider(provider.id)
    
    def show_status(self, message: str, error: bool = False):
        """Show status message"""
        self.status_text.show()
        prefix = self.config.notification_error_icon if error else self.config.notification_info_icon
        self.status_text.append(f"{prefix} {message}")
