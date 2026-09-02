"""The one way to present a list of channels.

**Why this file exists.** The virtualized list — ``ChannelListModel`` +
``ChannelRowDelegate`` + ``ChannelListView`` + the viewport thumbnail hydrator
— was built in the app's first months precisely to stop the render stalls that
came from making a real ``QWidget`` per row. It works: the main channel list
paints 785,163 channels without a stutter, because a delegate paints only the
rows on screen and the model materializes nothing.

But it was never a *component*. It was ~50 lines of hand-wiring inside
``main_window.setup_ui()``, so nothing in the tree said "this is how you render
results". Meanwhile the sidebar's ``build_chip_row`` IS one call and obviously
reusable — and it is the WRONG tool here, because it builds a live widget per
row. Bounded sidebar sections (tens of rows) and dialogs are exactly what it is
for.

So the discoverable path was the slow one and the correct path was invisible
unless you already knew it existed. The Sports view (#594) reached for
``build_chip_row`` and froze the app for minutes on 9,769 rows — measured at
0.39 ms/row offscreen, which is a floor: on a real display, competing with a
migration for CPU and I/O, it was minutes. That is not a mistake anyone should
be able to make twice, so the wiring is packaged here and
``tests/test_results_list_is_virtualized.py`` fails the suite if a content view
grows a per-row widget again.

Usage — the whole API is three lines::

    self.results = ChannelResultsList(config=self.config, image_cache=cache)
    layout.addWidget(self.results)
    self.results.set_rows(dtos)          # list[ChannelListDTO]

Anything that needs paging, grouping, or favourite-toggling still talks to
``self.results.model`` directly; this class deliberately does not re-wrap the
model's full surface, only the wiring that was easy to get wrong.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from loguru import logger
from PyQt6.QtCore import QModelIndex, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QAbstractItemView, QLabel, QVBoxLayout, QWidget

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.channel_list_delegate import ChannelRowDelegate
from metatv.gui.channel_list_model import ChannelListModel
from metatv.gui.channel_list_view import ChannelListView


class ChannelResultsList(QWidget):
    """A virtualized channel list: model + delegate + view, wired correctly.

    Signals carry the channel id (a ``str``), never a widget or a row index —
    a row index is meaningless the moment the model is reset, and every caller
    wanted the id anyway.
    """

    #: Double-click or Enter — "play this".
    channel_activated = pyqtSignal(str)
    #: Selection moved (single click, arrow keys).
    channel_selected = pyqtSignal(str)
    #: Middle-click — the app's "open in the other pane" gesture.
    channel_middle_clicked = pyqtSignal(str)
    #: Right-click. Payload is (channel_id, global QPoint) so the caller can
    #: hand the point straight to ``QMenu.exec`` without re-deriving it.
    channel_context_menu = pyqtSignal(str, object)
    #: A delegate-painted chip was clicked: (facet_type, value).
    chip_clicked = pyqtSignal(str, str)
    #: (section key, word_only) — forwarded from the view's header control.
    section_mode_toggled = pyqtSignal(str, bool)

    #: How often the list re-paints so a fixture's state mark stays true.
    #:
    #: A MINUTE, and one shared timer for the whole list rather than one per
    #: row — the settled design's words. A row that says "On now" is a claim
    #: about the clock, and a list that never repaints keeps making it after the
    #: game has ended; that is the staleness the Watch Alerts list already had.
    #: Seconds were rejected as "busy and obnoxious", and a 1 Hz repaint of a
    #: virtualized list is real battery for no information — the mark changes at
    #: a window boundary, not continuously.
    #:
    #: Only the VIEWPORT repaints, so the cost is the rows on screen (tens), not
    #: the model (up to 785k).
    _STATE_TICK_MS = 60_000

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        config: Any = None,
        image_cache: Any = None,
        get_media_type_icon: Optional[Callable[[str | None], str]] = None,
        raw_name_tooltip: bool = False,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._get_media_type_icon = get_media_type_icon
        # See ChannelListModel._channel_data's ToolTipRole branch. Off by
        # default: the main list shows no tooltip on an unrated row, and that
        # is deliberate.
        self._raw_name_tooltip = bool(raw_name_tooltip)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.model = ChannelListModel(self)
        self.view = ChannelListView()
        self.view.setModel(self.model)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        # Density/thumbnails/platform-style come from the same three settings the
        # main list reads, so a Sports row and a Search row are the same row.
        self.delegate = ChannelRowDelegate(self.view, image_cache=image_cache)
        self.delegate.set_density(
            getattr(config, "channel_list_density", "comfy") if config else "comfy")
        self.delegate.set_thumbnails_enabled(
            bool(getattr(config, "channel_list_thumbnails", True)) if config else True)
        self.delegate.set_platform_name_style(
            getattr(config, "platform_name_style", "auto") if config else "auto")
        self.view.setItemDelegate(self.delegate)

        # Viewport-only poster hydration: downloads artwork for the rows on
        # screen and nothing else. Optional — without an image_cache the list
        # still paints, just without posters.
        self.hydrator = None
        if image_cache is not None:
            from metatv.gui.channel_list_thumbnails import ChannelThumbnailHydrator
            self.hydrator = ChannelThumbnailHydrator(
                self.model, image_cache, parent=self)
            self.hydrator.set_enabled(
                bool(getattr(config, "channel_list_thumbnails", True)) if config else True)
            self.view.set_thumbnail_hydrator(self.hydrator)

        layout.addWidget(self.view)

        # An error is a VISIBLE row, never an empty list — CLAUDE.md's
        # async-read rule. Kept as its own label rather than a fake model row so
        # it cannot be selected, played, or counted.
        self._error = QLabel("")
        self._error.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._error.setWordWrap(True)
        _theme.style(self._error, "EMPTY_LABEL")
        self._error.hide()
        layout.addWidget(self._error)

        self.view.doubleClicked.connect(self._on_activated)
        self.view.middle_clicked.connect(self._on_middle_clicked)
        self.view.chip_clicked.connect(self.chip_clicked)
        self.view.section_mode_toggled.connect(self.section_mode_toggled)
        self.view.customContextMenuRequested.connect(self._on_context_menu)
        if (sel := self.view.selectionModel()) is not None:
            sel.currentChanged.connect(self._on_current_changed)

        # Parented to self, so it dies with the widget and needs no entry in a
        # cleanup registry — the registry is for background managers that own
        # threads or pools, and a QTimer owns neither.
        self._state_tick = QTimer(self)
        self._state_tick.setInterval(self._STATE_TICK_MS)
        self._state_tick.timeout.connect(self._repaint_state_marks)
        self._state_tick.start()

    def _repaint_state_marks(self) -> None:
        """Re-paint the visible rows so "On now" cannot outlive the fixture.

        ``viewport().update()`` and nothing else: the model has not changed, so
        a reset would scroll the list out from under the reader to fix a word.
        """
        self.view.viewport().update()

    # ------------------------------------------------------------------ #
    # Content                                                             #
    # ------------------------------------------------------------------ #

    def set_rows(self, dtos, **kwargs) -> None:
        """Show these rows. ``dtos`` is a list of ``ChannelListDTO``.

        Extra keyword arguments pass straight through to
        ``ChannelListModel.set_channels`` for the callers that page or show
        provider badges; the defaults suit a view that loads one full result set.
        """
        self._error.hide()
        self.view.show()
        params = {
            "provider_icon_map": {},
            "show_provider_icon": False,
            "has_more": False,
            "query_params": {},
            "get_media_type_icon": self._get_media_type_icon,
            "raw_name_tooltip": self._raw_name_tooltip,
            "partial_threshold_pct": int(
                float(getattr(self._config, "watch_partial_threshold", 0.10) or 0.10) * 100
            ) if self._config else 10,
        }
        params.update(kwargs)
        self.model.set_channels(list(dtos), **params)

    def clear(self) -> None:
        self.set_rows([])

    def show_error(self, message: str) -> None:
        """Render a visible failure instead of an empty list."""
        logger.warning("ChannelResultsList: {}", message)
        self.model.set_channels(
            [], provider_icon_map={}, show_provider_icon=False,
            has_more=False, query_params={})
        self._error.setText(f"{_icons.notification_warning_icon} {message}")
        self.view.hide()
        self._error.show()

    def count(self) -> int:
        return self.model.rowCount()

    # ------------------------------------------------------------------ #
    # Interaction                                                         #
    # ------------------------------------------------------------------ #

    def _id_at(self, index: QModelIndex) -> str:
        return (index.data(Qt.ItemDataRole.UserRole) or "") if index.isValid() else ""

    def current_channel_id(self) -> str:
        return self._id_at(self.view.currentIndex())

    def _on_activated(self, index: QModelIndex) -> None:
        if (cid := self._id_at(index)):
            self.channel_activated.emit(cid)

    def _on_middle_clicked(self, index: QModelIndex) -> None:
        if (cid := self._id_at(index)):
            self.channel_middle_clicked.emit(cid)

    def _on_current_changed(self, current: QModelIndex, _previous) -> None:
        if (cid := self._id_at(current)):
            self.channel_selected.emit(cid)

    def _on_context_menu(self, pos) -> None:
        index = self.view.indexAt(pos)
        if (cid := self._id_at(index)):
            self.channel_context_menu.emit(
                cid, self.view.viewport().mapToGlobal(pos))
