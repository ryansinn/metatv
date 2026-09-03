"""Hosting the chip bar: one place that decides what the filter UI looks like.

The window has two ways to present filters — the ``Includes:`` column, and a
one-line chip bar with the column opened on demand. Which one is showing is a
question several code paths ask (startup, every view switch, the Tools menu,
"+ Add filter"), and the failure mode if they each answer it themselves is the
one this codebase has hit repeatedly: the channel-list restore path sets
``filter_panel.setVisible(True)`` unconditionally, so in chip mode the column
would come back every time you left a view and returned.

So there is exactly one answer: :meth:`_apply_filter_ui_mode`. Every path calls
it, nobody sets either widget's visibility directly, and the mode lives in
config rather than in a widget's current state — which is the lesson already written into
``toggle_filters``, where direction was read from the measured splitter
size and the panel could therefore never be turned back on.
"""

from __future__ import annotations

from loguru import logger

from metatv.gui.filter_chip_bar import FilterChipBar
from metatv.gui.filter_chips import describe_active_filters
from metatv.gui import deferred_config_save as _cfgsave

#: The two presentations. Anything else in config is treated as "chips".
MODE_CHIPS = "chips"
MODE_PANEL = "panel"


class _FilterChipHostMixin:
    """Builds, wires and synchronises the active-filter chip bar."""

    # ── Construction ─────────────────────────────────────────────────────────

    def _create_filter_chip_bar(self) -> FilterChipBar:
        """Build the bar and connect it to the panel. Caller does the layout."""
        bar = FilterChipBar()
        bar.remove_requested.connect(self._on_filter_chip_removed)
        bar.add_requested.connect(self._on_filter_chip_add)
        bar.clear_requested.connect(self._on_filter_chip_clear)
        bar.results_filter_changed.connect(self._on_results_filter_changed)
        self.filter_chip_bar = bar
        return bar

    def _on_results_filter_changed(self, text: str) -> None:
        """Narrow the rows already on screen. No re-query, nothing persisted.

        Straight to the model, deliberately not through the filter/query path:
        every other chip on this bar changes WHAT IS FETCHED, and routing this
        one the same way would re-run a 785,551-row query on every keystroke to
        answer a question about the hundred rows already in front of the user.
        """
        model = self.__dict__.get("channel_model")
        if model is not None:
            model.set_result_filter(text)

    # ── The chokepoint ───────────────────────────────────────────────────────

    def filter_ui_mode(self) -> str:
        mode = getattr(self.config, "filter_ui_mode", MODE_CHIPS)
        return MODE_PANEL if mode == MODE_PANEL else MODE_CHIPS

    def _apply_filter_ui_mode(self) -> None:
        """Show whichever filter UI the current mode calls for.

        Whether the COLUMN is up is not decided here — it is
        ``config.filter_section_visible``, which the Layout menu and the
        panel's own toggle already own. This method reads that flag; it does
        not invent a second one. Two flags for one panel is how a menu tick
        starts disagreeing with the screen.

        In panel mode the column is always up and the chip line never appears:
        the column already lists what is selected, so chips would be the same
        information twice, in less detail.
        """
        panel = self.__dict__.get("filter_panel")
        bar = self.__dict__.get("filter_chip_bar")
        if panel is None:
            return

        if self.filter_ui_mode() == MODE_PANEL:
            self.config.filter_section_visible = True
            panel.setVisible(True)
            if bar is not None:
                bar.setVisible(False)
            self._set_filter_panel_width(getattr(self.config, "filter_panel_width", 220))
            return

        if bar is not None:
            bar.setVisible(True)
        self._shut_column_at_launch()
        panel_open = bool(getattr(self.config, "filter_section_visible", False))
        panel.setVisible(panel_open)
        if panel_open:
            self._set_filter_panel_width(getattr(self.config, "filter_panel_width", 220))
        self._sync_filter_chips()

    def _shut_column_at_launch(self) -> None:
        """In chip mode the column starts shut, every launch.

        Not a persisted preference and not a migration flag — a *rule*. Chip
        mode means the line is the filter UI and the column is a thing you open
        when you need it, the way a disclosure works: you open it, you use it,
        next launch you are back to the clean line. Someone who wants the column
        permanently up is describing panel mode, which persists exactly that.

        Stating it this way also removes a whole class of problem. A stored
        "have the chips taken over yet" flag has to be right for a fresh
        install, for every existing config (all of which carry
        ``filter_section_visible: true``), and for a config that was written
        while the flag meant something slightly different. A rule applied at
        launch is right for all of them without knowing which it is.

        Runs once per session; after that the column is the user's to open and
        shut, and ``config.filter_section_visible`` tracks it as it always has
        so the Layout menu's tick stays honest.
        """
        if self.__dict__.get("_filter_column_launched"):
            return
        self._filter_column_launched = True
        self.config.filter_section_visible = False

    def _set_filter_panel_width(self, width: int) -> None:
        """Give the column its persisted width without disturbing the list's."""
        splitter = self.__dict__.get("_inner_splitter")
        if splitter is None:
            return
        sizes = splitter.sizes()
        if len(sizes) != 2:
            return
        total = sum(sizes)
        w = max(160, int(width) or 220)
        splitter.setSizes([w, max(200, total - w)])

    def toggle_filter_ui_mode(self) -> str:
        """Switch between the chip bar and the column, and persist the choice."""
        new_mode = MODE_PANEL if self.filter_ui_mode() == MODE_CHIPS else MODE_CHIPS
        self.config.filter_ui_mode = new_mode
        # Switching TO chips shuts the column — leaving it up would show both
        # presentations at once, which is the layout the chips exist to undo.
        # Switching to panel mode opens it, because in that mode it IS the UI.
        self.config.filter_section_visible = (new_mode == MODE_PANEL)
        _cfgsave.save_soon(self)
        self._apply_filter_ui_mode()
        logger.info(f"Filter UI mode → {new_mode}")
        return new_mode

    # ── Content ──────────────────────────────────────────────────────────────

    def _sync_filter_chips(self) -> None:
        """Redescribe the active filters on the chip line.

        Reads the panel's own resolved state, so the chips cannot disagree with
        the query that produced the list underneath them.
        """
        bar = self.__dict__.get("filter_chip_bar")
        panel = self.__dict__.get("filter_panel")
        if bar is None or panel is None:
            return
        state = self.current_filter_state or panel.get_filter_state()
        bar.set_chips(describe_active_filters(
            state,
            label_for=panel.label_for,
            facet_totals=panel.facet_totals(),
        ))

    # ── Chip actions ─────────────────────────────────────────────────────────

    def _on_filter_chip_removed(self, facet: str) -> None:
        """A chip's × — lift that one constraint.

        ``clear_facet`` emits the panel's ``filter_changed``, which is already
        wired to ``on_filter_changed``; the reload and the chip refresh both
        happen there. Doing either here as well would run the query twice.
        """
        panel = self.__dict__.get("filter_panel")
        if panel is None:
            return
        panel.clear_facet(facet)

    def _on_filter_chip_add(self) -> None:
        """"+ Add filter" — open the full column, or shut it if it is already up.

        Routes through ``toggle_filters``, the app's existing open/close
        path, rather than setting visibility here: that one already persists the
        flag and restores the remembered width, and the Layout menu reads the
        same flag, so the menu tick follows this button for free.
        """
        if self.__dict__.get("filter_panel") is None:
            return
        self.toggle_filters()

    def _on_filter_chip_clear(self) -> None:
        """"Clear all" — everything ticked, nothing constrained."""
        panel = self.__dict__.get("filter_panel")
        if panel is None:
            return
        panel.select_all_sections()
