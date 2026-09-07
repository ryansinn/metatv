"""ToolView — shared scaffold for the four Tools-menu diagnostic views.

Source Analytics, Missing TMDb, Reconnect Engaged Content, and Metadata
Enrichment each independently built the same Back-button top bar, section
header, "Loading…" placeholder, and layout-clearing helper — found while
auditing centre panels for the CLAUDE.md rule that a failed background load
must render a visible error row, never ``clear(); return``. Sidebar sections
already have that in ``CollapsibleSection.show_load_error``; this is the
centre-panel twin, plus the one scaffold every "tool" view rebuilds by copy.

Subclass ``ToolView`` instead of ``QWidget`` for a new Tools-menu view.
"""
from __future__ import annotations

from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLayout, QPushButton
from PyQt6.QtCore import pyqtSignal
from loguru import logger

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.content_view import ContentView


def clear_layout(layout: QLayout) -> None:
    """Remove every widget from *layout*, recursing into nested layouts.

    Widgets are scheduled for deletion via ``deleteLater()`` (never destroyed
    synchronously mid-signal); a nested ``QLayout`` item (no widget of its
    own) is cleared recursively rather than skipped, so a panel built with
    inner ``QHBoxLayout`` rows (as the four Tools views do) is actually
    emptied instead of leaving orphaned child layouts behind.
    """
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()
            continue
        child_layout = item.layout()
        if child_layout is not None:
            clear_layout(child_layout)


class ToolView(ContentView):
    """Base class for the Tools-menu panel views.

    Provides the scaffold every one of them (Source Analytics, Missing TMDb,
    Reconnect Engaged Content, Metadata Enrichment) rebuilt independently:
    the Back-button top bar (:meth:`build_top_bar`), a section-header label
    helper (:meth:`section_header`), a "Loading…" placeholder
    (:meth:`show_loading`), and the centre-panel error row
    (:meth:`show_panel_error`) for a background read that raised.
    """

    done = pyqtSignal()

    def __init__(self, main_window) -> None:
        super().__init__(main_window.config)
        self.main_window = main_window

    def build_top_bar(self, title: str) -> QHBoxLayout:
        """Back button (emits ``done``) + *title* + stretch.

        Verbatim top bar every one of the four views built by copy.
        """
        top_bar = QHBoxLayout()
        back_btn = QPushButton(_icons.prev_icon + " Back")
        back_btn.setToolTip("Return to channel list")
        back_btn.clicked.connect(self.done.emit)
        title_label = QLabel(title)
        _theme.style(title_label, "DETAIL_TITLE")
        top_bar.addWidget(back_btn)
        top_bar.addWidget(title_label)
        top_bar.addStretch()
        return top_bar

    def section_header(self, text: str) -> QLabel:
        """A section-header label (the ``SECTION_HDR_LG`` role)."""
        label = QLabel(text)
        _theme.style(label, "SECTION_HDR_LG")
        return label

    def show_loading(self, layout: QLayout, text: str = "Loading…") -> None:
        """Clear *layout* and show a single muted loading row."""
        clear_layout(layout)
        loading = QLabel(text)
        _theme.style(loading, "SECTION_HINT")
        layout.addWidget(loading)

    def show_panel_error(self, layout: QLayout, exc_or_text: "Exception | str") -> None:
        """The centre-panel twin of ``CollapsibleSection.show_load_error``.

        Clears *layout* and renders one visible "couldn't load" row instead
        of leaving a "Loading…" placeholder that a failed background read
        will never replace (CLAUDE.md: "On the None/error branch, render a
        visible error row ... never clear(); return").
        """
        detail = str(exc_or_text)
        logger.warning("Panel load failed: {}", detail)
        clear_layout(layout)
        err = QLabel(f"{_icons.notification_warning_icon}  Couldn't load — {detail}")
        _theme.style(err, "SECTION_HINT")
        layout.addWidget(err)
