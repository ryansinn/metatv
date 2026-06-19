"""Sources sidebar section — provider list with refresh/edit/toggle actions."""

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt, pyqtSignal

from metatv.core.repositories import RepositoryFactory
from metatv.core.epg_utils import epg_status as _epg_status, to_local as _to_local
from metatv.gui import theme as _theme
from metatv.gui import icons as _icons
from metatv.gui.sidebar.base import CollapsibleSection


def _epg_tooltip(state: str, start, end) -> str:
    """Build the EPG indicator tooltip: a date range, or 'No EPG Available'."""
    if state == "none":
        return "No EPG Available"

    def _fmt(d):
        if d is None:
            return "?"
        try:
            return _to_local(d).strftime("%d %b %Y").lstrip("0")
        except Exception:
            return str(d)

    label = {
        "stale": "EPG stale",
        "soon": "EPG ending soon",
        "current": "EPG current",
    }.get(state, "EPG")
    return f"{label}: {_fmt(start)} – {_fmt(end)}  (click to refresh)"


# EPG freshness state → colour token (single source: epg_utils.epg_status).
_EPG_STATE_COLOR = {
    "none":    _theme.COLOR_FAINT,    # almost transparent — no guide
    "stale":   _theme.COLOR_ERR_2,    # softer red — feed out of date
    "soon":    _theme.COLOR_WARN,     # amber — about to run out
    "current": _theme.COLOR_OK,       # green — current & future-looking
}


