"""The menu bar, optionally hidden until you press Alt.

Hiding the menu bar behind Alt was built once and reversed by the owner:
*"leave the menu visible, because otherwise it's fucked on other platforms."*
That reversal was right, and this is not an attempt to relitigate it — the
behaviour is **off by default and only reachable by asking for it**, and it is
refused outright on the one platform where it is nonsense.

Three things make it safe to offer:

**macOS is excluded, not merely discouraged.** There the menu bar is the system
bar at the top of the screen, not part of the window; Qt puts it there and the
window has no menu bar to hide. Alt is not a menu-activation convention there
either. So on macOS the setting is inert whatever config says — the guard is in
:func:`auto_hide_supported`, not in the settings UI, because a UI-only guard is
one someone can route around later.

**What it costs is real and worth stating.** The menu bar holds File, View,
Tools, Help, Layout, Style and Buffer. The header surfaces only **Tools**, so
hiding the bar hides the Layout panel toggles, the Style menu and the Buffer
menu behind an Alt press. That is a fair trade for someone who wants the chrome
gone, and a bad surprise for anyone who does not — hence opt-in.

**Alt toggles rather than "reveals while held."** Hold-to-reveal reads well and
behaves badly: the reveal ends the moment you release, which is the moment you
reach for the menu. Toggle is what Windows Explorer and Firefox do, and it is
the behaviour that survives a user who presses Alt and then thinks.
"""

from __future__ import annotations

import sys

from loguru import logger
from PyQt6.QtCore import Qt

from metatv.gui import deferred_config_save as _cfgsave


def auto_hide_supported() -> bool:
    """Whether this platform can meaningfully hide its menu bar.

    False on macOS: the menu bar lives in the system bar, so there is nothing
    in the window to hide and Alt means nothing. Checked here rather than at
    the call sites so a future caller cannot forget it.
    """
    return sys.platform != "darwin"


class _MenuBarRevealMixin:
    """Alt-to-toggle for the menu bar, when the user has asked for it."""

    def menu_bar_auto_hide(self) -> bool:
        """The effective setting — config AND platform, never config alone."""
        return bool(
            getattr(self.config, "menu_bar_auto_hide", False)
            and auto_hide_supported()
        )

    def apply_menu_bar_auto_hide(self) -> None:
        """Put the menu bar in the state the setting calls for.

        The single seam: startup, a Settings change and the Alt handler all
        come through here or through :meth:`toggle_menu_bar`, so the bar's
        visibility has one owner.
        """
        bar = self.menuBar()
        if bar is None:
            return
        if self.menu_bar_auto_hide():
            bar.setVisible(False)
        else:
            # Turning the setting OFF must restore it, including when it is
            # currently hidden mid-session. Never leave a user with no menu.
            bar.setVisible(True)

    def set_menu_bar_auto_hide(self, auto_hide: bool) -> None:
        """The one writer. Settings and the Tools toggle both come here.

        Two surfaces set this, and they must not drift: Settings, and a
        checkable entry in the **Tools** menu. Tools is the one that matters —
        the header's Tools button opens that same menu, so it is reachable
        with the menu bar hidden, which is exactly when you need the way back.
        A setting whose only off-switch is behind the thing it switched off is
        a trap.
        """
        self.config.menu_bar_auto_hide = bool(auto_hide) and auto_hide_supported()
        _cfgsave.save_soon(self)
        self.apply_menu_bar_auto_hide()
        self.sync_menu_bar_actions()
        logger.info(f"Menu bar auto-hide → {self.config.menu_bar_auto_hide}")

    def sync_menu_bar_actions(self) -> None:
        """Tick every surface from the setting, never from a cached flag."""
        action = self.__dict__.get("_menu_always_visible_action")
        if action is not None:
            action.blockSignals(True)
            action.setChecked(not self.menu_bar_auto_hide())
            action.blockSignals(False)

    def toggle_menu_bar(self) -> None:
        """Alt: show the hidden bar, or hide the shown one."""
        if not self.menu_bar_auto_hide():
            return
        bar = self.menuBar()
        if bar is None:
            return
        showing = not bar.isVisible()
        bar.setVisible(showing)
        if showing:
            # Give it focus so the very next keypress works as a mnemonic —
            # Alt then F opens File, which is the whole point of pressing Alt.
            bar.setFocus(Qt.FocusReason.ShortcutFocusReason)

    # ── Key handling ─────────────────────────────────────────────────────────

    def keyPressEvent(self, event):  # noqa: N802 (Qt naming)
        # Record that Alt went down ALONE. Alt+F is a mnemonic and must not
        # also toggle the bar, so the release handler checks this flag.
        if event.key() == Qt.Key.Key_Alt:
            self._alt_pressed_alone = True
        else:
            self._alt_pressed_alone = False
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):  # noqa: N802 (Qt naming)
        if (event.key() == Qt.Key.Key_Alt
                and self.__dict__.get("_alt_pressed_alone")
                and self.menu_bar_auto_hide()):
            self._alt_pressed_alone = False
            self.toggle_menu_bar()
            event.accept()
            return
        if (event.key() == Qt.Key.Key_Escape
                and self.menu_bar_auto_hide()
                and self.menuBar() is not None
                and self.menuBar().isVisible()):
            # Escape is the way out for someone who revealed it by accident.
            self.menuBar().setVisible(False)
            event.accept()
            return
        super().keyReleaseEvent(event)
