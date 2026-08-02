"""Sources manager — full-view provider list + configuration (Wave 6).

Replaces the old sidebar ``SourcesSection`` (see ``gui/sidebar/sources.py``,
which now only supplies :class:`ProviderItemWidget` and its helper — the
per-provider row widget this view reuses verbatim, same signals, never a
parallel implementation). Opened from the sidebar status strip
(``gui/sidebar/sources_strip.py``).

LEFT column: every provider as a selectable :class:`ProviderItemWidget` row —
the SAME widget (status dot / EPG pip / name / toggle / edit / analyze /
refresh buttons) the retired sidebar section rendered, so the visual language
and every action signal (refresh / analyze / toggle active / EPG refresh) are
unchanged; the host wires them to the exact same handlers
(``refresh_provider``, ``enter_provider_analytics_mode``,
``toggle_provider_active``, ``_on_provider_epg_refresh``) it always has.

CENTER: the host's single ``ProviderEditorView`` instance, embedded here
instead of added directly to the content stack — never a second instance /
parallel save-delete-refresh plumbing. Selecting a row calls
``load_provider()`` on it directly (in-view, no separate "edit mode" switch).
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from metatv.core.epg_utils import epg_status as _epg_status
from metatv.core.repositories import RepositoryFactory
from metatv.gui import cursor_affordance
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.sidebar.sources import ProviderItemWidget, _epg_tooltip

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database


class SourcesManagerView(QWidget):
    """Main-area Sources manager: provider list (left) + config (center)."""

    providerRefreshClicked = pyqtSignal(str)
    providerAnalyzeClicked = pyqtSignal(str)
    providerToggleClicked = pyqtSignal(str)
    providerEpgRefreshClicked = pyqtSignal(str)
    addProviderClicked = pyqtSignal()

    def __init__(
        self, config: "Config", db: "Database", provider_editor: QWidget, parent=None
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.db = db
        self._provider_editor = provider_editor
        # provider_ids with an operation in flight — survives refresh() rebuilds
        # (mirrors the retired SourcesSection's _busy_ids, same purpose).
        self._busy_ids: set[str] = set()
        self._item_widgets: dict[str, ProviderItemWidget] = {}
        self._selected_id: str | None = None

        self.setObjectName("sourcesManagerView")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 8, 10, 8)
        title = QLabel(f"{_icons.provider_icon} <b>Sources</b>")
        header_layout.addWidget(title)
        header_layout.addStretch()

        add_btn = QPushButton("+")
        add_btn.setFixedSize(24, 22)
        add_btn.setToolTip("Add Source…")
        add_btn.setStyleSheet(_theme.RECIPE_SAVED_ICON_BTN)
        cursor_affordance.set_clickable(add_btn)
        add_btn.clicked.connect(self.addProviderClicked.emit)
        header_layout.addWidget(add_btn)
        outer.addWidget(header)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        self.sources_tree = QTreeWidget()
        self.sources_tree.setHeaderHidden(True)
        self.sources_tree.setFixedWidth(280)
        self.sources_tree.itemClicked.connect(self._on_item_clicked)
        body_layout.addWidget(self.sources_tree)

        center = QWidget()
        self._center_layout = QVBoxLayout(center)
        self._center_layout.setContentsMargins(0, 0, 0, 0)
        self._center_layout.addWidget(self._provider_editor)

        self._empty_label = QLabel("Select a source on the left to view its configuration.")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setWordWrap(True)
        self._empty_label.setStyleSheet(_theme.EXPLORE_STATUS)
        self._center_layout.addWidget(self._empty_label)

        body_layout.addWidget(center, 1)
        outer.addWidget(body, 1)

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #
    def on_activate(self) -> None:
        """Rebuild the provider list and (re-)select a row.

        Keeps the previously-selected provider selected across re-activation
        when it still exists; otherwise falls back to the first row.
        """
        self.refresh()
        if self._selected_id and self._selected_id in self._item_widgets:
            self.select_provider(self._selected_id)
        elif self._item_widgets:
            self.select_provider(next(iter(self._item_widgets)))

    def on_deactivate(self) -> None:
        """Hide the embedded editor so a stale form isn't visible under another
        view (the row selection itself is kept for next activation)."""
        self._provider_editor.setVisible(False)

    # ------------------------------------------------------------------ #
    # Selection                                                            #
    # ------------------------------------------------------------------ #
    def _on_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        provider_id = item.data(0, Qt.ItemDataRole.UserRole)
        if provider_id:
            self.select_provider(provider_id)

    def select_provider(self, provider_id: str) -> None:
        """Load *provider_id* into the embedded editor and highlight its row."""
        if provider_id not in self._item_widgets:
            return
        self._selected_id = provider_id
        for i in range(self.sources_tree.topLevelItemCount()):
            item = self.sources_tree.topLevelItem(i)
            if item and item.data(0, Qt.ItemDataRole.UserRole) == provider_id:
                self.sources_tree.setCurrentItem(item)
                break
        self._empty_label.setVisible(False)
        self._provider_editor.setVisible(True)
        self._provider_editor.load_provider(provider_id)

    # ------------------------------------------------------------------ #
    # Data                                                                 #
    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        """Rebuild the provider tree from the database."""
        self.sources_tree.clear()
        self._item_widgets = {}

        from metatv.gui.provider_editor import subscription_color

        with self.db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            providers = repos.providers.get_all()
            now = datetime.now()

            for provider in providers:
                item = QTreeWidgetItem(self.sources_tree)
                item.setText(0, "")
                item.setData(0, Qt.ItemDataRole.UserRole, provider.id)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

                is_expired = bool(
                    provider.account_exp_date and provider.account_exp_date <= now
                )
                sub_color = ""
                if not is_expired and provider.account_exp_date:
                    sub_color = subscription_color(
                        provider.account_exp_date, provider.account_created_at
                    )
                icon = getattr(provider, "icon", "") or ""
                epg_state = _epg_status(
                    getattr(provider, "epg_url", None), getattr(provider, "epg_data_end", None)
                )
                epg_tooltip = _epg_tooltip(
                    epg_state, getattr(provider, "epg_data_start", None),
                    getattr(provider, "epg_data_end", None),
                )

                widget = ProviderItemWidget(
                    provider.id, provider.name,
                    is_active=provider.is_active,
                    icon=icon,
                    sub_color=sub_color,
                    is_expired=is_expired,
                    busy=provider.id in self._busy_ids,
                    epg_state=epg_state,
                    epg_tooltip=epg_tooltip,
                )
                self._item_widgets[provider.id] = widget
                widget.refreshClicked.connect(
                    lambda pid=provider.id: self.providerRefreshClicked.emit(pid)
                )
                widget.analyzeClicked.connect(
                    lambda pid=provider.id: self.providerAnalyzeClicked.emit(pid)
                )
                widget.toggleClicked.connect(
                    lambda pid=provider.id: self.providerToggleClicked.emit(pid)
                )
                widget.epgRefreshClicked.connect(
                    lambda pid=provider.id: self.providerEpgRefreshClicked.emit(pid)
                )
                # The pencil ("edit") action just focuses/loads this row's config —
                # selecting a row already shows it in the center pane, so there is
                # no separate "edit mode" to switch to.
                widget.editClicked.connect(
                    lambda pid=provider.id: self.select_provider(pid)
                )
                self.sources_tree.setItemWidget(item, 0, widget)

        if not providers:
            self._selected_id = None
            self._provider_editor.setVisible(False)
            self._empty_label.setText("No sources yet. Click + to add one.")
            self._empty_label.setVisible(True)

    # ------------------------------------------------------------------ #
    # Busy / EPG-spinner state — same external surface the retired sidebar
    # SourcesSection exposed, so MainWindow's existing call sites work
    # unchanged (see MainWindow._sources_status_target).
    # ------------------------------------------------------------------ #
    def is_provider_busy(self, provider_id: str) -> bool:
        return provider_id in self._busy_ids

    def set_provider_busy(self, provider_id: str, busy: bool) -> None:
        if busy:
            self._busy_ids.add(provider_id)
        else:
            self._busy_ids.discard(provider_id)
        widget = self._item_widgets.get(provider_id)
        if widget is not None:
            widget.set_busy(busy)

    def set_provider_epg_refreshing(self, provider_id: str, busy: bool) -> None:
        widget = self._item_widgets.get(provider_id)
        if widget is not None:
            widget.set_epg_refreshing(busy)

    def has_busy(self) -> bool:
        return bool(self._busy_ids)

    def clear_busy(self) -> None:
        for pid in list(self._busy_ids):
            self.set_provider_busy(pid, False)

    def update_provider_status(self, provider_id: str, status: str) -> None:
        """Legacy no-op — kept for interface parity with the retired sidebar
        section; widgets update via refresh()/set_provider_busy()."""
        pass

    def clear_selection(self) -> None:
        """Deselect any active row (interface parity with the retired section)."""
        self.sources_tree.clearSelection()
        self.sources_tree.setCurrentItem(None)
