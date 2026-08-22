"""The Style menu — theme, row density, poster thumbnails, platform names.

Everything that answers "what does the results list LOOK like": the menu that
builds those choices, the handlers that apply one, and the sync that re-reads
the ticks back off config.

They belong together because of a bug that needed all three to see. The menu
checked its actions once at construction and never again, so a density set in
Settings left the menu asserting the old value — and then picking the value
Settings had actually set hit the "already that" early-return below and did
nothing, which reads as a dead menu. The menu is a VIEW of config; the sync is
what keeps it one.

Split out of ``main_window.py`` (the largest GUI file, frozen by the
code-health ratchet) rather than growing it further.
"""
from __future__ import annotations

from PyQt6.QtGui import QAction, QActionGroup

from metatv.gui import theme as _t


class _StyleMenuMixin:
    """Style-menu construction, its handlers, and the config→ticks sync."""

    def _build_style_menu(self, menubar) -> None:
        """Build the Style menu: theme and results density, both live.

        Every entry is checkable and exclusive within its group, and reflects
        the CURRENT config on open — a menu that doesn't show what is active is
        a menu you have to guess at.

        Args:
            menubar: The window's ``QMenuBar``.
        """
        style_menu = menubar.addMenu("&Style")

        theme_menu = style_menu.addMenu("&Theme")
        self._theme_action_group = QActionGroup(self)
        self._theme_action_group.setExclusive(True)
        current_theme = getattr(self.config, "theme_name", _t.current_theme())
        for name in _t.available_themes():
            action = QAction(name, self, checkable=True)
            action.setData(name)
            action.setChecked(name == current_theme)
            action.triggered.connect(lambda _c, n=name: self._set_theme_from_menu(n))
            self._theme_action_group.addAction(action)
            theme_menu.addAction(action)

        density_menu = style_menu.addMenu("&Results density")
        self._density_action_group = QActionGroup(self)
        self._density_action_group.setExclusive(True)
        current_density = getattr(self.config, "channel_list_density", "comfy")
        # (config value, label) — labels match Settings → Interface so the two
        # surfaces read the same.
        for value, label in (
            ("compact", "&Compact"),
            ("comfy", "Com&fy"),
            ("comfy_plus", "Comfy &+"),
        ):
            action = QAction(label, self, checkable=True)
            action.setData(value)
            action.setChecked(value == current_density)
            action.triggered.connect(lambda _c, v=value: self._set_density_from_menu(v))
            self._density_action_group.addAction(action)
            density_menu.addAction(action)

        style_menu.addSeparator()

        # Poster thumbnails — a pure appearance toggle, and the one most worth
        # reaching quickly (posters are the biggest visual change in the list).
        self._thumbs_action = QAction("Poster &thumbnails", self, checkable=True)
        self._thumbs_action.setChecked(
            bool(getattr(self.config, "channel_list_thumbnails", True))
        )
        self._thumbs_action.toggled.connect(self._set_thumbnails_from_menu)
        style_menu.addAction(self._thumbs_action)

        # Platform names — "Netflix" vs "NF" on the row chip.
        platform_menu = style_menu.addMenu("&Platform names")
        self._platform_action_group = QActionGroup(self)
        self._platform_action_group.setExclusive(True)
        current_platform = getattr(self.config, "platform_name_style", "auto")
        for value, label in (
            ("auto", "&Auto"),
            ("full", "&Full name"),
            ("short", "&Short code"),
        ):
            action = QAction(label, self, checkable=True)
            action.setData(value)
            action.setChecked(value == current_platform)
            action.triggered.connect(
                lambda _c, v=value: self._set_platform_style_from_menu(v)
            )
            self._platform_action_group.addAction(action)
            platform_menu.addAction(action)


    def _set_thumbnails_from_menu(self, enabled: bool) -> None:
        """Toggle poster thumbnails from the Style menu.

        Args:
            enabled: True to show posters in the results list.
        """
        if bool(getattr(self.config, "channel_list_thumbnails", True)) == enabled:
            return
        self.config.channel_list_thumbnails = enabled
        self.config.save()
        self._apply_channel_list_density()

    def _set_platform_style_from_menu(self, value: str) -> None:
        """Set how platform chips are labelled, from the Style menu.

        Args:
            value: One of ``"auto"``/``"full"``/``"short"``.
        """
        if getattr(self.config, "platform_name_style", None) == value:
            return
        self.config.platform_name_style = value
        self.config.save()
        self._apply_channel_list_density()

    def _set_density_from_menu(self, value: str) -> None:
        """Apply and persist a row density chosen from the Style menu.

        Args:
            value: One of ``"compact"``/``"comfy"``/``"comfy_plus"``.
        """
        if getattr(self.config, "channel_list_density", None) == value:
            return
        self.config.channel_list_density = value
        self.config.save()
        self._apply_channel_list_density()

    def _sync_style_menu_state(self) -> None:
        """Re-check every Style-menu entry from config.

        The menu is a VIEW of config, so it is re-read wholesale rather than
        patched per-change: that way no caller has to remember which ticks its
        change affects. Signals are blocked while setting, so syncing the view
        never re-enters the handlers that change the model.

        Lives on the density seam because that is the path every appearance
        change already takes (menu handlers and ``settings_applied`` both end
        there), and it runs after the menus exist — ``_build_style_menu`` is
        part of ``setup_ui``, and nothing applies a density before that.
        """
        groups = (
            (self._theme_action_group, getattr(self.config, "theme_name", None)),
            (self._density_action_group,
             getattr(self.config, "channel_list_density", "comfy")),
            (self._platform_action_group,
             getattr(self.config, "platform_name_style", "auto")),
        )
        for group, current in groups:
            for action in group.actions():
                # setData is set for every action in these groups at build
                # time; no text() fallback, because matching a menu LABEL
                # ("&Compact") against a config value ("compact") never would.
                action.blockSignals(True)
                action.setChecked(action.data() == current)
                action.blockSignals(False)
        self._thumbs_action.blockSignals(True)
        self._thumbs_action.setChecked(
            bool(getattr(self.config, "channel_list_thumbnails", True))
        )
        self._thumbs_action.blockSignals(False)

    def _sync_split_toggle(self) -> None:
        """Re-check the nav-bar Split toggle from config (Playback tab mirror)."""
        self._split_toggle_btn.blockSignals(True)
        self._split_toggle_btn.setChecked(
            getattr(self.config, "split_streams_by_source", False)
        )
        self._split_toggle_btn.blockSignals(False)

