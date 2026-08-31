"""Sports view — the sport → league cascade over ``special_view = 'sports'``.

``sports_filter_bar.py`` has been 430 finished lines with zero importers, and
``ChannelRepository.get_sports_channels`` had zero callers. What was missing was
never the widget: the queries behind it showed every channel from every source,
including the 16,715 sports rows belonging to a provider the owner had switched
off. That is fixed in ``channel_stats._special_content_query``; this view is what
finally calls it.

Rows are built by ``chip_row.build_chip_row`` — the one row builder — rather
than a second renderer, so a change to row grammar reaches Sports the same day
it reaches History and Favorites.
"""

from __future__ import annotations

from typing import Any, Callable

from loguru import logger
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QLabel, QVBoxLayout,
)

from metatv.gui import theme as _theme
from metatv.gui.channel_results_list import ChannelResultsList
from metatv.gui.content_view import ContentView
from metatv.gui.sports_filter_bar import SportsFilterBar
from metatv.gui.view_scope import resolve_visibility_scope


class SportsView(ContentView):
    """Sport/league cascade over the classified sports channels.

    Signals mirror ``DiscoverView``'s names exactly, so the host wires this the
    same way it wires every other content view — the seam is the point, not the
    view.
    """

    channelSelected            = pyqtSignal(str)   # channel_id
    playRequested              = pyqtSignal(str)   # channel_id
    channelMiddleClicked       = pyqtSignal(str)   # channel_id
    # (channel_id, global x, global y) — the shape _on_rec_channel_context_menu
    # takes. It is three args, not a QPoint, and connecting the wrong shape
    # fails only when someone actually right-clicks.
    channelContextMenuRequested = pyqtSignal(str, int, int)

    def __init__(self, db, config, run_query: Callable, parent=None,
                 image_cache=None) -> None:
        """
        Args:
            db: Database instance (held for nothing but symmetry with siblings;
                every read goes through *run_query*).
            config: Live ``Config`` — the control layer resolves exclusions from
                it before the worker ever sees a scope (DR-0007).
            run_query: ``MainWindow._run_query``, the single async-read seam.
            parent: Qt parent.
            image_cache: Shared ``ImageCache``, so rows can show the same
                poster thumbnails the main channel list does. Optional —
                without it the list still paints, just without artwork.
        """
        super().__init__(config, parent)
        self._db = db
        self._run_query = run_query
        self._image_cache = image_cache
        #: Stale-result token. A fast sport→league→sport click sequence issues
        #: three queries; only the newest may render.
        self._token: list[int] = [0]
        #: Set when the taxonomy query is SUBMITTED, not when it returns —
        #: two rapid activations would otherwise both see 'not loaded' and
        #: issue the same whole-corpus scan twice.
        self._taxonomy_requested = False
        self._setup_ui()

    # ------------------------------------------------------------------ #
    # Construction                                                        #
    # ------------------------------------------------------------------ #

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.filter_bar = SportsFilterBar(self)
        self.filter_bar.filter_changed.connect(self._reload_channels)
        layout.addWidget(self.filter_bar)

        self.count_label = QLabel("", self)
        # ITEM_COUNT is the existing role for a "{n} things" label — the
        # filter groups use it, so this reads the same as the rest.
        _theme.style(self.count_label, "ITEM_COUNT")
        layout.addWidget(self.count_label)

        # The shared virtualized results list — NOT a QListWidget with a
        # widget per row. This view once built one live QWidget per channel and
        # froze the app for minutes on 9,769 rows; see channel_results_list.py
        # for the measurement and why the wiring is packaged there.
        self.channel_list = ChannelResultsList(
            self, config=self.config, image_cache=self._image_cache,
            # The title drops the league and quality the raw name carries
            # ("NHL-TEAM| CALGARY FLAMES HD"); the raw string stays reachable.
            raw_name_tooltip=True)
        self.channel_list.channel_selected.connect(self.channelSelected)
        self.channel_list.channel_activated.connect(self.playRequested)
        self.channel_list.channel_middle_clicked.connect(self.channelMiddleClicked)
        self.channel_list.channel_context_menu.connect(self._on_context_menu)
        layout.addWidget(self.channel_list, 1)

    # ------------------------------------------------------------------ #
    # Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    def on_activate(self) -> None:
        """Load the taxonomy once, then the channels for the current filter."""
        if not self._taxonomy_requested:
            self._taxonomy_requested = True
            self._load_taxonomy()
        self._reload_channels()

    def on_deactivate(self) -> None:
        """Drop any in-flight result.

        Symmetric with ``on_activate`` (CLAUDE.md: a view with one must have the
        other). Bumping the token is the cancel: the worker still finishes, but
        its result is discarded instead of painting over whatever view the user
        switched to.
        """
        self._token[0] += 1

    def get_view_name(self) -> str:
        return "sports"

    # ------------------------------------------------------------------ #
    # Loading                                                             #
    # ------------------------------------------------------------------ #

    def _load_taxonomy(self) -> None:
        """Fill the cascade dropdowns from the classified corpus."""
        config = self.config

        def query(repos) -> dict:
            scope = resolve_visibility_scope(repos, config)
            return {
                "taxonomy": repos.channels.get_sports_taxonomy(scope),
                "counts": repos.channels.get_sports_counts(scope),
            }

        self._run_query(
            query,
            self._on_taxonomy_loaded,
            on_error=lambda exc: self._on_taxonomy_loaded(None),
        )

    def _on_taxonomy_loaded(self, data: Any) -> None:
        if not data:
            # Let the next activation retry rather than leaving the dropdowns
            # empty for the rest of the session.
            self._taxonomy_requested = False
            self._show_error("Couldn't load the sport list")
            return
        self.filter_bar.load_taxonomy(data["taxonomy"], data["counts"])

    def _reload_channels(self) -> None:
        """Re-query for the current cascade selection."""
        state = self.filter_bar.get_filter_state()
        config = self.config

        def query(repos) -> list:
            scope = resolve_visibility_scope(repos, config)
            return repos.channels.get_sports_channels(
                scope,
                sport_types=state.get("sport_types") or None,
                league_names=state.get("league_names") or None,
            )

        self._run_query(
            query,
            self._on_channels_loaded,
            token_ref=self._token,
            on_error=lambda exc: self._show_error("Couldn't load these channels"),
        )

    def _on_channels_loaded(self, rows: Any) -> None:
        """Render the result, or a visible error — never a silent empty list."""
        if rows is None:
            self._show_error("Couldn't load these channels")
            return
        self.channel_list.set_rows(rows)
        self.count_label.setText(
            f"{len(rows):,} channel{'' if len(rows) == 1 else 's'}")

    # ------------------------------------------------------------------ #
    # Rendering                                                           #
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    # Interaction                                                         #
    # ------------------------------------------------------------------ #

    def _on_context_menu(self, channel_id: str, global_pos) -> None:
        """Re-emit as (id, x, y) — the shape ``_on_rec_channel_context_menu``
        takes. The harness hands over a QPoint because that is what QMenu wants;
        this view's published signal predates it and other hosts connect to it.
        """
        self.channelContextMenuRequested.emit(
            channel_id, global_pos.x(), global_pos.y())

    # ------------------------------------------------------------------ #
    # Failure                                                             #
    # ------------------------------------------------------------------ #

    def _show_error(self, message: str) -> None:
        """Render a visible, non-selectable error row.

        CLAUDE.md's async-read rule: a failed background load must never look
        like a silently-empty result — never ``clear(); return``.
        """
        logger.warning("SportsView: {}", message)
        self.channel_list.show_error(message)
        self.count_label.setText("")
