"""Sources sidebar section — provider list with refresh/edit/toggle actions."""

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt, QSize, pyqtSignal

from metatv.core.epg_utils import to_local as _to_local
from metatv.gui import theme as _theme
from metatv.gui import icon_utils as _icon_utils
from metatv.gui import icons as _icons


def _epg_tooltip(state: str, start, end) -> str:
    """Build the EPG indicator tooltip: a date range, or 'No EPG Available'."""
    if state == "none":
        return "No EPG Available"

    def _fmt(d):
        if d is None:
            return "?"
        try:
            return _to_local(d).strftime("%d %b %Y").lstrip("0")
        except (TypeError, ValueError, OSError, OverflowError):
            return str(d)  # silent: unformattable date still reads

    label = {
        "stale": "EPG stale",
        "soon": "EPG ending soon",
        "current": "EPG current",
    }.get(state, "EPG")
    return f"{label}: {_fmt(start)} – {_fmt(end)}  (click to refresh)"


# EPG freshness state → colour token (single source: epg_utils.epg_status).
def _epg_state_color() -> dict[str, str]:
    return {
        "none":    _theme.COLOR_FAINT,    # almost transparent — no guide
        "stale":   _theme.COLOR_ERR_2,    # softer red — feed out of date
        "soon":    _theme.COLOR_WARN,     # amber — about to run out
        "current": _theme.COLOR_OK,       # green — current & future-looking
    }


