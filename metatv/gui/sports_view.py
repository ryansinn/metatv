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

from functools import partial
from typing import Any, Callable

from loguru import logger
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QVBoxLayout,
)

from metatv.gui.channel_row_lead import discriminator_for
from metatv.gui.channel_results_list import ChannelResultsList
from metatv.gui.filter_bar import ToggleChip
from metatv.gui.content_view import ContentView
from metatv.gui.sports_filter_bar import SportsFilterBar
from metatv.gui.view_scope import resolve_visibility_scope


#: Lane chip labels, in the order the rundown presents them. The keys are
#: ``ChannelRepository.SPORTS_LANES`` — one vocabulary, so a chip cannot name a
#: lane the query does not have.
LANE_LABELS = {
    "live": "On now",
    "upcoming": "Upcoming",
    "channels": "Channels",
    "finished": "Finished",
    "placeholders": "No event",
}

#: Why each lane exists, said plainly — several are not self-evident.
LANE_TOOLTIPS = {
    "live": "Started recently and probably still on",
    "upcoming": "Scheduled, soonest first",
    "channels": "Always-on sports channels — no single fixture",
    "finished": "Already over, most recent first",
    "placeholders": "Feed slots the provider left empty — nothing is on them",
}


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
        # ONE TOKEN PER QUERY. _run_query increments the counter before every
        # submit and drops any result whose tag no longer matches, so two
        # concurrent reads sharing a counter means the SECOND one silently
        # cancels the FIRST. Rows and lane counts are fired together from
        # _reload_channels, so a shared token discarded the rows every time and
        # the view opened permanently empty while the chips filled in.
        # Every other view here already does it this way (_providers_token,
        # _results_token, _load_channels_token, …); this was the outlier.
        self._rows_token: list[int] = [0]
        self._counts_token: list[int] = [0]
        #: Set when the taxonomy query is SUBMITTED, not when it returns —
        #: two rapid activations would otherwise both see 'not loaded' and
        #: issue the same whole-corpus scan twice.
        self._taxonomy_requested = False
        #: Restore happens once per session, after the first taxonomy load.
        self._filters_restored = False
        #: The active lane. Restored from config so the view opens where the
        #: user left it (UI state persistence), defaulting to Upcoming.
        self._lane: str = getattr(config, "sports_lane", None) or self.DEFAULT_LANE
        if self._lane not in LANE_LABELS:
            self._lane = self.DEFAULT_LANE
        self._setup_ui()

    # ------------------------------------------------------------------ #
    # Construction                                                        #
    # ------------------------------------------------------------------ #

    #: The lane shown when the view opens. "live" would be empty most of the
    #: day and read as a broken view; "upcoming" is what a schedule is for.
    DEFAULT_LANE = "upcoming"

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.filter_bar = SportsFilterBar(self)
        self.filter_bar.filter_changed.connect(self._reload_channels)
        layout.addWidget(self.filter_bar)

        # Lane chips carry their own counts, so the standalone "183 channels"
        # line goes (mockup Q7). ToggleChip already renders "Label (N)" via
        # set_count and already supports a segmented track — nothing new was
        # built for this.
        lane_row = QHBoxLayout()
        lane_row.setSpacing(0)
        lane_row.setContentsMargins(0, 0, 0, 0)
        self._lane_chips: "dict[str, ToggleChip]" = {}
        last = len(LANE_LABELS) - 1
        for i, (lane, label) in enumerate(LANE_LABELS.items()):
            segment = "first" if i == 0 else ("last" if i == last else "middle")
            chip = ToggleChip(label, enabled=(lane == self._lane), segment=segment)
            chip.setToolTip(LANE_TOOLTIPS[lane])
            chip.clicked.connect(partial(self._on_lane_clicked, lane))
            self._lane_chips[lane] = chip
            lane_row.addWidget(chip)
        lane_row.addStretch()
        layout.addLayout(lane_row)

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

    def reload(self) -> None:
        """Re-read everything after a provider/source mutation.

        The centre views each expose this so ``_refresh_provider_dependent_views``
        has one thing to call. Sports was the ONLY one missing from that
        function — discover, preferences, recipe, missing_tmdb,
        reconnect_engaged and epg were all listed — so a source refresh that
        renamed rows left this view painting names that no longer existed.

        That is how the owner came to click "MLB 04 | Royals x Blue Jays" and
        watch Mariners x Red Sox: the refresh had renamed that row in place
        (same provider, same stream id), the database was correct, and only the
        view was stale. Nothing was playing the wrong stream — the title next
        to it was simply out of date.

        The taxonomy is re-read too: a refresh can add or remove a whole sport.
        """
        self._taxonomy_requested = False
        if self.isVisible():
            self.on_activate()

    def on_deactivate(self) -> None:
        """Drop any in-flight result.

        Symmetric with ``on_activate`` (CLAUDE.md: a view with one must have the
        other). Bumping the tokens is the cancel: the workers still finish, but
        their results are discarded instead of painting over whatever view the
        user switched to. BOTH counters, or the un-bumped read still lands.
        """
        self._rows_token[0] += 1
        self._counts_token[0] += 1

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
        # Restore the saved selection ONCE, after the chips exist — before this
        # the sport chips have not been built, so there is nothing to check.
        #
        # `restore_filter_state` was fully written (sports, leagues AND search)
        # and had ZERO callers, while `config.sports_filter_state` was declared
        # and never written: the feature was complete at both ends and connected
        # at neither, so every restart dropped the user's sport back to "all"
        # (owner, 2026-09-01: "Sports filters are not remembered on app
        # restart"). The lane survived because it saves separately.
        if not self._filters_restored:
            saved = getattr(self.config, "sports_filter_state", None) or {}
            if saved:
                self.filter_bar.restore_filter_state(saved)
                # ...and then actually APPLY it. restore_filter_state sets the
                # chips under blockSignals — correctly, or sixteen chips would
                # fire sixteen reloads — so nothing downstream ever hears about
                # it. Without this the chips render the saved sport while the
                # rows and lane counts are still the unfiltered first load: the
                # owner saw Baseball selected above a list of hockey fixtures
                # and "Channels (6524)" where the real filtered count is 142.
                #
                # Unselecting and reselecting the chip "fixed" it, which is the
                # tell — the toggle emits the signal the restore suppressed.
                #
                # Guarded on the state actually narrowing something, the same
                # call #626 made for the channel list: an empty saved state
                # matches what the first load already did, and re-querying 6,500
                # rows to reach the identical answer is pure cost.
                if any(saved.get(k) for k in ("sport_types", "league_names",
                                              "search")):
                    self._reload_channels()
            # LAST, and that ordering is the fix's second half. _reload_channels
            # saves the live filter state back to config, but ONLY once this flag
            # is set — which is exactly why the reload above runs while it is
            # still False. Setting it first (my first draft did) made the startup
            # reload write the CHIPS' state over the saved one, so a sport the
            # taxonomy no longer carries — which restore_filter_state drops
            # silently, by design — would be erased from config the first time a
            # source hiccuped. test_nothing_is_saved_before_the_restore_has_run
            # already documents this flag as the guard against precisely that,
            # and it is what caught the draft.
            self._filters_restored = True

    def _reload_channels(self, *, refresh_counts: bool = True) -> None:
        """Re-query for the current cascade selection.

        Args:
            refresh_counts: Re-run the lane counts too. False when only the
                LANE changed — the counts are computed over the whole
                facet-filtered set and do not depend on which lane is open, so
                a lane click would otherwise pay for a GROUP BY that cannot
                return a different answer.
        """
        state = self.filter_bar.get_filter_state()
        config = self.config

        # Every UI section remembers its state (DESIGN.md). Only write when it
        # actually changed: this runs on every keystroke in the fixture search,
        # and a config write is a full file rewrite plus a backup copy.
        if self._filters_restored and state != getattr(
                config, "sports_filter_state", None):
            config.sports_filter_state = dict(state)
            config.save()

        lane = self._lane

        def query(repos) -> list:
            scope = resolve_visibility_scope(repos, config)
            return repos.channels.get_sports_channels(
                scope,
                sport_types=state.get("sport_types") or None,
                league_names=state.get("league_names") or None,
                search=state.get("search") or None,
                lane=lane,
            )

        def count_query(repos) -> dict:
            scope = resolve_visibility_scope(repos, config)
            return repos.channels.get_sports_lane_counts(
                scope,
                sport_types=state.get("sport_types") or None,
                league_names=state.get("league_names") or None,
                search=state.get("search") or None,
            )

        self._run_query(
            query,
            self._on_channels_loaded,
            token_ref=self._rows_token,
            on_error=lambda exc: self._show_error("Couldn't load these channels"),
        )
        # Counts are a second read on purpose: one GROUP BY over the whole
        # facet-filtered set, independent of which lane is open, so switching
        # lanes never restates the other three from stale numbers.
        if refresh_counts:
            self._run_query(
                count_query,
                self._on_lane_counts_loaded,
                token_ref=self._counts_token,
                on_error=lambda exc: None,
            )

    def _on_channels_loaded(self, rows: Any) -> None:
        """Render the result, or a visible error — never a silent empty list."""
        if rows is None:
            self._show_error("Couldn't load these channels")
            return
        # Decide the leading slot BEFORE handing the rows over, so the first
        # paint is already correct rather than corrected. "What still
        # discriminates" is a fact about this result set, not about any row,
        # which is why the delegate is told rather than left to work it out —
        # a delegate paints one row and cannot see the other 9,768.
        self.channel_list.delegate.set_row_discriminator(
            discriminator_for((r.sport_type or "", r.detected_region or "")
                              for r in rows)
        )
        self.channel_list.set_rows(rows)

    # ------------------------------------------------------------------ #
    # Rendering                                                           #
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    # Interaction                                                         #
    # ------------------------------------------------------------------ #

    def _on_lane_clicked(self, lane: str) -> None:
        """Switch lanes. Exactly one is active — these are a view, not filters."""
        if lane == self._lane:
            # Re-clicking the active lane must not turn it off: an empty
            # rundown with no lane selected is a dead end, not a state.
            self._lane_chips[lane].setChecked(True)
            return
        self._lane = lane
        for key, chip in self._lane_chips.items():
            chip.setChecked(key == lane)
        # Every UI section remembers its state (DESIGN.md) — save on change.
        self.config.sports_lane = lane
        self.config.save()
        self._reload_channels(refresh_counts=False)

    def _on_lane_counts_loaded(self, counts: Any) -> None:
        """Paint each chip's count, or leave the labels bare if the query failed.

        A wrong number is worse than none: the chip is a promise about what the
        list holds, so on failure the chips say nothing rather than lying.
        """
        if not isinstance(counts, dict):
            return
        for lane, chip in self._lane_chips.items():
            chip.set_count(int(counts.get(lane, 0)))

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
