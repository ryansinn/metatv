"""Style menu: theme + results density without digging through Settings (#279).

Owner: "why not create an item under the view menu → Themes … it would also be
worth having the Results options … Compact, Comfy, Comfy+ … should there just be
a style menu, instead? basically a way for the user to adjust some look and feel
options easily without digging through settings?"

One Style menu rather than two scattered View entries, and both groups drive the
SAME live-apply seams the Settings dialog uses — ``refresh_theme()`` and
``_apply_channel_list_density()``. That matters more than it looks: routing the
theme through ``apply_theme`` directly would skip the registered-style re-apply
and the widget repolish (#277/#278) and reproduce the half-switched rendering
those exist to fix.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from metatv.gui import deferred_config_save as _cfgsave


class _Host:
    """Minimal host binding the real menu-handler methods."""

    def __init__(self, theme_name="Midnight", density="comfy"):
        from metatv.gui.main_window import MainWindow

        self.config = MagicMock()
        self.config.theme_name = theme_name
        self.config.channel_list_density = density
        self.refresh_theme = MagicMock()
        self._apply_channel_list_density = MagicMock()
        self._set_theme_from_menu = MainWindow._set_theme_from_menu.__get__(self)
        self._set_density_from_menu = MainWindow._set_density_from_menu.__get__(self)


class TestThemeSelection:

    def test_choosing_a_theme_persists_and_applies_it(self):
        host = _Host(theme_name="Midnight")

        host._set_theme_from_menu("Daylight")

        assert host.config.theme_name == "Daylight"
        # The write settles through the deferred-save chokepoint (CFG-10);
        # flush forces it now instead of waiting out the real timer.
        host.config.save.assert_not_called()
        assert _cfgsave.flush(host) is True
        host.config.save.assert_called_once()
        host.refresh_theme.assert_called_once()

    def test_it_goes_through_refresh_theme_not_apply_theme(self):
        """refresh_theme is where the style re-apply and repolish live.

        Calling theme.apply_theme directly would switch the tokens but leave
        existing widgets painted in the old palette — the exact bug #277/#278
        fixed. Pinned because it is an easy and invisible shortcut to take.
        """
        import inspect

        from metatv.gui.main_window import MainWindow

        src = inspect.getsource(MainWindow._set_theme_from_menu)
        assert "self.refresh_theme()" in src
        assert "apply_theme(" not in src

    def test_reselecting_the_active_theme_is_a_no_op(self):
        """No pointless save or full restyle when nothing changed."""
        host = _Host(theme_name="Daylight")

        host._set_theme_from_menu("Daylight")

        host.config.save.assert_not_called()
        host.refresh_theme.assert_not_called()


class TestDensitySelection:

    @pytest.mark.parametrize("value", ["compact", "comfy", "comfy_plus"])
    def test_choosing_a_density_persists_and_applies_it(self, value):
        host = _Host(density="comfy" if value != "comfy" else "compact")

        host._set_density_from_menu(value)

        assert host.config.channel_list_density == value
        host.config.save.assert_not_called()
        assert _cfgsave.flush(host) is True
        host.config.save.assert_called_once()
        host._apply_channel_list_density.assert_called_once()

    def test_reselecting_the_active_density_is_a_no_op(self):
        host = _Host(density="comfy")

        host._set_density_from_menu("comfy")

        host.config.save.assert_not_called()
        host._apply_channel_list_density.assert_not_called()


class TestMenuContents:
    """Built against the real window so the menu can't drift from the data."""

    @pytest.fixture()
    def window(self, qapp, tmp_path):
        from PyQt6.QtWidgets import QMainWindow

        from metatv.gui.main_window import MainWindow

        host = QMainWindow()
        host.config = MagicMock()
        host.config.theme_name = "Graphite"
        host.config.channel_list_density = "comfy_plus"
        host._build_style_menu = MainWindow._build_style_menu.__get__(host)
        host._set_theme_from_menu = MagicMock()
        host._set_density_from_menu = MagicMock()
        host._set_thumbnails_from_menu = MagicMock()
        host._set_platform_style_from_menu = MagicMock()
        host._toggle_filters_from_menu = MagicMock()
        host._set_buffer_from_menu = MagicMock()
        host._build_style_menu(host.menuBar())
        return host

    @pytest.fixture(scope="module")
    def qapp(self):
        from PyQt6.QtWidgets import QApplication

        return QApplication.instance() or QApplication([])

    def _menu(self, window, title):
        for action in window.menuBar().actions():
            if action.text().replace("&", "") == title:
                return action.menu()
        raise AssertionError(f"no {title!r} menu")

    def test_style_menu_exists_with_its_groups(self, window):
        style = self._menu(window, "Style")
        entries = {a.text().replace("&", "") for a in style.actions()}
        assert {"Theme", "Results density", "Poster thumbnails",
                "Platform names"} <= entries
        # "Filter panel" moved to the Layout menu in #284: Style is what things
        # LOOK like, Layout is what is on screen, and the filter panel is one of
        # the three panels. Asserted as an absence so the two menus cannot drift
        # back into both offering it.
        assert "Filter panel" not in entries

    def test_every_palette_is_listed(self, window):
        from metatv.gui import theme as _theme

        style = self._menu(window, "Style")
        theme_menu = next(
            a.menu() for a in style.actions() if a.text().replace("&", "") == "Theme"
        )
        listed = {a.text() for a in theme_menu.actions()}
        assert listed == set(_theme.available_themes()), (
            "the menu must list exactly the available palettes — a hardcoded "
            "list silently omits a new theme"
        )

    def test_the_active_theme_is_ticked(self, window):
        """A menu that doesn't show what's active is one you have to guess at."""
        style = self._menu(window, "Style")
        theme_menu = next(
            a.menu() for a in style.actions() if a.text().replace("&", "") == "Theme"
        )
        checked = [a.text() for a in theme_menu.actions() if a.isChecked()]
        assert checked == ["Graphite"], f"expected Graphite ticked, got {checked}"

    def test_the_active_density_is_ticked(self, window):
        style = self._menu(window, "Style")
        density_menu = next(
            a.menu() for a in style.actions()
            if a.text().replace("&", "") == "Results density"
        )
        checked = [a.text().replace("&", "") for a in density_menu.actions() if a.isChecked()]
        assert checked == ["Comfy +"], f"expected Comfy + ticked, got {checked}"

    def test_each_group_is_exclusive(self, window):
        """Radio behaviour — two themes ticked at once is incoherent."""
        style = self._menu(window, "Style")
        for title in ("Theme", "Results density", "Platform names"):
            menu = next(
                a.menu() for a in style.actions()
                if a.text().replace("&", "") == title
            )
            groups = {a.actionGroup() for a in menu.actions()}
            assert len(groups) == 1 and None not in groups, (
                f"{title} actions are not in one exclusive group"
            )
            assert next(iter(groups)).isExclusive()