class ProviderItemWidget(QWidget):
    """Custom widget for provider items.

    ``show_actions=True`` (default) renders the full row: refresh / edit /
    analyze / toggle buttons + the EPG freshness pip — kept for tests
    exercising that row shape (the sidebar ``SourcesSection`` that used it in
    production was deleted as dead code, audit slice 4, 2026-09-07).

    ``show_actions=False`` renders a minimal row — icon, status dot, provider
    name only — used by :class:`~metatv.gui.sources_manager_view.SourcesManagerView`'s
    left column (Wave 7): those five per-row icon buttons were truncating the
    provider name in the narrow left column, so they moved into the detail
    pane's action bar (``ProviderEditorView._build_action_bar``) instead of
    being rebuilt as a parallel widget — one shared row class, one flag.
    """

    refreshClicked = pyqtSignal(str)      # provider_id
    editClicked = pyqtSignal(str)         # provider_id
    analyzeClicked = pyqtSignal(str)      # provider_id
    toggleClicked = pyqtSignal(str)       # provider_id
    epgRefreshClicked = pyqtSignal(str)   # provider_id — refresh EPG for this source

    def __init__(self, provider_id: str, provider_name: str, is_active: bool = True,
                 icon: str = "", sub_color: str = "", is_expired: bool = False,
                 busy: bool = False, epg_state: str = "none", epg_tooltip: str = "",
                 show_actions: bool = True, parent=None):
        super().__init__(parent)
        self.provider_id = provider_id
        self._is_active = is_active
        self._epg_state = epg_state
        self._epg_tooltip = epg_tooltip
        self._show_actions = show_actions
        self._epg_btn = None
        self._toggle_btn = None
        self._action_btns: list = []

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
            dot_char = _icons.status_dot_icon
            dot_color = _theme.COLOR_ERR
        elif is_active:
            dot_char = _icons.status_dot_icon
            dot_color = _theme.COLOR_OK
        else:
            dot_char = _icons.inactive_dot_icon
            dot_color = _theme.COLOR_MUTED_2
        self._status_lbl = QLabel(dot_char)
        self._status_lbl.setFixedWidth(12)
        self._status_lbl.setStyleSheet(f"color: {dot_color};")
        if is_expired:
            self._status_lbl.setToolTip("Subscription expired")
        layout.addWidget(self._status_lbl)

        if show_actions:
            # EPG freshness indicator — colored by state; click to refresh EPG for this source.
            self._epg_btn = QPushButton()
            self._epg_btn.setFixedSize(16, 20)
            self._epg_btn.setFlat(True)
            self._epg_btn.setIconSize(QSize(13, 13))
            self._epg_btn.clicked.connect(lambda: self.epgRefreshClicked.emit(self.provider_id))
            layout.addWidget(self._epg_btn)
            self.set_epg_state(epg_state, epg_tooltip)

        # Provider name — expired gets distinct label + color, otherwise use sub_color
        display_name = f"{provider_name} (Expired)" if is_expired else provider_name
        self._name_lbl = QLabel(display_name)
        self._name_lbl.setWordWrap(False)
        self._name_lbl.setTextFormat(Qt.TextFormat.PlainText)
        if is_expired:
            _theme.style_fn(self._name_lbl, lambda: f"color: {_theme.COLOR_ERR}; font-style: italic;")
        elif sub_color:
            self._name_lbl.setStyleSheet(f"color: {sub_color};")
        layout.addWidget(self._name_lbl, 1)

        if not show_actions:
            return

        # The glyph is COLOR_TEXT_HI, not the action's own rgb(r,g,b): that hue
        # at full saturation is the tint's SOURCE colour, and as icon-on-tint
        # text it fails the 4.5:1 floor outright in Daylight (as low as
        # 1.54:1) and marginally in the dark palettes. CLAUDE.md's "text on a
        # solid fill" rule treats a translucent tint OF the app surface as a
        # different case from a solid fill: use the surface's own ramp
        # (COLOR_TEXT_HI), not on_fill(). The tint itself still carries the
        # per-action hue via background/border.
        _btn_style = (
            "QPushButton {{\n"
            "    background: rgba({r},{g},{b},0.15);\n"
            "    border: 1px solid rgba({r},{g},{b},0.5);\n"
            "    border-radius: 3px;\n"
            "    font-size: " + _theme.FONT_SM + ";\n"
            "    color: " + _theme.COLOR_TEXT_HI + ";\n"
            "}}\n"
            "QPushButton:hover {{ background: rgba({r},{g},{b},0.35); }}"
        )

        # Toggle (enable/disable)
        self._toggle_btn = QPushButton()
        self._toggle_btn.setFixedSize(22, 20)
        self._toggle_btn.setToolTip("Enable / Disable this source")
        self._toggle_btn.setStyleSheet(_btn_style.format(r=180, g=180, b=180))
        _icon_utils.set_button_icon(
            self._toggle_btn, "status_dot" if is_active else "inactive_dot",
            color=_theme.COLOR_TEXT_HI,
        )
        self._toggle_btn.setIconSize(QSize(13, 13))
        self._toggle_btn.clicked.connect(lambda: self.toggleClicked.emit(self.provider_id))
        layout.addWidget(self._toggle_btn)

        # Edit pencil (teal/cyan for edit action)
        edit_btn = QPushButton()
        edit_btn.setFixedSize(22, 20)
        edit_btn.setToolTip("Edit source settings")
        edit_btn.setStyleSheet(_btn_style.format(r=80, g=200, b=180))
        _icon_utils.set_button_icon(edit_btn, "edit", color=_theme.COLOR_TEXT_HI)
        edit_btn.setIconSize(QSize(13, 13))
        edit_btn.clicked.connect(lambda: self.editClicked.emit(self.provider_id))
        layout.addWidget(edit_btn)

        # Analyze (purple for analytics)
        analyze_btn = QPushButton()
        analyze_btn.setFixedSize(22, 20)
        analyze_btn.setToolTip("Analyze source overlap and content")
        analyze_btn.setStyleSheet(_btn_style.format(r=200, g=100, b=255))
        _icon_utils.set_button_icon(analyze_btn, "analyze", color=_theme.COLOR_TEXT_HI)
        analyze_btn.setIconSize(QSize(13, 13))
        analyze_btn.clicked.connect(lambda: self.analyzeClicked.emit(self.provider_id))
        layout.addWidget(analyze_btn)

        # Refresh (blue — action button)
        refresh_btn = QPushButton()
        refresh_btn.setFixedSize(22, 20)
        refresh_btn.setToolTip("Refresh channels from source")
        refresh_btn.setStyleSheet(_btn_style.format(r=68, g=136, b=255))
        _icon_utils.set_button_icon(refresh_btn, "refresh", color=_theme.COLOR_TEXT_HI)
        refresh_btn.setIconSize(QSize(13, 13))
        refresh_btn.clicked.connect(lambda: self.refreshClicked.emit(self.provider_id))
        layout.addWidget(refresh_btn)

        # Action buttons that get disabled while a provider operation is in flight.
        self._action_btns = [self._toggle_btn, edit_btn, analyze_btn, refresh_btn]
        if busy:
            self.set_busy(True)

    def update_active(self, is_active: bool):
        self._is_active = is_active
        self._status_lbl.setText(_icons.status_dot_icon if is_active else _icons.inactive_dot_icon)
        dot_color = _theme.COLOR_OK if is_active else _theme.COLOR_MUTED_2
        self._status_lbl.setStyleSheet(f"color: {dot_color};")
        if self._toggle_btn is not None:
            _icon_utils.set_button_icon(
                self._toggle_btn, "status_dot" if is_active else "inactive_dot",
                color=_theme.COLOR_TEXT_HI,
            )

    def set_busy(self, busy: bool) -> None:
        """Disable the row's action buttons and show a spinner on the toggle while a
        provider operation (enable/disable + view refresh) is in progress.

        No-ops when ``show_actions=False`` — the row has no action buttons to
        update; the equivalent visual now lives on the detail pane's action bar
        (``ProviderEditorView.set_toggle_busy``)."""
        if self._toggle_btn is None:
            return
        for btn in self._action_btns:
            btn.setEnabled(not busy)
        if busy:
            _icon_utils.set_button_icon(self._toggle_btn, "loading", color=_theme.COLOR_TEXT_HI)
            self._toggle_btn.setToolTip("Updating…")
        else:
            _icon_utils.set_button_icon(
                self._toggle_btn, "status_dot" if self._is_active else "inactive_dot",
                color=_theme.COLOR_TEXT_HI,
            )
            self._toggle_btn.setToolTip("Enable / Disable this source")

    def set_epg_state(self, state: str, tooltip: str) -> None:
        """Color the EPG indicator by freshness state and set its date-range tooltip.

        No-ops when ``show_actions=False`` — there is no EPG pip on a stripped row."""
        self._epg_state = state
        self._epg_tooltip = tooltip
        if self._epg_btn is None:
            return
        color = _epg_state_color().get(state, _theme.COLOR_FAINT)
        self._epg_btn.setEnabled(True)
        _icon_utils.set_button_icon(self._epg_btn, "epg_indicator", color=color)
        self._epg_btn.setStyleSheet(
            "QPushButton { border: none; background: transparent; }"
        )
        self._epg_btn.setToolTip(tooltip)

    def set_epg_refreshing(self, busy: bool) -> None:
        """Spinner on the EPG indicator while its feed is being refreshed.

        No-ops when ``show_actions=False``."""
        if self._epg_btn is None:
            return
        if busy:
            _icon_utils.set_button_icon(self._epg_btn, "loading", color=_theme.COLOR_FAINT)
            self._epg_btn.setEnabled(False)
            self._epg_btn.setToolTip("Refreshing EPG…")
        else:
            self.set_epg_state(self._epg_state, self._epg_tooltip)
