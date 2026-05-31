"""Notification widget for displaying progress toasts"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QProgressBar, QPushButton, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, QPropertyAnimation, QRect
from PyQt6.QtGui import QPalette, QColor

from metatv.core.notifications import Notification, NotificationType
from metatv.core.config import Config


class NotificationCard(QFrame):
    """Single notification card"""
    
    def __init__(self, notification: Notification, config: Config, parent=None):
        super().__init__(parent)
        self.notification = notification
        self.config = config
        self.setup_ui()
    
    def setup_ui(self):
        """Set up notification UI"""
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self.setMinimumWidth(380)
        self.setMaximumWidth(440)
        
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        
        # Style based on type
        if self.notification.type == NotificationType.ERROR:
            bg_color = "#2c1515"
            border_color = "#ff4444"
            text_color = "#ffffff"
        elif self.notification.type == NotificationType.SUCCESS:
            bg_color = "#152c15"
            border_color = "#44ff44"
            text_color = "#ffffff"
        elif self.notification.type == NotificationType.WARNING:
            bg_color = "#2c2415"
            border_color = "#ffaa44"
            text_color = "#ffffff"
        else:  # INFO and PROGRESS
            bg_color = "#1a1a2e"
            border_color = "#4488ff"
            text_color = "#ffffff"
        
        self.setStyleSheet(f"""
            NotificationCard {{
                background-color: {bg_color};
                border: 2px solid {border_color};
                border-radius: 6px;
            }}
            QLabel {{
                color: {text_color};
            }}
            QPushButton {{
                color: {text_color};
                background-color: transparent;
                border: none;
                font-size: 18px;
            }}
            QPushButton:hover {{
                background-color: rgba(255, 255, 255, 0.1);
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        
        # Header with title and close button
        header_layout = QHBoxLayout()
        
        # Icon based on type
        icon_map = {
            NotificationType.PROGRESS: self.config.notification_progress_icon,
            NotificationType.SUCCESS: self.config.notification_success_icon,
            NotificationType.ERROR: self.config.notification_error_icon,
            NotificationType.WARNING: self.config.notification_warning_icon,
            NotificationType.INFO: self.config.notification_info_icon
        }
        icon = icon_map.get(self.notification.type, "")
        
        self.title_label = QLabel(f"{icon} {self.notification.title}")
        _bold = self.title_label.font()
        _bold.setBold(True)
        self.title_label.setFont(_bold)
        header_layout.addWidget(self.title_label)
        
        header_layout.addStretch()
        
        if self.notification.dismissible:
            close_btn = QPushButton(self.config.close_icon)
            close_btn.setFixedSize(20, 20)
            close_btn.clicked.connect(self.dismiss)
            header_layout.addWidget(close_btn)
        
        layout.addLayout(header_layout)
        
        # Message
        if self.notification.message:
            self.message_label = QLabel(self.notification.message)
            self.message_label.setWordWrap(True)
            layout.addWidget(self.message_label)
        
        # Action buttons (e.g. "Undo")
        if self.notification.actions:
            action_layout = QHBoxLayout()
            action_layout.setContentsMargins(0, 4, 0, 0)
            action_layout.addStretch()
            for label, callback in self.notification.actions:
                btn = QPushButton(label)
                btn.setStyleSheet(
                    "QPushButton { font-size: 11px; font-weight: bold; border: 1px solid #666;"
                    " border-radius: 3px; padding: 2px 8px; }"
                    "QPushButton:hover { background: rgba(255,255,255,0.15); }"
                )
                btn.setToolTip(label)
                btn.clicked.connect(lambda _, cb=callback: (cb(), self.dismiss()))
                action_layout.addWidget(btn)
            layout.addLayout(action_layout)

        # Progress bar for progress notifications
        if self.notification.type == NotificationType.PROGRESS:
            progress_layout = QHBoxLayout()
            
            self.progress_bar = QProgressBar()
            self.progress_bar.setMaximum(100)
            if self.notification.progress is not None:
                self.progress_bar.setValue(int(self.notification.progress * 100))
            progress_layout.addWidget(self.progress_bar)
            
            layout.addLayout(progress_layout)
            
            # Progress text — always created, shown once we have a total
            self.progress_label = QLabel("")
            self.progress_label.setVisible(False)
            layout.addWidget(self.progress_label)
        
        # Record the type used to style this card — used to detect changes in update_notifications
        self._notification_type = self.notification.type

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        """Compute height at a given width, correctly propagating word-wrap from QLabels.

        Qt's default sizeHint() for word-wrapped labels returns the unwrapped height
        until the widget has been rendered. This method computes the correct height
        analytically so reposition() works before the first paint event.
        """
        lyt = self.layout()
        m = lyt.contentsMargins()
        inner_w = max(0, width - m.left() - m.right())
        heights = []
        for i in range(lyt.count()):
            item = lyt.itemAt(i)
            if not item:
                continue
            w = item.widget()
            sub = item.layout()
            if w and w.isVisible():
                if w.hasHeightForWidth():
                    heights.append(w.heightForWidth(inner_w))
                else:
                    heights.append(w.sizeHint().height())
            elif sub:
                h = sub.sizeHint().height()
                if h > 0:
                    heights.append(h)
        if not heights:
            return m.top() + m.bottom()
        total = m.top() + m.bottom() + sum(heights) + lyt.spacing() * (len(heights) - 1)
        return total

    def update_notification(self, notification: Notification):
        """Update notification display"""
        self.notification = notification
        
        # Update title
        icon_map = {
            NotificationType.PROGRESS: self.config.notification_progress_icon,
            NotificationType.SUCCESS: self.config.notification_success_icon,
            NotificationType.ERROR: self.config.notification_error_icon,
            NotificationType.WARNING: self.config.notification_warning_icon,
            NotificationType.INFO: self.config.notification_info_icon
        }
        icon = icon_map.get(notification.type, "")
        self.title_label.setText(f"{icon} {notification.title}")
        
        # Update message if exists
        if hasattr(self, 'message_label') and notification.message:
            self.message_label.setText(notification.message)
        
        # Update progress
        if hasattr(self, 'progress_bar') and notification.progress is not None:
            self.progress_bar.setValue(int(notification.progress * 100))
        
        if hasattr(self, 'progress_label'):
            if notification.progress_current is not None and notification.progress_total is not None:
                progress_text = f"{notification.progress_current:,} / {notification.progress_total:,}"
                percentage = int(notification.progress * 100) if notification.progress else 0
                self.progress_label.setText(f"{progress_text} ({percentage}%)")
                if not self.progress_label.isVisible():
                    self.progress_label.setVisible(True)
        
        self.updateGeometry()
        self.adjustSize()
    
    def dismiss(self):
        """Dismiss this notification"""
        if self.parent():
            self.parent().dismiss_notification(self.notification.id)


class NotificationWidget(QWidget):
    """Widget to display notifications in bottom-right corner"""
    
    def __init__(self, notification_manager, config, parent=None):
        super().__init__(parent)
        self.notification_manager = notification_manager
        self.config = config
        self.notification_cards = {}
        self.setup_ui()
    
    def setup_ui(self):
        """Set up notification widget"""
        # Make widget a child widget (not a separate window)
        self.setParent(self.parent())
        
        # Layout for stacking notifications
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(10, 10, 10, 10)
        self.layout.setSpacing(8)
        self.layout.addStretch()
        
        # Set fixed width
        self.setFixedWidth(420)
        
        # Position in bottom-right
        self.reposition()
    
    def reposition(self):
        """Reposition widget in bottom-right corner"""
        if self.parent():
            parent_rect = self.parent().rect()
            
            # Calculate height based on actual card heights
            self.updateGeometry()
            
            # Sum up heights of all cards plus margins and spacing
            cm = self.layout.contentsMargins()
            total_height = cm.top() + cm.bottom()
            # Card width is the container width minus its own margins
            card_w = self.width() - cm.left() - cm.right()
            visible_cards = 0
            for i in range(self.layout.count()):
                item = self.layout.itemAt(i)
                widget = item.widget() if item else None
                if widget and widget.isVisible():
                    if widget.hasHeightForWidth():
                        total_height += widget.heightForWidth(card_w)
                    else:
                        total_height += widget.sizeHint().height()
                    visible_cards += 1
            if visible_cards > 1:
                total_height += self.layout.spacing() * (visible_cards - 1)
            
            # Ensure we don't exceed parent height
            widget_height = min(total_height, parent_rect.height() - 100)
            
            # Position in bottom-right with margins
            x = parent_rect.width() - self.width() - 20
            y = parent_rect.height() - widget_height - 20
            
            self.setGeometry(x, y, self.width(), widget_height)
            self.raise_()
    
    def update_notifications(self, notifications):
        """Update displayed notifications"""
        # Remove notifications that are no longer visible
        current_ids = {n.id for n in notifications}
        for notif_id in list(self.notification_cards.keys()):
            if notif_id not in current_ids:
                card = self.notification_cards.pop(notif_id)
                self.layout.removeWidget(card)
                card.deleteLater()
        
        # Update or add notifications
        for notification in notifications:
            if notification.id in self.notification_cards:
                card = self.notification_cards[notification.id]
                if card._notification_type != notification.type:
                    # Type changed (e.g. INFO → ERROR) — tear down and rebuild so
                    # the stylesheet and action buttons reflect the new type.
                    self.layout.removeWidget(card)
                    card.deleteLater()
                    del self.notification_cards[notification.id]
                    # Fall through to create a fresh card below.
                else:
                    card.update_notification(notification)
                    continue

            # Add new card (or replacement after type change)
            card = NotificationCard(notification, self.config, self)
            self.notification_cards[notification.id] = card
            # Insert before stretch
            self.layout.insertWidget(self.layout.count() - 1, card)
            card.adjustSize()
            card.updateGeometry()
        
        # Show/hide widget
        if notifications:
            self.show()
            # Force layout update before repositioning
            self.layout.update()
            self.updateGeometry()
            self.reposition()
        else:
            self.hide()
    
    def dismiss_notification(self, notification_id: str):
        """Dismiss a notification"""
        self.notification_manager.dismiss(notification_id)