class ProviderItemWidget(QWidget):
    """Custom widget for provider items with refresh, edit, analyze, and toggle buttons."""

    refreshClicked = pyqtSignal(str)      # provider_id
    editClicked = pyqtSignal(str)         # provider_id
    analyzeClicked = pyqtSignal(str)      # provider_id
    toggleClicked = pyqtSignal(str)       # provider_id
    epgRefreshClicked = pyqtSignal(str)   # provider_id — refresh EPG for this source

    def __init__(self, provider_id: str, provider_name: str, is_active: bool = True,
                 icon: str = "", sub_color: str = "", is_expired: bool = False,
                 busy: bool = False, epg_state: str = "none", epg_tooltip: str = "",
                 parent=None):
        super().__init__(parent)
        self.provider_id = provider_id
        self._is_active = is_active
        self._epg_state = epg_state
        self._epg_tooltip = epg_tooltip

        self.setAutoFillBackground(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)

        # Provider icon / emoji (optional)
        if icon:
            icon_lbl = QLabel(icon)
            icon_lbl.setFixedWidth(18)
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(icon_lbl)

        # Status dot — green=active, red=expired, grey=inactive
        if is_expired:
            dot_char = "●"
            dot_color = _theme.COLOR_ERR
        elif is_active:
            dot_char = "●"
            dot_color = _theme.COLOR_OK
        else:
            dot_char = "○"
            dot_color = _theme.COLOR_MUTED_2
        self._status_lbl = QLabel(dot_char)
        self._status_lbl.setFixedWidth(12)
        self._status_lbl.setStyleSheet(f"color: {dot_color};")
        if is_expired:
            self._status_lbl.setToolTip("Subscription expired")
        layout.addWidget(self._status_lbl)

        # EPG freshness indicator — colored by state; click to refresh EPG for this source.
        self._epg_btn = QPushButton(_icons.epg_indicator_icon)
        self._epg_btn.setFixedSize(16, 20)
        self._epg_btn.setFlat(True)
        self._epg_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._epg_btn.clicked.connect(lambda: self.epgRefreshClicked.emit(self.provider_id))
        layout.addWidget(self._epg_btn)
        self.set_epg_state(epg_state, epg_tooltip)

        # Provider name — expired gets distinct label + color, otherwise use sub_color
        display_name = f"{provider_name} (Expired)" if is_expired else provider_name
        self._name_lbl = QLabel(display_name)
        self._name_lbl.setWordWrap(False)
        self._name_lbl.setTextFormat(Qt.TextFormat.PlainText)
        if is_expired:
            self._name_lbl.setStyleSheet(f"color: {_theme.COLOR_ERR}; font-style: italic;")
        elif sub_color:
            self._name_lbl.setStyleSheet(f"color: {sub_color};")
        layout.addWidget(self._name_lbl, 1)

        _btn_style = """
            QPushButton {{
                background: rgba({r},{g},{b},0.15);
                border: 1px solid rgba({r},{g},{b},0.5);
                border-radius: 3px;
                font-size: 10px;
                color: rgb({r},{g},{b});
            }}
            QPushButton:hover {{ background: rgba({r},{g},{b},0.35); }}
        """

        # Toggle (enable/disable)
        self._toggle_btn = QPushButton("●" if is_active else "○")
        self._toggle_btn.setFixedSize(22, 20)
        self._toggle_btn.setToolTip("Enable / Disable this provider")
        self._toggle_btn.setStyleSheet(_btn_style.format(r=180, g=180, b=180))
        self._toggle_btn.clicked.connect(lambda: self.toggleClicked.emit(self.provider_id))
        layout.addWidget(self._toggle_btn)

        # Edit pencil (teal/cyan for edit action)
        edit_btn = QPushButton("✎")
        edit_btn.setFixedSize(22, 20)
        edit_btn.setToolTip("Edit provider settings")
        edit_btn.setStyleSheet(_btn_style.format(r=80, g=200, b=180))
        edit_btn.clicked.connect(lambda: self.editClicked.emit(self.provider_id))
        layout.addWidget(edit_btn)

        # Analyze (purple for analytics)
        analyze_btn = QPushButton("📊")
        analyze_btn.setFixedSize(22, 20)
        analyze_btn.setToolTip("Analyze source overlap and content")
        analyze_btn.setStyleSheet(_btn_style.format(r=200, g=100, b=255))
        analyze_btn.clicked.connect(lambda: self.analyzeClicked.emit(self.provider_id))
        layout.addWidget(analyze_btn)

        # Refresh (blue — action button)
        refresh_btn = QPushButton("↻")
        refresh_btn.setFixedSize(22, 20)
        refresh_btn.setToolTip("Refresh channels from provider")
        refresh_btn.setStyleSheet(_btn_style.format(r=68, g=136, b=255))
        refresh_btn.clicked.connect(lambda: self.refreshClicked.emit(self.provider_id))
        layout.addWidget(refresh_btn)

        # Action buttons that get disabled while a provider operation is in flight.
        self._action_btns = [self._toggle_btn, edit_btn, analyze_btn, refresh_btn]
        if busy:
            self.set_busy(True)

    def update_active(self, is_active: bool):
        self._is_active = is_active
        self._status_lbl.setText("●" if is_active else "○")
        dot_color = _theme.COLOR_OK if is_active else _theme.COLOR_MUTED_2
        self._status_lbl.setStyleSheet(f"color: {dot_color};")
        self._toggle_btn.setText("●" if is_active else "○")

    def set_busy(self, busy: bool) -> None:
        """Disable the row's action buttons and show a spinner on the toggle while a
        provider operation (enable/disable + view refresh) is in progress."""
        for btn in self._action_btns:
            btn.setEnabled(not busy)
        if busy:
            self._toggle_btn.setText(_icons.loading_icon)
            self._toggle_btn.setToolTip("Updating…")
        else:
            self._toggle_btn.setText("●" if self._is_active else "○")
            self._toggle_btn.setToolTip("Enable / Disable this provider")

    def set_epg_state(self, state: str, tooltip: str) -> None:
        """Color the EPG indicator by freshness state and set its date-range tooltip."""
        self._epg_state = state
        self._epg_tooltip = tooltip
        color = _EPG_STATE_COLOR.get(state, _theme.COLOR_FAINT)
        self._epg_btn.setEnabled(True)
        self._epg_btn.setText(_icons.epg_indicator_icon)
        self._epg_btn.setStyleSheet(
            f"QPushButton {{ color: {color}; border: none; background: transparent;"
            f" font-size: {_theme.FONT_MD}; }}"
            f" QPushButton:hover {{ color: {_theme.COLOR_TEXT_HI}; }}"
        )
        self._epg_btn.setToolTip(tooltip)

    def set_epg_refreshing(self, busy: bool) -> None:
        """Spinner on the EPG indicator while its feed is being refreshed."""
        if busy:
            self._epg_btn.setText(_icons.loading_icon)
            self._epg_btn.setEnabled(False)
            self._epg_btn.setToolTip("Refreshing EPG…")
        else:
            self.set_epg_state(self._epg_state, self._epg_tooltip)


