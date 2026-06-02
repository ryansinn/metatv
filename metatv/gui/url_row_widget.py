"""URLRowWidget — single URL row for the provider editor URL list."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from metatv.core.models import ProviderURL
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme


class URLRowWidget(QWidget):
    """Single URL row: move up/down, live test result badge, stats, remove."""

    moveUp = pyqtSignal()
    moveDown = pyqtSignal()
    removed = pyqtSignal()

    def __init__(self, provider_url: ProviderURL, index: int, total: int, parent=None):
        super().__init__(parent)
        self.provider_url = provider_url
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # Order controls
        order_col = QVBoxLayout()
        order_col.setSpacing(1)
        self._up_btn = QPushButton(_icons.move_up_icon)
        self._up_btn.setFixedSize(22, 18)
        self._up_btn.setEnabled(index > 0)
        self._up_btn.clicked.connect(self.moveUp)
        self._down_btn = QPushButton(_icons.move_down_icon)
        self._down_btn.setFixedSize(22, 18)
        self._down_btn.setEnabled(index < total - 1)
        self._down_btn.clicked.connect(self.moveDown)
        order_col.addWidget(self._up_btn)
        order_col.addWidget(self._down_btn)
        layout.addLayout(order_col)

        # Priority badge
        badge = QLabel(f"#{index + 1}")
        badge.setFixedWidth(24)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(_theme.META_HINT)
        layout.addWidget(badge)

        # URL + stats column
        info_col = QVBoxLayout()
        info_col.setSpacing(2)

        url_label = QLabel(provider_url.url)
        url_label.setStyleSheet(_theme.FIELD_LABEL)
        url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        info_col.addWidget(url_label)

        self._stats_label = QLabel(self._build_stats(provider_url))
        self._stats_label.setStyleSheet(_theme.META_HINT)
        info_col.addWidget(self._stats_label)
        layout.addLayout(info_col, 1)

        # Live test result badge (hidden until a test runs)
        self._result_badge = QLabel("")
        self._result_badge.setFixedWidth(110)
        self._result_badge.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._result_badge.setStyleSheet(_theme.URL_BADGE)
        self._result_badge.hide()
        layout.addWidget(self._result_badge)

        # Remove button
        rm_btn = QPushButton(_icons.close_icon)
        rm_btn.setFixedSize(24, 24)
        rm_btn.setToolTip("Remove this URL")
        rm_btn.setStyleSheet(_theme.URL_REMOVE_BTN)
        rm_btn.clicked.connect(self.removed)
        layout.addWidget(rm_btn)

    def show_testing(self):
        """Show a 'Testing…' spinner while waiting for result."""
        self._result_badge.setText(f"{_icons.loading_icon} Testing…")
        self._result_badge.setStyleSheet(_theme.URL_BADGE_TESTING)
        self._result_badge.show()

    def show_test_result(self, success: bool, message: str):
        """Update badge with pass/fail result."""
        if success:
            self._result_badge.setText(f"{_icons.notification_success_icon}  {message}")
            self._result_badge.setStyleSheet(_theme.URL_BADGE_OK)
        else:
            self._result_badge.setText(f"{_icons.notification_error_icon}  {message}")
            self._result_badge.setStyleSheet(_theme.URL_BADGE_ERR)
        self._result_badge.show()

    def clear_test_result(self):
        self._result_badge.hide()
        self._result_badge.setText("")

    @staticmethod
    def _build_stats(pu: ProviderURL) -> str:
        total = pu.success_count + pu.failure_count
        if total == 0:
            return "Untested"
        ok = _icons.notification_success_icon
        err = _icons.notification_error_icon
        rel = f"{pu.reliability_score:.0f}% reliability"
        parts = [rel, f"{ok}{pu.success_count}", f"{err}{pu.failure_count}"]
        if pu.last_success:
            parts.append(f"last ok {pu.last_success.strftime('%m/%d')}")
        return "  ·  ".join(parts)
