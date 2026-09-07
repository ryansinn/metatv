"""MainWindow's one status-bar chokepoint (audit row UI-8, STATUS-1).

Before this module, 95 call sites across a dozen ``main_window_*.py`` mixins
called ``self.status_bar.showMessage(...)`` directly: 64 persistent, the rest
split across five different ad-hoc timeouts, with an error and a hint reading
identically (plain text, no cue, nowhere else to look). Every future change to
"how the app tells the user something" was a 95-site edit.

``status()`` is the one place that decides: how long a message stays up,
whether it carries a warning/error cue (colour is never the only cue — see
CLAUDE.md's theming rule — so "warn"/"error" prefix the text with a glyph from
``icons.py``), and whether it also reaches the log. No toast/notification-
manager route exists for "error" today: ``NotificationManager.show()``
(``metatv/core/notifications.py``) is a generic constructor-style API that
requires a ``title``, not a one-argument "post an error" method, so wiring it
in here would mean inventing a title out of nothing — a design decision this
slice does not make. Revisit if/when a single-purpose toast-error method
exists.
"""

from __future__ import annotations

from loguru import logger

from metatv.gui import icons as _icons

#: The three status levels ``status()`` accepts.
_LEVELS = ("info", "warn", "error")


class _StatusMixin:
    """Mixin: MainWindow's status-bar chokepoint.

    Mixed into :class:`~metatv.gui.main_window.MainWindow`; methods on every
    other mixin call ``self.status(...)`` instead of touching
    ``self.status_bar`` directly (``clearMessage()`` is the one exception —
    see ``tests/status_bar_allowlist.json`` and
    ``tests/test_status_bar_has_one_path.py``).
    """

    def status(self, text: str, *, ms: int = 4000, level: str = "info") -> None:
        """Show ``text`` in the status bar.

        Args:
            text: The message to show, unchanged — "warn"/"error" prefix a
                glyph rather than reword anything.
            ms: Timeout in milliseconds before Qt clears the message on its
                own. ``0`` is Qt's own "persistent" value — the message stays
                until something else overwrites it or ``clearMessage()``
                runs. Defaults to 4000, the most common of the five ad-hoc
                timeouts the migrated call sites used.
            level: One of ``"info"``, ``"warn"``, ``"error"``. "warn" and
                "error" prefix ``text`` with the matching glyph from
                ``icons.py`` and log the unprefixed text at the matching
                loguru level (``logger.warning``/``logger.error``); "info"
                does neither.

        Raises:
            ValueError: ``level`` is not one of ``"info"``/``"warn"``/``"error"``.
        """
        if level not in _LEVELS:
            raise ValueError(f"unknown status level: {level!r} (want one of {_LEVELS})")

        shown = text
        if level == "warn":
            shown = f"{_icons.notification_warning_icon} {text}"
            logger.warning(text)
        elif level == "error":
            shown = f"{_icons.notification_error_icon} {text}"
            logger.error(text)

        self.status_bar.showMessage(shown, ms)