class TestBufferMenu:
    """Buffer is its own menu, not a Style entry (#280).

    Owner: "I think Buffer, stand-alone as a menu, might be useful." Right call,
    and the reasoning matters: Style is APPEARANCE. Buffer changes playback with
    no visual result, so folding it in would blur the line that makes Style
    predictable. It earns a menu of its own because it is what you reach for
    while a stream is stuttering — precisely when opening Settings is worst.
    """

    @pytest.fixture(scope="module")
    def qapp(self):
        from PyQt6.QtWidgets import QApplication

        return QApplication.instance() or QApplication([])

    @pytest.fixture()
    def window(self, qapp):
        from PyQt6.QtWidgets import QMainWindow

        from metatv.gui.main_window import MainWindow

        host = QMainWindow()
        host.config = MagicMock()
        host.config.buffer_profile = "large"
        host._build_buffer_menu = MainWindow._build_buffer_menu.__get__(host)
        host._set_buffer_from_menu = MagicMock()
        host._build_buffer_menu(host.menuBar())
        return host

    def _buffer_menu(self, window):
        for action in window.menuBar().actions():
            if action.text().replace("&", "") == "Buffer":
                return action.menu()
        raise AssertionError("no Buffer menu")

    def test_lists_the_same_profiles_as_settings(self, window):
        """Same options, same words — two entry points to one setting."""
        import inspect

        from metatv.gui import settings_dialog_tabs

        menu_values = {a.text().replace("&", "") for a in self._buffer_menu(window).actions()}
        src = inspect.getsource(settings_dialog_tabs)
        for label in menu_values:
            assert label in src, (
                f"menu label {label!r} does not match Settings — the two must "
                f"read as one setting, not two similar ones"
            )

    def test_the_active_profile_is_ticked(self, window):
        checked = [a.text().replace("&", "") for a in self._buffer_menu(window).actions()
                   if a.isChecked()]
        assert checked == ["Large (~30s buffer)"], f"got {checked}"

    def test_it_says_the_change_is_not_retroactive(self, window):
        """mpv flags are composed at launch, so this lands on the NEXT stream.

        Silently doing nothing to the current stream would read as a broken
        menu, so every entry has to say so.
        """
        for action in self._buffer_menu(window).actions():
            assert "next stream" in action.toolTip().lower(), (
                f"{action.text()!r} does not say when the change applies"
            )

    def test_it_does_not_restart_playback(self):
        """A menu click must never interrupt what is playing."""
        import inspect

        from metatv.gui.main_window import MainWindow

        src = inspect.getsource(MainWindow._set_buffer_from_menu)
        for destructive in ("play(", "stop(", "restart", "reload"):
            assert destructive not in src, (
                f"_set_buffer_from_menu touches {destructive!r} — changing a "
                f"buffer preference must not disturb the current stream"
            )
