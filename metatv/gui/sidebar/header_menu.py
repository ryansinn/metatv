"""A sidebar section header's right-click menu: Hide / Sidebar settings…

Split out of ``sidebar/base.py`` (pinned at its code-health baseline) rather
than grown as a method there — the menu is a small, self-contained piece with
no state of its own, which is exactly the kind of thing CLAUDE.md's "split by
isolation, not the line count" calls for.
"""

from __future__ import annotations

from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QMenu, QWidget


def show_header_menu(section, header: QWidget, pos: QPoint) -> None:
    """Build a fresh ``QMenu`` (no cache — the title can change under it).

    Two plain-text actions, no icons: "Hide {title}" and "Sidebar
    settings…". Both are pure signal emits — this function knows nothing
    about ``config.sidebar_visible_sections`` or how to reopen Settings; the
    host (``MainWindow``) owns that mutation (single chokepoint, CLAUDE.md).

    Args:
        section: The ``CollapsibleSection`` whose ``.title``,
            ``hideRequested`` and ``sidebarSettingsRequested`` this menu acts
            on.
        header: The header widget the menu is anchored to (for
            ``mapToGlobal``/parenting).
        pos: The click position, in *header*'s local coordinates — as handed
            in by ``customContextMenuRequested``.
    """
    menu = QMenu(header)
    hide_action = menu.addAction(f"Hide {section.title}")
    settings_action = menu.addAction("Sidebar settings…")
    chosen = menu.exec(header.mapToGlobal(pos))
    if chosen is hide_action:
        section.hideRequested.emit()
    elif chosen is settings_action:
        section.sidebarSettingsRequested.emit()
