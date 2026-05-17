"""Provider settings and URL management dialog"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QComboBox, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QGroupBox,
    QDialogButtonBox, QSpinBox, QWidget
)
from PyQt6.QtCore import Qt
from loguru import logger

from metatv.core.models import Provider, ProviderURL
from metatv.core.connection_tracker import ConnectionTracker


class URLListItem(QWidget):
    """Widget for displaying a provider URL with stats"""
    
    def __init__(self, provider_url: ProviderURL, parent=None):
        super().__init__(parent)
        self.provider_url = provider_url
        self.setup_ui()
    
    def setup_ui(self):
        """Set up URL item UI"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        
        # Priority controls
        priority_widget = QWidget()
        priority_layout = QVBoxLayout(priority_widget)
        priority_layout.setContentsMargins(0, 0, 0, 0)
        priority_layout.setSpacing(2)
        
        up_btn = QPushButton("▲")
        up_btn.setFixedSize(24, 20)
        up_btn.setToolTip("Move up")
        up_btn.clicked.connect(self.move_up)
        priority_layout.addWidget(up_btn)

        down_btn = QPushButton("▼")
        down_btn.setFixedSize(24, 20)
        down_btn.setToolTip("Move down")
        down_btn.clicked.connect(self.move_down)
        priority_layout.addWidget(down_btn)
        
        layout.addWidget(priority_widget)
        
        # URL and stats
        info_layout = QVBoxLayout()
        
        # URL
        url_label = QLabel(self.provider_url.url)
        url_label.setStyleSheet("font-weight: bold;")
        info_layout.addWidget(url_label)
        
        # Stats
        stats_text = self.get_stats_text()
        stats_label = QLabel(stats_text)
        stats_label.setStyleSheet("font-size: 10pt; color: gray;")
        info_layout.addWidget(stats_label)
        
        layout.addLayout(info_layout, 1)
        
        # Actions
        action_layout = QVBoxLayout()
        
        reset_btn = QPushButton("Reset Stats")
        reset_btn.clicked.connect(self.reset_stats)
        action_layout.addWidget(reset_btn)
        
        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(self.remove_url)
        action_layout.addWidget(remove_btn)
        
        layout.addLayout(action_layout)
    
    def get_stats_text(self) -> str:
        """Get statistics text"""
        url = self.provider_url
        parts = [
            f"Status: {url.status}",
            f"Reliability: {url.reliability_score:.1f}%",
            f"Success: {url.success_count}",
            f"Failures: {url.failure_count}"
        ]
        
        # Show blocked IPs if any
        if url.failed_client_ips:
            blocked_ips = [ip for ip in url.failed_client_ips.keys() if url.is_ip_blocked(ip)]
            if blocked_ips:
                parts.append(f"⚠ Blocked IPs: {', '.join(blocked_ips[:2])}")
        
        if url.last_success:
            parts.append(f"Last success: {url.last_success.strftime('%Y-%m-%d %H:%M')}")
        if url.last_failure:
            parts.append(f"Last failure: {url.last_failure.strftime('%Y-%m-%d %H:%M')}")
        
        return " | ".join(parts)
    
    def move_up(self):
        """Move URL priority up"""
        if self.provider_url.priority > 0:
            self.provider_url.priority -= 1
            if self.parent():
                self.parent().refresh_list()
    
    def move_down(self):
        """Move URL priority down"""
        self.provider_url.priority += 1
        if self.parent():
            self.parent().refresh_list()
    
    def reset_stats(self):
        """Reset connection statistics"""
        ConnectionTracker.reset_stats(self.provider_url)
        if self.parent():
            self.parent().refresh_list()
    
    def remove_url(self):
        """Remove this URL"""
        if self.parent():
            self.parent().remove_url(self.provider_url)


