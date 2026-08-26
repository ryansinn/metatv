"""The Stream Monitoring group: streams that failed and are being retried.

The smallest of the four groups — it renders a list the recovery machinery
hands it and offers a context menu. Split from :mod:`alerts` for the reason
given in :mod:`alerts_epg`.
"""

from __future__ import annotations


from PyQt6.QtWidgets import QListWidgetItem
from datetime import datetime
from PyQt6.QtCore import Qt
from metatv.gui import icons as _icons


class StreamMonitoringMixin:
    def _update_retry_toggle_label(self, count: int) -> None:
        """Refresh the Stream Monitoring heading's count."""
        self._retry_toggle.set_count(count or None)

    def _toggle_stream_monitoring(self) -> None:
        self._retry_collapsed = not self._retry_collapsed
        if self._retry_collapsed:
            self._retry_list.hide()
        else:
            self._retry_list.show()
        self._update_retry_toggle_label(self._retry_list.count())

    def refresh_retry(self, entries: list) -> None:
        """Populate the stream retry sub-list from StreamRetryDB entries."""
        self._retry_list.clear()
        if not entries:
            self._retry_hdr_container.hide()
            self._retry_list.hide()
            self._recompute_empty()
            return

        from datetime import datetime, timezone
        now = datetime.utcnow()

        for entry in entries:
            icon = _icons.stream_retry_online_icon if entry.status == "online" \
                else _icons.stream_retry_pending_icon
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

        count = self._retry_list.count()
        self._update_retry_toggle_label(count)
        self._retry_hdr_container.show()
        if not self._retry_collapsed:
            self._retry_list.show()
            self._recompute_empty()

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
