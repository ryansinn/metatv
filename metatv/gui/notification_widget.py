"""Notification widget for displaying progress toasts"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer

from metatv.core.notifications import Notification, NotificationType
from metatv.core.config import Config
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme


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
            bg_color = _theme.COLOR_NOTIFY_ERR_BG
            border_color = _theme.COLOR_NOTIFY_ERR_BORDER
            text_color = _theme.COLOR_TEXT_HI
        elif self.notification.type == NotificationType.SUCCESS:
            bg_color = _theme.COLOR_NOTIFY_OK_BG
            border_color = _theme.COLOR_NOTIFY_OK_BORDER
            text_color = _theme.COLOR_TEXT_HI
        elif self.notification.type == NotificationType.WARNING:
            bg_color = _theme.COLOR_NOTIFY_WARN_BG
            border_color = _theme.COLOR_NOTIFY_WARN_BORDER
            text_color = _theme.COLOR_TEXT_HI
        else:  # INFO and PROGRESS
            bg_color = _theme.COLOR_NOTIFY_INFO_BG
            border_color = _theme.COLOR_ACCENT_BLUE
            text_color = _theme.COLOR_TEXT_HI

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
                background-color: {_theme.OVERLAY_10};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Header with title and close button
        header_layout = QHBoxLayout()

        icon_map = {
            NotificationType.PROGRESS: _icons.notification_progress_icon,
            NotificationType.SUCCESS: _icons.notification_success_icon,
            NotificationType.ERROR: _icons.notification_error_icon,
            NotificationType.WARNING: _icons.notification_warning_icon,
            NotificationType.INFO: _icons.notification_info_icon
        }
        icon = icon_map.get(self.notification.type, "")

        self.title_label = QLabel(f"{icon} {self.notification.title}")
        _bold = self.title_label.font()
        _bold.setBold(True)
        self.title_label.setFont(_bold)
        header_layout.addWidget(self.title_label)

        header_layout.addStretch()

        if self.notification.dismissible:
            close_btn = QPushButton(_icons.close_icon)
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
                    f"QPushButton {{ font-size: 11px; font-weight: bold; border: 1px solid {_theme.COLOR_MUTED_2};"
                    " border-radius: 3px; padding: 2px 8px; }"
                    f"QPushButton:hover {{ background: {_theme.OVERLAY_15}; }}"
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

    def update_notification(self, notification: Notification):
        """Update notification display"""
        self.notification = notification

        # Update title
        icon_map = {
            NotificationType.PROGRESS: _icons.notification_progress_icon,
            NotificationType.SUCCESS: _icons.notification_success_icon,
            NotificationType.ERROR: _icons.notification_error_icon,
            NotificationType.WARNING: _icons.notification_warning_icon,
            NotificationType.INFO: _icons.notification_info_icon
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
        self._reposition_timer = QTimer(self)
        self._reposition_timer.setSingleShot(True)
        self._reposition_timer.setInterval(0)
        self._reposition_timer.timeout.connect(self.reposition)
        self.setup_ui()

    def setup_ui(self):
        """Set up notification widget"""
        self.setParent(self.parent())

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(10, 10, 10, 10)
        self._layout.setSpacing(8)
        self._layout.addStretch()

        self.setFixedWidth(420)
        self.reposition()

    def _schedule_reposition(self):
        """Queue a reposition on the next event loop tick, coalescing rapid calls."""
        if not self._reposition_timer.isActive():
            self._reposition_timer.start()

    def reposition(self):
        """Reposition widget in bottom-right corner based on actual content size."""
        if self.parent():
            parent_rect = self.parent().rect()
            self.adjustSize()
            x = parent_rect.width() - self.width() - 20
            y = parent_rect.height() - self.height() - 20
            self.move(x, max(0, y))
            self.raise_()

    def update_notifications(self, notifications):
        """Update displayed notifications"""
        # Remove cards for notifications that are no longer visible
        current_ids = {n.id for n in notifications}
        for notif_id in list(self.notification_cards.keys()):
            if notif_id not in current_ids:
                card = self.notification_cards.pop(notif_id)
                self._layout.removeWidget(card)
                card.deleteLater()

        # Update or add notifications
        for notification in notifications:
            if notification.id in self.notification_cards:
                card = self.notification_cards[notification.id]
                if card._notification_type != notification.type:
                    # Type changed (e.g. PROGRESS → SUCCESS) — rebuild card
                    self._layout.removeWidget(card)
                    card.deleteLater()
                    del self.notification_cards[notification.id]
                    # Fall through to create a fresh card below.
                else:
                    card.update_notification(notification)
                    continue

            # New card (or rebuilt after type change)
            card = NotificationCard(notification, self.config, self)
            self.notification_cards[notification.id] = card
            # Insert before the trailing stretch
            self._layout.insertWidget(self._layout.count() - 1, card)

        if notifications:
            self.show()
            # Defer repositioning — Qt must process the layout/show events first
            # so that adjustSize() sees the correct child geometry.
            self._schedule_reposition()
        else:
            self.hide()

    def dismiss_notification(self, notification_id: str):
        """Dismiss a notification"""
        self.notification_manager.dismiss(notification_id)