class ProviderSettingsDialog(QDialog):
    """Dialog for managing provider settings"""
    
    def __init__(self, provider: Provider, parent=None):
        super().__init__(parent)
        self.provider = provider
        self.setup_ui()
    
    def setup_ui(self):
        """Set up dialog UI"""
        self.setWindowTitle(f"Provider Settings - {self.provider.name}")
        self.setMinimumWidth(700)
        self.setMinimumHeight(500)
        
        layout = QVBoxLayout(self)
        
        # Basic settings
        basic_group = QGroupBox("Basic Settings")
        basic_layout = QFormLayout(basic_group)
        
        self.name_input = QLineEdit(self.provider.name)
        basic_layout.addRow("Name:", self.name_input)
        
        self.refresh_combo = QComboBox()
        self.refresh_combo.addItems([
            "Manual",
            "On App Launch",
            "Daily",
            "Weekly",
            "Every 30 Days"
        ])
        refresh_map = {
            "manual": 0,
            "launch": 1,
            "daily": 2,
            "weekly": 3,
            "monthly": 4
        }
        self.refresh_combo.setCurrentIndex(refresh_map.get(self.provider.refresh_schedule, 0))
        basic_layout.addRow("Refresh Schedule:", self.refresh_combo)
        
        layout.addWidget(basic_group)
        
        # URL management
        url_group = QGroupBox("URLs (in priority order)")
        url_layout = QVBoxLayout(url_group)
        
        # URL list
        self.url_list = QListWidget()
        self.refresh_url_list()
        url_layout.addWidget(self.url_list)
        
        # Add URL controls
        add_layout = QHBoxLayout()
        self.new_url_input = QLineEdit()
        self.new_url_input.setPlaceholderText("http://newprovider.com:8000")
        add_layout.addWidget(self.new_url_input)
        
        add_btn = QPushButton("Add URL")
        add_btn.clicked.connect(self.add_url)
        add_layout.addWidget(add_btn)
        
        url_layout.addLayout(add_layout)
        
        layout.addWidget(url_group)
        
        # Buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | 
            QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
    
    def refresh_url_list(self):
        """Refresh URL list display"""
        self.url_list.clear()
        
        # Ensure we have the primary URL in the list
        if not self.provider.urls:
            self.provider.urls = [
                ProviderURL(url=self.provider.url, priority=0)
            ]
        
        # Sort by priority
        sorted_urls = sorted(self.provider.urls, key=lambda u: u.priority)
        
        for url in sorted_urls:
            item = QListWidgetItem()
            widget = URLListItem(url, self)
            item.setSizeHint(widget.sizeHint())
            self.url_list.addItem(item)
            self.url_list.setItemWidget(item, widget)
    
    def add_url(self):
        """Add new URL"""
        new_url = self.new_url_input.text().strip()
        if not new_url:
            return
        
        # Check for duplicates
        if any(u.url == new_url for u in self.provider.urls):
            logger.warning(f"URL already exists: {new_url}")
            return
        
        # Add with next priority
        max_priority = max((u.priority for u in self.provider.urls), default=-1)
        new_provider_url = ProviderURL(
            url=new_url,
            priority=max_priority + 1
        )
        self.provider.urls.append(new_provider_url)
        
        self.new_url_input.clear()
        self.refresh_url_list()
    
    def remove_url(self, provider_url: ProviderURL):
        """Remove URL from list"""
        if len(self.provider.urls) <= 1:
            logger.warning("Cannot remove last URL")
            return
        
        self.provider.urls.remove(provider_url)
        self.refresh_url_list()
    
    def refresh_list(self):
        """Refresh the display"""
        self.refresh_url_list()
    
    def accept(self):
        """Save settings and close"""
        self.provider.name = self.name_input.text()
        
        schedule_map = {
            0: "manual",
            1: "launch",
            2: "daily",
            3: "weekly",
            4: "monthly"
        }
        self.provider.refresh_schedule = schedule_map.get(
            self.refresh_combo.currentIndex(), 
            "manual"
        )
        
        # Update primary URL to highest priority active URL
        best_url = ConnectionTracker.get_best_url(self.provider.urls)
        if best_url:
            self.provider.url = best_url.url
        
        super().accept()