class SourcesSection(CollapsibleSection):
    """Sources provider list section"""

    providerSelected = pyqtSignal(str)         # provider_id
    providerRefreshClicked = pyqtSignal(str)   # provider_id
    providerEditClicked = pyqtSignal(str)      # provider_id
    providerAnalyzeClicked = pyqtSignal(str)   # provider_id
    providerToggleClicked = pyqtSignal(str)    # provider_id
    providerEpgRefreshClicked = pyqtSignal(str)  # provider_id — refresh EPG for this source
    addProviderClicked = pyqtSignal()
    refreshAllClicked = pyqtSignal()

    def __init__(self, config, db, parent=None):
        self.db = db
        # provider_ids with an operation in flight (toggle + view refresh); survives the
        # tree rebuild in refresh() so the spinner/disabled state is re-applied.
        self._busy_ids: set[str] = set()
        self._item_widgets: dict[str, "ProviderItemWidget"] = {}
        super().__init__("Sources", config.provider_icon, config, parent)

    def get_section_id(self):
        return "sources"

    def create_header(self):
        """Override to add '+' button in the header instead of bottom buttons."""
        header = QWidget()
        header.setStyleSheet(_theme.HEADER_TINT)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(5, 3, 5, 3)

        self.toggle_btn = QPushButton(self.config.collapse_icon)
        self.toggle_btn.setFixedSize(20, 20)
        self.toggle_btn.clicked.connect(self.toggle_collapse)
        header_layout.addWidget(self.toggle_btn)

        self.title_label = QLabel(f"{self.config.provider_icon} <b>Sources</b>")
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()

        _btn_style = (
            "QPushButton {{ font-size: {fs}px; border: 1px solid {c};"
            " border-radius: 3px; color: {c}; background: {bg}; }}"
            "QPushButton:hover {{ background: {hbg}; }}"
        )
        refresh_all_btn = QPushButton(self.config.refresh_icon)
        refresh_all_btn.setFixedSize(22, 20)
        refresh_all_btn.setToolTip("Refresh all sources")
        refresh_all_btn.setStyleSheet(_btn_style.format(
            fs=13, c=_theme.COLOR_DIM,
            bg=_theme.OVERLAY_05, hbg=_theme.OVERLAY_15,
        ))
        refresh_all_btn.clicked.connect(self.refreshAllClicked.emit)
        header_layout.addWidget(refresh_all_btn)

        add_btn = QPushButton("+")
        add_btn.setFixedSize(22, 20)
        add_btn.setToolTip("Add Source…")
        add_btn.setStyleSheet(_btn_style.format(
            fs=13, c=_theme.COLOR_DIM,
            bg=_theme.OVERLAY_05, hbg=_theme.OVERLAY_15,
        ))
        add_btn.clicked.connect(self.addProviderClicked.emit)
        header_layout.addWidget(add_btn)

        self.main_layout.addWidget(header)

    def create_content(self):
        """Create sources tree (no bottom buttons — they moved to the header)."""
        from PyQt6.QtWidgets import QTreeWidget
        self.sources_tree = QTreeWidget()
        self.sources_tree.setHeaderHidden(True)
        self.sources_tree.itemClicked.connect(self.on_provider_clicked)
        self.content_layout.addWidget(self.sources_tree)

    def refresh(self):
        """Load providers from database."""
        self.sources_tree.clear()
        self._item_widgets = {}

        session = self.db.get_session()
        try:
            from datetime import datetime
            from metatv.gui.provider_editor import subscription_color
            repos = RepositoryFactory(session)
            providers = repos.providers.get_all()
            self.set_empty(len(providers) == 0)

            now = datetime.now()
            for provider in providers:
                from PyQt6.QtWidgets import QTreeWidgetItem
                item = QTreeWidgetItem(self.sources_tree)
                item.setText(0, "")
                item.setData(0, Qt.ItemDataRole.UserRole, provider.id)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

                # Determine if subscription has actually lapsed (date-based, not just API status).
                is_expired = bool(
                    provider.account_exp_date and provider.account_exp_date <= now
                )

                # Subscription color — only shown when not expired (expired has its own style).
                sub_color = ""
                if not is_expired and provider.account_exp_date:
                    sub_color = subscription_color(provider.account_exp_date, provider.account_created_at)

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
                widget.editClicked.connect(
                    lambda pid=provider.id: self.providerEditClicked.emit(pid)
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
                self.sources_tree.setItemWidget(item, 0, widget)
        finally:
            session.close()

    def on_provider_clicked(self, item, column):
        provider_id = item.data(0, Qt.ItemDataRole.UserRole)
        if provider_id:
            self.providerSelected.emit(provider_id)

    def update_provider_status(self, provider_id: str, status: str):
        """Legacy method — no-op; widgets now update via refresh()."""
        pass

    def is_provider_busy(self, provider_id: str) -> bool:
        return provider_id in self._busy_ids

    def set_provider_busy(self, provider_id: str, busy: bool) -> None:
        """Mark a provider's row busy/idle. Records it in `_busy_ids` (so a later
        refresh() rebuild re-applies the state) and updates the live widget in place
        for immediate feedback without a full rebuild."""
        if busy:
            self._busy_ids.add(provider_id)
        else:
            self._busy_ids.discard(provider_id)
        widget = self._item_widgets.get(provider_id)
        if widget is not None:
            widget.set_busy(busy)

    def set_provider_epg_refreshing(self, provider_id: str, busy: bool) -> None:
        """Show/clear the spinner on a provider row's EPG indicator while its feed
        is being refreshed (in place — no full rebuild needed)."""
        widget = self._item_widgets.get(provider_id)
        if widget is not None:
            widget.set_epg_refreshing(busy)

    def has_busy(self) -> bool:
        return bool(self._busy_ids)

    def clear_busy(self) -> None:
        """Clear busy/spinner state for every provider row."""
        for pid in list(self._busy_ids):
            self.set_provider_busy(pid, False)

    def clear_selection(self) -> None:
        """Deselect any active source row (used when the per-source filter is toggled off)."""
        self.sources_tree.clearSelection()
        self.sources_tree.setCurrentItem(None)
