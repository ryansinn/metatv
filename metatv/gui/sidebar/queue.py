"""WatchQueueSection — user's ordered watch queue."""

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QSizePolicy, QListWidget, QListWidgetItem,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont

from metatv.core.repositories import RepositoryFactory
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.sidebar.background_refresh import BackgroundRefreshMixin
from metatv.gui.sidebar.base import CollapsibleSection, _fmt_channel_name

_ROLE_AVAILABLE   = Qt.ItemDataRole.UserRole + 1
_ROLE_SEARCH_TITLE = Qt.ItemDataRole.UserRole + 2

_UNAVAILABLE_TOOLTIP = "Source unavailable — double-click to find this on another source."


class WatchQueueSection(BackgroundRefreshMixin, CollapsibleSection):
    """Sidebar section showing the user's ordered watch queue."""

    itemDoubleClicked             = pyqtSignal(str)        # channel_id
    itemSelected                  = pyqtSignal(str)        # channel_id
    channelMiddleClicked          = pyqtSignal(str)        # channel_id — configured middle-click play
    channelContextMenuRequested   = pyqtSignal(str, int, int)  # channel_id, gx, gy
    clearQueueClicked             = pyqtSignal()
    clearWatchedClicked           = pyqtSignal()
    clearAlertsClicked            = pyqtSignal()           # bulk-acknowledge all new matches
    clearUnavailableClicked       = pyqtSignal()           # request clear-unavailable
    newMatchesClicked             = pyqtSignal()           # open the new matched content
    searchRequested               = pyqtSignal(str)        # search_title for recovery
    _data_ready                   = pyqtSignal(object)     # list[QueueEntry] | None

    def __init__(self, config, db, parent=None):
        self.db = db
        self._has_unavailable = False
        super().__init__("Watch Queue", config.queue_icon, config, parent)
        self._init_background_refresh()
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

    def get_section_id(self):
        return "queue"

    def create_content(self):
        # Pinned GREEN "new matches from your alerts" line — a single clickable row
        # at the very top of the queue.  Hidden until there are unviewed matches;
        # clicking opens the matched content (where it is flagged 🚨/green).
        self._new_matches_btn = QPushButton()
        self._new_matches_btn.setStyleSheet(_theme.QUEUE_NEW_MATCHES_LINE)
        self._new_matches_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._new_matches_btn.clicked.connect(self.newMatchesClicked.emit)
        self._new_matches_btn.hide()
        self.content_layout.addWidget(self._new_matches_btn)

        self._list = QListWidget()
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.itemDoubleClicked.connect(self._on_double_click)
        self._list.currentItemChanged.connect(self._on_selection_changed)
        self._list.customContextMenuRequested.connect(self._on_context_menu)
        # Middle-click plays the user-configured action (same seam as the channel
        # list) via the shared QListWidget helper — no per-section handler copy.
        from metatv.gui.list_middle_click import install_list_middle_click
        self._list_mc = install_list_middle_click(self._list)
        self._list_mc.middleClicked.connect(self.channelMiddleClicked)
        self.content_layout.addWidget(self._list)

        btn_row = QHBoxLayout()
        self._clear_watched_btn = QPushButton(f"{self.config.watched_icon} Clear Watched")
        self._clear_watched_btn.clicked.connect(self.clearWatchedClicked.emit)
        btn_row.addWidget(self._clear_watched_btn)

        # Conditional "Clear Alerts" — shown only when unviewed matches exist.
        self._clear_alerts_btn = QPushButton(f"{_icons.new_match_icon} Clear Alerts")
        self._clear_alerts_btn.setToolTip(
            "Acknowledge all new matched content — clears the alert green everywhere"
        )
        self._clear_alerts_btn.clicked.connect(self.clearAlertsClicked.emit)
        self._clear_alerts_btn.hide()
        btn_row.addWidget(self._clear_alerts_btn)

        self._clear_all_btn = QPushButton(f"{self.config.delete_icon} Clear All")
        self._clear_all_btn.clicked.connect(self.clearQueueClicked.emit)
        btn_row.addWidget(self._clear_all_btn)
        self.content_layout.addLayout(btn_row)

        self.set_empty(True)

    def update_new_match_count(self, count: int) -> None:
        """Show/hide the pinned green new-matches line + Clear Alerts button.

        Args:
            count: Number of unviewed watch-for matches across all rules.
        """
        try:
            line = self._new_matches_btn
            clear_btn = self._clear_alerts_btn
        except (AttributeError, RuntimeError):
            return  # content not built (e.g. __new__ test stub) — nothing to update
        if count > 0:
            if line is not None:
                line.setText(
                    f"{_icons.watchlist_on_icon} {count} new match"
                    f"{'es' if count != 1 else ''} from your alerts  "
                    f"{_icons.see_all_arrow_icon}"
                )
                line.setToolTip("Open the new matched content from your watch-for alerts")
                line.show()
            if clear_btn is not None:
                clear_btn.show()
        else:
            if line is not None:
                line.hide()
            if clear_btn is not None:
                clear_btn.hide()

    # --- BackgroundRefreshMixin hooks ---
    def _refresh_list(self) -> QListWidget:
        return self._list

    def _load_error_message(self) -> str:
        return "Couldn't load watch queue"

    def _load_rows(self):
        with self.db.session_scope() as session:
            repos = RepositoryFactory(session)
            hidden = set(repos.providers.get_hidden_provider_ids())
            return repos.queue.get_all(hidden_provider_ids=hidden)

    def _populate_rows(self, entries) -> None:
        """Main-thread slot: populate the queue list from QueueEntry plain dataclasses."""
        # The pinned new-matches line is independent of queue contents (it reflects
        # config watch-for matches), so refresh it before the empty-list early-out.
        # Guarded so partially-built __new__ test stubs (no config/widgets) don't trip.
        try:
            self.update_new_match_count(self.config.get_unviewed_vod_match_count())
        except (AttributeError, RuntimeError):
            pass
        self._has_unavailable = any(not e.available for e in entries) if entries else False
        self.set_empty(len(entries) == 0)
        if not entries:
            item = QListWidgetItem("Queue is empty — right-click any channel to add")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(item)
            return

        continue_watching = sorted(
            [e for e in entries if e.last_played],
            key=lambda e: e.last_played,
            reverse=True,
        )
        never_watched = [e for e in entries if not e.last_played]

        if continue_watching:
            self._add_header("Continue Watching")
            for e in continue_watching:
                self._add_entry_item(e)

        if never_watched:
            self._add_header("Never Watched")
            for e in never_watched:
                self._add_entry_item(e)

    def _add_entry_item(self, e) -> None:
        """Add a single queue entry to the list, dimming unavailable ones."""
        item = QListWidgetItem(
            f"{self._media_icon(e.media_type)} {_fmt_channel_name(e.channel_name)}"
        )
        item.setData(Qt.ItemDataRole.UserRole, e.channel_id)
        item.setData(_ROLE_AVAILABLE, e.available)
        item.setData(_ROLE_SEARCH_TITLE, e.search_title)
        if not e.available:
            item.setForeground(QColor(_theme.COLOR_MUTED))
            item.setToolTip(_UNAVAILABLE_TOOLTIP)
        self._list.addItem(item)

    def has_unavailable(self) -> bool:
        """True when at least one entry in the current list is unavailable."""
        return self._has_unavailable

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

    def _on_double_click(self, item: QListWidgetItem) -> None:
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        if not channel_id:
            return
        available = item.data(_ROLE_AVAILABLE)
        if available is False:
            search_title = item.data(_ROLE_SEARCH_TITLE) or ""
            self.searchRequested.emit(search_title)
        else:
            self.itemDoubleClicked.emit(channel_id)

    def _on_selection_changed(self, current: QListWidgetItem, _previous) -> None:
        if current:
            channel_id = current.data(Qt.ItemDataRole.UserRole)
            if channel_id:
                self.itemSelected.emit(channel_id)

    def _on_context_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        gp = self._list.viewport().mapToGlobal(pos)

        if item:
            channel_id = item.data(Qt.ItemDataRole.UserRole)
            if channel_id:
                # Emit signal so main_window builds the per-item context menu,
                # which will also append "Clear Unavailable" (see main_window_favorites.py).
                self.channelContextMenuRequested.emit(channel_id, gp.x(), gp.y())
                return

        # Right-click on empty space or a header — still offer Clear Unavailable.
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QAction
        from PyQt6.QtCore import QPoint
        menu = QMenu(self)
        clear_act = QAction("Clear Unavailable", self)
        clear_act.setEnabled(self._has_unavailable)
        if not self._has_unavailable:
            clear_act.setToolTip("No unavailable content")
        clear_act.triggered.connect(self.clearUnavailableClicked.emit)
        menu.addAction(clear_act)
        menu.exec(QPoint(gp.x(), gp.y()))
