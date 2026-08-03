"""Sources manager — full-view provider list + configuration (Wave 6, Wave 7).

Replaces the old sidebar ``SourcesSection`` (see ``gui/sidebar/sources.py``,
which now only supplies :class:`ProviderItemWidget` and its helper — the
per-provider row widget this view reuses verbatim, same signals, never a
parallel implementation). Opened from the sidebar status strip
(``gui/sidebar/sources_strip.py``).

LEFT column: every provider as a selectable :class:`ProviderItemWidget` row,
constructed with ``show_actions=False`` (Wave 7) — status dot, provider name
(no longer truncated), and expiry/inactive state only. The five per-row icon
buttons (refresh / edit / analyze / toggle / EPG-refresh) the pre-Wave-7 row
rendered now live in the embedded editor's Summary-tab action bar
(``ProviderEditorView._build_action_bar``); this view's public
``providerRefreshClicked``/``providerAnalyzeClicked``/``providerToggleClicked``/
``providerEpgRefreshClicked`` signals are unchanged (so ``main_window.py``'s
handler wiring for them is untouched) — they now fire from the editor's action
bar via the pass-through connections in ``__init__`` instead of from row
buttons. The "edit" action needed no re-pointing: selecting a row already
loads it into the editor, so there was never a separate "edit mode" to invoke.

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

from metatv.core.repositories import RepositoryFactory
from metatv.gui import cursor_affordance
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.sidebar.sources import ProviderItemWidget

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

        self._add_btn = QPushButton("+")
        self._add_btn.setFixedSize(24, 22)
        self._add_btn.setToolTip("Add Source…")
        self._add_btn.setStyleSheet(_theme.RECIPE_SAVED_ICON_BTN)
        cursor_affordance.set_clickable(self._add_btn)
        self._add_btn.clicked.connect(self.addProviderClicked.emit)
        header_layout.addWidget(self._add_btn)
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

        # Pass-through wiring (Wave 7): the editor's action bar replaced the row
        # buttons as the source of these clicks — re-point by relaying the
        # editor's new per-action signals onto this view's EXISTING public
        # signals, so main_window.py's handler connections need no changes.
        # Refresh is the one exception: it reuses the editor's pre-existing
        # (previously unemitted) `refresh_requested` signal, already connected
        # directly to `self.refresh_provider` on this same embedded instance —
        # no pass-through needed here for it.
        self._provider_editor.analyze_requested.connect(self.providerAnalyzeClicked.emit)
        self._provider_editor.toggle_active_requested.connect(self.providerToggleClicked.emit)
        self._provider_editor.epg_refresh_requested.connect(self.providerEpgRefreshClicked.emit)

        self._empty_label = QLabel("Select a source on the left to view its configuration.")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setWordWrap(True)
        self._empty_label.setStyleSheet(_theme.EXPLORE_STATUS)
        self._center_layout.addWidget(self._empty_label)

        body_layout.addWidget(center, 1)
        outer.addWidget(body, 1)

    def refresh_theme(self) -> None:
        """Re-apply the active palette to this view's own persistent chrome
        (the "+" add button and the "select a source" empty-state label,
        both styled once at construction) and forward to the embedded
        ``ProviderEditorView``, which has its own ``refresh_theme()`` — same
        recursion pattern as ``MainWindow.refresh_theme()`` forwarding to
        ``details_pane``/``filter_panel``. The per-provider tree rows
        (``ProviderItemWidget``) are rebuilt fresh from current tokens on
        every ``refresh()`` (on_activate/select), so they need no sweep entry
        here — same rationale as the channel-list row delegate.
        """
        self._add_btn.setStyleSheet(_theme.RECIPE_SAVED_ICON_BTN)
        self._empty_label.setStyleSheet(_theme.EXPLORE_STATUS)
        if hasattr(self._provider_editor, "refresh_theme"):
            self._provider_editor.refresh_theme()

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
        # A busy toggle for this provider may have started while a different
        # row was selected (or before any row was) — resync the action bar's
        # busy visual so switching back to it mid-operation still shows it.
        self._provider_editor.set_toggle_busy(provider_id in self._busy_ids)

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

                # Wave 7: no action buttons/EPG pip on the row — status dot,
                # name, expiry state only (see class docstring). The row's
                # click (below, itemClicked → _on_item_clicked → select_provider)
                # is the only interaction left; every action moved to the
                # editor's action bar.
                widget = ProviderItemWidget(
                    provider.id, provider.name,
                    is_active=provider.is_active,
                    icon=icon,
                    sub_color=sub_color,
                    is_expired=is_expired,
                    show_actions=False,
                )
                self._item_widgets[provider.id] = widget
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
        """Track busy state in ``_busy_ids`` (interface parity — still read by
        ``is_provider_busy``/``has_busy``/``clear_busy`` elsewhere) and, when
        *provider_id* is the one currently loaded in the editor, render the
        spinner on its action bar's Enable/Disable button — the row itself has
        no busy visual of its own since Wave 7 (``show_actions=False``)."""
        if busy:
            self._busy_ids.add(provider_id)
        else:
            self._busy_ids.discard(provider_id)
        if provider_id == self._selected_id:
            self._provider_editor.set_toggle_busy(busy)

    def set_provider_epg_refreshing(self, provider_id: str, busy: bool) -> None:
        """Render the EPG-refresh spinner on the editor's action bar "Refresh
        Guide" button when *provider_id* is the one currently loaded — mirrors
        the retired row EPG pip's spinner, which never persisted across a
        ``refresh()`` rebuild either (no ``_busy_ids``-style tracking needed)."""
        if provider_id == self._selected_id:
            self._provider_editor.set_epg_busy(busy)

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
