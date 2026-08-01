"""WatchQueueSection — user's ordered watch queue."""

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QSizePolicy, QListWidget, QListWidgetItem,
    QGraphicsOpacityEffect,
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QFont

from metatv.core.repositories import RepositoryFactory
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.chip_row import build_chip_row
from metatv.gui.sidebar.background_refresh import BackgroundRefreshMixin
from metatv.gui.sidebar.base import CollapsibleSection

_ROLE_AVAILABLE   = Qt.ItemDataRole.UserRole + 1
_ROLE_SEARCH_TITLE = Qt.ItemDataRole.UserRole + 2

_UNAVAILABLE_TOOLTIP = "Source unavailable — double-click to find this on another source."


class WatchQueueSection(BackgroundRefreshMixin, CollapsibleSection):
    """Sidebar section showing the user's ordered watch queue."""

    # Uses the base ``create_header``, which grows the shared "Explore →" link.
    EXPLORE_KEY = "queue"

    itemDoubleClicked             = pyqtSignal(str)        # channel_id (channel-grain entries)
    episodeActivated              = pyqtSignal(str)        # episode_id — double-click on an episode-grain entry
    itemSelected                  = pyqtSignal(str)        # channel_id
    channelMiddleClicked          = pyqtSignal(str)        # channel_id — configured middle-click play
    channelContextMenuRequested   = pyqtSignal(str, int, int)  # channel_id, gx, gy
    clearQueueClicked             = pyqtSignal()           # demoted to the ⋯ overflow menu
    clearWatchedClicked           = pyqtSignal()
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
        self._new_matches_btn.clicked.connect(self.newMatchesClicked.emit)
        self._new_matches_btn.hide()
        self.content_layout.addWidget(self._new_matches_btn)

        self._list = QListWidget()
        # Chip rows fit the sidebar width and elide — never scroll sideways (which
        # would push the right-aligned year/language chips off behind the scrollbar).
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.itemDoubleClicked.connect(self._on_double_click)
        self._list.currentItemChanged.connect(self._on_selection_changed)
        self._list.customContextMenuRequested.connect(self._on_context_menu)
        # Middle-click plays the user-configured action (same seam as the channel
        # list) via the shared QListWidget helper — no per-section handler copy.
        from metatv.gui.list_middle_click import install_list_middle_click
        self._list_mc = install_list_middle_click(self._list)
        self._list_mc.middleClicked.connect(self.channelMiddleClicked)
        _theme.apply_list_selection(self._list)
        self.content_layout.addWidget(self._list)

        btn_row = QHBoxLayout()
        self._clear_watched_btn = QPushButton(f"{self.config.watched_icon} Clear Watched")
        self._clear_watched_btn.clicked.connect(self.clearWatchedClicked.emit)
        btn_row.addWidget(self._clear_watched_btn)

        # "Clear All" is demoted from an always-visible button into a compact ⋯
        # overflow menu — the destructive bulk action is one step removed.
        from PyQt6.QtWidgets import QMenu
        self._overflow_btn = QPushButton(_icons.overflow_icon)
        self._overflow_btn.setFlat(True)
        self._overflow_btn.setFixedWidth(28)  # structural
        self._overflow_btn.setToolTip("More…")
        self._overflow_menu = QMenu(self._overflow_btn)
        clear_all_action = self._overflow_menu.addAction(
            f"{self.config.delete_icon} Clear All"
        )
        clear_all_action.setToolTip("Remove everything from the queue")
        clear_all_action.triggered.connect(self.clearQueueClicked.emit)
        self._overflow_btn.clicked.connect(self._show_overflow_menu)
        btn_row.addWidget(self._overflow_btn)
        self.content_layout.addLayout(btn_row)

        self.set_empty(True)

    def _show_overflow_menu(self) -> None:
        """Pop the ⋯ overflow menu just below the button."""
        below = self._overflow_btn.rect().bottomLeft()
        self._overflow_menu.exec(self._overflow_btn.mapToGlobal(below))

    def update_new_match_count(self, count: int) -> None:
        """Show/hide the pinned green new-matches banner.

        The bulk "Clear Alerts" action now lives in the Alerts header, so this
        only drives the pinned banner (unchanged behavior).

        Args:
            count: Number of unviewed watch-for matches across all rules.
        """
        try:
            line = self._new_matches_btn
        except (AttributeError, RuntimeError):
            return  # content not built (e.g. __new__ test stub) — nothing to update
        if line is None:
            return
        if count > 0:
            line.setText(
                f"{_icons.watchlist_on_icon} {count} new match"
                f"{'es' if count != 1 else ''} from your alerts  "
                f"{_icons.see_all_arrow_icon}"
            )
            line.setToolTip("Open the new matched content from your watch-for alerts")
            line.show()
        else:
            line.hide()

    # --- BackgroundRefreshMixin hooks ---
    def _refresh_list(self) -> QListWidget:
        return self._list

    def _load_error_message(self) -> str:
        return "Couldn't load watch queue"

    def _load_rows(self):
        from metatv.core.vod_alert_availability import compute_alert_availability
        with self.db.session_scope() as session:
            repos = RepositoryFactory(session)
            hidden = set(repos.providers.get_hidden_provider_ids())
            entries = repos.queue.get_all(hidden_provider_ids=hidden)
            # Re-validate the pinned banner's count against live source state (same
            # session): matches on disabled/expired sources must not count here either.
            try:
                self._available_unviewed = compute_alert_availability(
                    self.config, repos
                ).unviewed_total
            except Exception:  # noqa: BLE001
                self._available_unviewed = None  # fall back to raw config count
            return entries

    def _populate_rows(self, entries) -> None:
        """Main-thread slot: populate the queue list from QueueEntry plain dataclasses."""
        # The pinned new-matches line is independent of queue contents (it reflects
        # config watch-for matches), so refresh it before the empty-list early-out.
        # Uses the AVAILABLE unviewed count (re-validated in _load_rows), not the raw
        # config total.  Guarded so partially-built __new__ test stubs don't trip.
        try:
            count = getattr(self, "_available_unviewed", None)
            if count is None:
                count = self.config.get_unviewed_vod_match_count()
            self.update_new_match_count(count)
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
        """Add a single queue entry as the shared chip row, dimming unavailable ones.

        UserRole carries a dict tagging the entry's grain (Wave 2 Slice 2B) so
        every reader (double-click, selection, context menu) can branch without a
        second lookup: channel-grain -> {"grain": "channel", "channel_id": ...};
        episode-grain -> {"grain": "episode", "episode_id": ..., "channel_id": ...}
        (channel_id there is still the PARENT SERIES, for the context-menu seam).
        """
        item = QListWidgetItem()
        if e.is_episode:
            item.setData(Qt.ItemDataRole.UserRole, {
                "grain": "episode",
                "episode_id": e.episode_id,
                "channel_id": e.channel_id,
            })
            code = (
                f"S{e.season_num:02d}E{e.episode_num:02d}" if e.season_num and e.episode_num
                else f"E{e.episode_num}" if e.episode_num else ""
            )
            title = f"{e.channel_name} — {code}" if code else e.channel_name
            if e.episode_title:
                title += f" {e.episode_title}"
        else:
            item.setData(Qt.ItemDataRole.UserRole, {
                "grain": "channel",
                "channel_id": e.channel_id,
            })
            title = e.search_title or e.channel_name
        item.setData(_ROLE_AVAILABLE, e.available)
        item.setData(_ROLE_SEARCH_TITLE, e.search_title)
        row = build_chip_row(
            media_icon=self._media_icon(e.media_type),
            title=title,
            year=e.detected_year,
            quality=e.detected_quality,
            prefix=e.detected_prefix,
        )
        if not e.available:
            # A custom item widget ignores the item's foreground role, so dim the whole
            # row via a translucency effect (opacity, not a colour literal) and keep the
            # recovery tooltip on the item (mouse-transparent row → item shows it).
            effect = QGraphicsOpacityEffect(row)
            effect.setOpacity(0.45)
            row.setGraphicsEffect(effect)
            item.setToolTip(_UNAVAILABLE_TOOLTIP)
        # Width 0 → the item spans the viewport (no sideways scroll); the row's own
        # height governs the row height.
        item.setSizeHint(QSize(0, row.sizeHint().height()))
        self._list.addItem(item)
        self._list.setItemWidget(item, row)

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
        payload = item.data(Qt.ItemDataRole.UserRole)
        if not payload:
            return
        available = item.data(_ROLE_AVAILABLE)
        if available is False:
            search_title = item.data(_ROLE_SEARCH_TITLE) or ""
            self.searchRequested.emit(search_title)
            return
        if payload.get("grain") == "episode":
            self.episodeActivated.emit(payload["episode_id"])
        else:
            self.itemDoubleClicked.emit(payload["channel_id"])

    def _on_selection_changed(self, current: QListWidgetItem, _previous) -> None:
        if current:
            payload = current.data(Qt.ItemDataRole.UserRole)
            channel_id = payload.get("channel_id") if payload else None
            if channel_id:
                # Episode-grain rows still resolve to the SERIES channel_id here —
                # showing the series' own details pane is the closest available
                # surface; a dedicated episode-detail seam from the queue is
                # deferred (Slice 2B scope: play/favorite/queue the episode, not
                # single-click detail routing).
                self.itemSelected.emit(channel_id)

    def _on_context_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        gp = self._list.viewport().mapToGlobal(pos)

        if item:
            payload = item.data(Qt.ItemDataRole.UserRole)
            channel_id = payload.get("channel_id") if payload else None
            if channel_id:
                # Emit signal so main_window builds the per-item context menu,
                # which will also append "Clear Unavailable" (see main_window_favorites.py).
                # Episode-grain rows target the PARENT SERIES' channel menu here —
                # channel_menu.py's registry is ChannelDB-only today (episode
                # favorite/queue actions live in the series-tree's own menu instead).
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
