"""The application header — brand, search, view switcher, global actions.

One row across the top of the window::

    MetaTV │ ⌕ search │ [Search][EPG][Recommended][Discover][Recipe] │ [Split][Tools][Exclusions]

Decision Q2/R7 chose **Option A — divided segments in the HEADER**, which frees
the bottom bar entirely. What shipped before this was Option A's *control* in
Option C's *location*: a segmented track pinned to the bottom edge, roughly
950px from the content it switches. The spec lived only in an artifact and a
lossy memory note, and nothing in the repository mentioned a header at all —
see ``docs/V3_INTERFACE_SPEC.md`` §4.

Its own module because ``main_window.py`` is over 3000 lines on a shrink-only
ratchet and this is a cohesive piece of chrome, mixed in the same way
``_NavMixin`` and ``_ChannelListMixin`` already are.

Settings is deliberately absent: it appears once, at the foot of the sidebar,
where the hand already goes (R6). An early mockup had it in both places.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal as _pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget

from metatv.gui import cursor_affordance
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.filter_bar import FilterChip, ToggleChip


# ── Header styling ──────────────────────────────────────────────────────────
# Built here rather than as theme role constants because all three are used by
# this module alone, and theme.py is over 1000 lines on a shrink-only ratchet.
# theme.style_fn registers each builder, so a palette switch re-invokes it —
# which a plain setStyleSheet would not: Qt caches the RENDERED string.


def _header_sheet() -> str:
    return (f"#appHeader {{ background: {_theme.COLOR_BG_BAR};"
            f" border-bottom: 1px solid {_theme.COLOR_LINE}; }}")


def _brand_sheet() -> str:
    """The wordmark. Quiet, but it still has to read as the app's name.

    600 was too light to carry at this size — owner: "MetaTV isn't bold
    enough". 700 is the weight Inter actually ships a bold face for, so 600 was
    also being synthesised on platforms without a semibold, which is exactly
    where it looked weakest.
    """
    return (f"color: {_theme.COLOR_TEXT_HI}; font-size: {_theme.FONT_2XL};"
            f" font-weight: 700; padding: 0 {_theme.SPACE_XS};")


def _search_sheet() -> str:
    """The primary way into 491,624 titles, so it reads as a surface rather
    than a form field."""
    return (f"QLineEdit {{ background: {_theme.COLOR_BG_DEEP};"
            f" color: {_theme.COLOR_TEXT_HI};"
            f" border: 1px solid {_theme.COLOR_BORDER};"
            f" border-radius: {_theme.RADIUS_MD};"
            f" padding: 5px {_theme.SPACE_SM}; font-size: {_theme.FONT_MD}; }}"
            f"QLineEdit:focus {{ border-color: {_theme.COLOR_ACCENT}; }}")


#: The view switcher, in display order: (attribute, label, vector role,
#: tooltip, handler NAME on the host).
#:
#: Module-level and iterated rather than written out inside
#: ``_create_nav_group``, because ``main_window_nav._deactivate_view_chips``
#: ALSO needs the list — it had its own copy, and a chip missing from that copy
#: stays lit while another view is showing. The handler is named rather than
#: bound so this can be read without a live host (the guard test does exactly
#: that).
NAV_CHIP_SPECS: tuple[tuple[str, str, str, str, str], ...] = (
    ("search_chip", "Search", "search", "Channel list and search",
     "on_search_view_toggle"),
    ("epg_chip", "EPG", "epg", "EPG — programme guide, watchlist, on-now",
     "on_special_view_toggle"),
    ("prefs_chip", "Recommended", "recommended",
     "Personalised recommendations", "on_preferences_view_toggle"),
    ("discover_chip", "Discover", "discover",
     "Browse by genre, decade, actor, director", "on_discover_view_toggle"),
    ("recipe_chip", "Recipe", "recipe",
     "Build a recipe from facets — genre, language, region, decade…",
     "on_recipe_view_toggle"),
    ("sports_chip", "Sports", "sports",
     "Sports channels by sport, league and team", "on_sports_view_toggle"),
)


class _ClickableNavLabel(QLabel):
    """A QLabel variant that emits ``clicked`` on left mouse-press.

    Used for the playback-health readout in the bottom nav bar so the user
    can click to cycle between open player windows.  Does NOT replicate the
    clipboard behaviour of ``details_sections._ClickableLabel`` — it is purely
    a click-event bridge.
    """

    clicked = _pyqtSignal()

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        cursor_affordance.set_clickable(self)

    # Qt and QMouseEvent are imported at module top, not deferred: the button
    # test below runs at CLICK time, so a missing name is a live NameError and
    # not the harmless kind `from __future__ import annotations` absorbs in the
    # signature. It was missing until ruff's F821 found it.
    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class _AppHeaderMixin:
    """Builds and maintains the application header.

    Mixed into ``MainWindow``, which supplies the view-toggle slots, the
    config, and the widgets the header hands work to.
    """

    def _create_view_switcher(self) -> QWidget:
        """The five primary views as ONE segmented track, not five loose pills.

        Five pills separated by 30px of nothing gave the views no grouping and
        no edges: they read as loose buttons, and the active one was a small
        filled lozenge rather than an obviously-current tab. As a track they
        share one outline, one hairline per boundary, and the active view fills
        its whole cell.
        """
        nav_group = self._nav_track = QWidget()
        nav_group.setObjectName("navTrack")
        _theme.style_fn(nav_group, lambda: (
            f"#navTrack {{ background: {_theme.COLOR_BG_CARD};"
            f" border: 1px solid {_theme.COLOR_BORDER};"
            f" border-radius: {ToggleChip.SEGMENT_RADIUS + 1}px; }}"
        ))
        nav_layout = QHBoxLayout(nav_group)
        # Zero margins and zero spacing are load-bearing: any gap here would
        # show the track's fill between cells and break the shared-edge look.
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(0)

        specs = [
            (attr, label, role, tip, getattr(self, slot_name))
            for attr, label, role, tip, slot_name in NAV_CHIP_SPECS
        ]
        for i, (attr, label, role, tip, slot) in enumerate(specs):
            segment = ("first" if i == 0
                       else "last" if i == len(specs) - 1
                       else "middle")
            chip = ToggleChip(label, enabled=(i == 0), vector_role=role,
                              segment=segment)
            chip.setToolTip(tip)
            chip.clicked.connect(slot)
            setattr(self, attr, chip)
            nav_layout.addWidget(chip)
        return nav_group

    def _create_header(self) -> QWidget:
        """The application header — brand, search, view switcher, global actions.

        Replaces the bottom pill bar, which sat roughly 950px from the content
        it switched. Decision Q2/R7 chose **Option A**: divided segments in the
        HEADER. What previously shipped was Option A's control in the bottom
        bar — Option C's location — so the switcher looked right and was in the
        wrong place (docs/V3_INTERFACE_SPEC.md §4).

        Left to right: wordmark · search · switcher · Split / Tools /
        Exclusions. Settings is deliberately NOT here — it lives once, at the
        foot of the sidebar, where the hand already goes (R6).
        """
        header = self._app_header = QWidget()
        header.setObjectName("appHeader")
        _theme.style_fn(header, _header_sheet)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(10)

        brand = self._brand_label = QLabel("MetaTV")
        _theme.style_fn(brand, _brand_sheet)
        brand.setToolTip("MetaTV")
        layout.addWidget(brand)

        # Search moves here from the content area's controls row. It keeps its
        # existing behaviour (it filters the channel list) and its existing
        # signal; only its home and its placeholder change. Visibility still
        # follows the Search view — see ``_sync_header_search_visibility``.
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search titles — name, category…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMinimumWidth(240)
        self.search_input.setMaximumWidth(460)
        _theme.style_fn(self.search_input, _search_sheet)
        self.search_input.textChanged.connect(self._on_search_text_changed)
        self.search_input.returnPressed.connect(self._on_search_submitted)
        layout.addWidget(self.search_input, 1)

        layout.addWidget(self._create_view_switcher())
        layout.addStretch(1)

        # Split-streams toggle — one player window per source when ON.
        self._split_toggle_btn = QPushButton(f"{_icons.split_icon} Split")
        self._split_toggle_btn.setCheckable(True)
        self._split_toggle_btn.setChecked(
            getattr(self.config, "split_streams_by_source", False)
        )
        _theme.style(self._split_toggle_btn, "NAV_TOGGLE_BTN")
        self._split_toggle_btn.setToolTip(
            "Split streams — keep one player window per source.\n"
            "OFF: every channel reuses one player window."
        )
        self._split_toggle_btn.toggled.connect(self.on_split_toggle_clicked)
        layout.addWidget(self._split_toggle_btn)

        # Playback-health readout — hidden until there is something to say.
        self._playback_health_label = _ClickableNavLabel("")
        self._playback_health_label.setToolTip(
            "Playback health — click for the full readout"
        )
        _theme.style(self._playback_health_label, "NAV_HEALTH")
        self._playback_health_label.hide()
        self._playback_health_label.clicked.connect(self._on_health_readout_clicked)
        layout.addWidget(self._playback_health_label)

        # Tools — Diagnose lived on its own button in the bottom bar, which put
        # a niche action permanently on screen next to the primary navigation.
        # It is one entry in a menu now (R5).
        self._tools_btn = QPushButton(f"{_icons.tools_icon} Tools")
        _theme.style(self._tools_btn, "NAV_TOGGLE_BTN")
        self._tools_btn.setToolTip("Diagnostics and maintenance tools")
        self._tools_btn.clicked.connect(self._show_tools_menu)
        layout.addWidget(self._tools_btn)

        self._filter_chip = FilterChip("Exclusions")
        self._filter_chip.toggled_changed.connect(self._on_filter_toggle)
        self._filter_chip.open_dialog_requested.connect(self._open_global_filter_dialog)
        layout.addWidget(self._filter_chip)

        QTimer.singleShot(0, self._update_filter_btn_state)
        return header

    def _show_tools_menu(self) -> None:
        """Pop the menu bar's own Tools menu under the header button.

        Reuses the QMenu the menu bar already owns rather than rebuilding its
        entries — two lists of tools would drift apart the first time one grew.
        """
        menu = getattr(self, "_tools_menu", None)
        if menu is None:
            return
        button = self._tools_btn
        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))

    def _sync_header_search_visibility(self, visible: bool) -> None:
        """No-op on the box's visibility: the header search is ALWAYS present.

        It used to hide on EPG, Recommended, Discover and Recipe, on the
        reasoning that it filters the channel list and so means nothing
        elsewhere. Two problems with that, and the second is the reason it
        changed:

        * Removing a 240-460px widget from a horizontal layout re-flows
          everything to its right, so the view switcher JUMPED sideways every
          time you left or returned to Search — the control you use to change
          views moved as a consequence of changing views.
        * "Means nothing elsewhere" stopped being true. Typing here and
          pressing Enter now SWITCHES to Search and runs the query (see
          ``_on_search_submitted``), which makes the box a way INTO the search
          view rather than a filter that only works once you are already in it.

        The parameter is kept so the three nav call sites need no edit and the
        signature stays honest about what they are asking for; the enabled
        state still follows it, so the box reads as inert where it does not
        filter, without moving anything.
        """
        # ``self.__dict__.get``, never ``hasattr``: PyQt raises RuntimeError —
        # not AttributeError — for attribute access on a ``__new__``'d
        # QObject, and hasattr does not absorb it. Several nav tests drive this
        # path on exactly such a skeleton.
        search = self.__dict__.get("search_input")
        if search is not None:
            search.setVisible(True)
            search.setPlaceholderText(
                "Search titles — name, category…" if visible
                else "Search titles — press Enter to search"
            )
