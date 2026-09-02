"""Mixin for the EPG View's Watchlist / My-Channels / Discover tabs (Band 10 B10-4).

``_EpgWatchlistMixin`` is a plain Python mixin — it does NOT inherit from QWidget.
It is mixed into ``EpgView`` via multiple inheritance and accesses all shared
instance state through ``self`` at runtime (MRO resolution).

The three tabs share one fetch+render path: ``_reload_watchlist`` schedules
``_fetch_watchlist`` on the executor, which emits ``_data_loaded``;
``_on_data_loaded`` dispatches to ``_render_watchlist``, which populates the
Watchlist, My-Channels, and Discover (recommendations) pages.

Methods moved here (verbatim from ``EpgView``):
    _build_watchlist_tab
    _build_channels_tab
    _build_discover_tab
    _reload_watchlist
    _fetch_watchlist
    _on_data_loaded
    _render_watchlist
    _make_watchlist_item
    _make_quiet_section
    _make_channel_item
    _make_recommendation_item
    _load_rec_matches
    _on_add_pattern
    _add_pattern
    _remove_pattern
    _dismiss_channel
    _dismissed_ids
    _manage_dismissed

All other helpers these methods call (``self._build_name_map``,
``self._filtered_provider_ids``, ``self._play_channel``,
``self._emit_channel_selected``, ``self._watch_channel``,
``self._unwatch_channel``, ``self._render_on_now`` / ``self._render_browse`` /
``self._render_events`` dispatched from ``_on_data_loaded``, the
``_channel_*_map`` dicts, the ``_data_loaded`` signal, etc.) remain in
``EpgView`` (or other mixins) and resolve via ``self`` / MRO.

NOTE: ``_make_recommendation_item`` and ``_make_channel_item`` no longer call
``parse_channel_name`` at render time (CLAUDE.md ingestion-only rule). They read
stored ``_channel_*_map`` dicts populated from ``detected_*`` columns, including
``_channel_audio_map`` from the new ``detected_audio`` JSONEncoded column
(added in tasks #82/#24).  The CLAUDE.md exception that previously permitted
render-parse here is now removed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from loguru import logger

from metatv.core import watchlist
from metatv.core.channel_name_utils import quality_tier_rank
from metatv.core.database import ChannelDB, EpgProgramDB
from metatv.core.epg_utils import (
    now_utc as _now_utc,
    fmt_time as _format_time,
    minutes_away as _minutes_away,
    remaining_str as _remaining_str,
    is_local_today as _is_local_today,
    local_weekday as _local_weekday,
)
from metatv.gui.badge_utils import (
    make_audio_chip,
    make_quality_chip,
    make_region_chip,
    make_year_chip,
)
from metatv.gui import cursor_affordance
from metatv.gui import theme as _theme
from metatv.gui import icons as _icons
from metatv.gui.epg_widgets import _DismissedDialog, _parse_iso


class _EpgWatchlistMixin:
    """Watchlist / My-Channels / Discover-tab methods for EpgView.

    Mixed into ``EpgView`` — all ``self.*`` references resolve via MRO.
    """

    # ── Tab 0: Watchlist ───────────────────────────────────────────────

    def _build_watchlist_tab(self) -> None:
        #: pattern -> (matched, suppressed, capped) from the last background
        #: read. Empty until the first payload lands, which is why the rule row
        #: renders "counting…" rather than a zero it has not measured.
        self._rule_counts: dict[str, tuple[int, int, bool]] = {}
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        # A bare text box stopped fitting the moment a watchlist entry grew a
        # match mode, an exclude list and a scope. Owner: *"having just the
        # plain text box does not work with the complexity of the watchlist
        # rule now."* So the same editor that EDITS an entry now composes one,
        # behind a disclosure — the list stays scannable and the form you fill
        # in is the form you come back to.
        from metatv.gui.watch_rule_editor import WatchRuleEditor

        self._new_item_btn = QPushButton(
            f"{_icons.expand_icon}  Track something new")
        self._new_item_btn.setFlat(True)
        _theme.style(self._new_item_btn, "LINK_BTN_SM")
        self._new_item_btn.setToolTip(
            "Watch for a show or keyword across all of your sources")
        self._new_item_btn.clicked.connect(self._toggle_compose)
        new_row = QHBoxLayout()
        new_row.addWidget(self._new_item_btn)
        new_row.addStretch()
        layout.addLayout(new_row)

        self._compose_editor = WatchRuleEditor(compose=True)
        self._compose_editor.setVisible(False)
        self._compose_editor.rule_committed.connect(self._on_compose_committed)
        self._compose_editor.cancelled.connect(self._close_compose)
        layout.addWidget(self._compose_editor)

        # Pattern cards — responsive FlowLayout
        self.watchlist_scroll = QScrollArea()
        self.watchlist_scroll.setWidgetResizable(True)
        self.watchlist_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.watchlist_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.watchlist_scroll.setWidget(QWidget())  # placeholder; fully rebuilt each render
        layout.addWidget(self.watchlist_scroll, 1)

        self.stack.addWidget(page)

    def _build_channels_tab(self) -> None:
        from metatv.gui.flow_layout import FlowLayout
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("Pinned channels — right-click any channel in On Now to add one."))
        hdr.addStretch()
        layout.addLayout(hdr)

        self.channels_scroll = QScrollArea()
        self.channels_scroll.setWidgetResizable(True)
        self.channels_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.channels_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.channels_content = QWidget()
        self.channels_layout = FlowLayout(self.channels_content, spacing=8)
        self.channels_scroll.setWidget(self.channels_content)
        layout.addWidget(self.channels_scroll, 1)

        self.ch_empty_label = QLabel(
            "No channels pinned yet.\nRight-click any channel in On Now → Watch this channel."
        )
        self.ch_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _theme.style(self.ch_empty_label, "EMPTY_LABEL")

        self.stack.addWidget(page)

    def _build_discover_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        rec_header = QHBoxLayout()
        self._rec_title_lbl = QLabel("Channels with content matching your watchlist patterns:")
        _theme.style(self._rec_title_lbl, "CHANNEL_NAME_DIM")
        rec_header.addWidget(self._rec_title_lbl)
        rec_header.addStretch()
        self.manage_dismissed_btn = QPushButton("Manage dismissed")
        _theme.style_fn(self.manage_dismissed_btn, lambda: f"color: {_theme.COLOR_TEXT}; font-size: {_theme.FONT_MD}; border: none; background: transparent;")
        self.manage_dismissed_btn.clicked.connect(self._manage_dismissed)
        rec_header.addWidget(self.manage_dismissed_btn)
        layout.addLayout(rec_header)

        self.rec_scroll = QScrollArea()
        self.rec_scroll.setWidgetResizable(True)
        self.rec_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.rec_content = QWidget()
        self.rec_layout = QVBoxLayout(self.rec_content)
        self.rec_layout.setSpacing(4)
        self.rec_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.rec_scroll.setWidget(self.rec_content)
        layout.addWidget(self.rec_scroll, 1)

        self.rec_empty_label = QLabel(
            "Add watchlist patterns to get channel recommendations."
        )
        self.rec_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _theme.style(self.rec_empty_label, "EMPTY_LABEL")

        self.stack.addWidget(page)

    # ── Reload + background fetch ──────────────────────────────────────

    def _reload_watchlist(self) -> None:
        patterns = list(watchlist.patterns(self.config))
        provider_ids = self._filtered_provider_ids()
        self._show_watchlist_loading()
        self._executor.submit(self._fetch_watchlist, patterns, provider_ids)

    def _show_watchlist_loading(self) -> None:
        """Swap a transient loading placeholder into the watchlist scroll area.

        The watchlist scroll's widget is fully rebuilt each render via takeWidget();
        this occupies the load window so the tab never shows its stale prior/empty
        content while the background fetch runs. ``_render_watchlist`` replaces it.
        """
        old = self.watchlist_scroll.takeWidget()
        if old:
            old.deleteLater()
        placeholder = QWidget()
        layout = QVBoxLayout(placeholder)
        layout.setContentsMargins(12, 20, 12, 12)
        loading = QLabel(f"{_icons.loading_icon} Loading watchlist…")
        loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _theme.style(loading, "LOADING_TEXT")
        layout.addWidget(loading)
        layout.addStretch()
        self.watchlist_scroll.setWidget(placeholder)

    def _fetch_watchlist(self, patterns: list[str], provider_ids: list[str]) -> None:
        session = self.db.get_session()
        try:
            from metatv.core.repositories import RepositoryFactory
            repos = RepositoryFactory(session)
            excluded_ch_provider_ids = set(repos.providers.get_hidden_provider_ids())
            repo = repos.epg
            watchlist_data = repo.get_upcoming_for_watchlist(
                patterns, hours_ahead=48,
                provider_ids=provider_ids,
                excluded_channel_provider_ids=excluded_ch_provider_ids,
            )
            live_data = repo.get_live_for_watchlist(
                patterns,
                provider_ids=provider_ids,
                excluded_channel_provider_ids=excluded_ch_provider_ids,
            )

            # Build dismissed set (expired entries are filtered out)
            now = _now_utc()
            dismissed = {
                cid for cid, ts_str in self.config.epg_dismissed_channels.items()
                if _parse_iso(ts_str) > now
            }

            recs = repo.get_recommendations(
                patterns=patterns,
                dismissed_ids=dismissed,
                provider_ids=provider_ids,
                limit=8,
                excluded_channel_provider_ids=excluded_ch_provider_ids,
            )

            # Build channel name map
            name_map = self._build_name_map(session, watchlist_data, live_data)
            self._channel_name_map.update(name_map)

            # MY CHANNELS — current program for each pinned channel
            channel_ids = self.config.epg_watchlist_channels
            channel_now: dict[str, EpgProgramDB | None] = {}
            channel_names: dict[str, str] = {}
            # Why each pinned channel can or cannot produce an alert.
            #
            # The card said "No EPG data" for every channel without a current
            # programme, which conflates three different situations: a guide
            # that simply does not cover it right now (transient, worth
            # waiting for), a source the user has switched off, and a provider
            # that no longer exists. The last two can NEVER fire, and the owner
            # had one of each pinned with nothing on screen saying so.
            #
            # excluded_ch_provider_ids is get_hidden_provider_ids() — inactive
            # ∪ expired ∪ orphaned — the canonical gate, already computed above
            # for the queries. Read here rather than re-derived (CLAUDE.md:
            # never rebuild that set ad hoc).
            channel_state: dict[str, str] = {}
            for cid in channel_ids:
                channel_now[cid] = repo.get_now_for_channel(cid)
                ch = session.query(ChannelDB).filter_by(id=cid).first()
                channel_names[cid] = ch.name if ch else cid
                if ch is None:
                    channel_state[cid] = "gone"
                elif ch.provider_id in excluded_ch_provider_ids:
                    channel_state[cid] = "source_off"
                else:
                    channel_state[cid] = "ok"

            # Rule-row summary counts, on this thread because it is a guide
            # scan. Failure degrades to "no counts" — the rule row then says
            # "counting…" forever, which is honest; it must never take the
            # watchlist down with it.
            try:
                rule_counts = repo.count_for_watchlist(
                    watchlist.rules(self.config),
                    provider_ids=provider_ids,
                    excluded_channel_provider_ids=excluded_ch_provider_ids,
                )
            except Exception:
                logger.exception("EpgView: watch-rule counts failed")
                rule_counts = {}

            self._data_loaded.emit({
                "tab": "watchlist",
                "rule_counts": rule_counts,
                "watchlist_data": watchlist_data,
                "live_data": live_data,
                "recommendations": recs,
                "dismissed": dismissed,
                "channel_now": channel_now,
                "channel_names": channel_names,
                "channel_state": channel_state,
            })
        except Exception as e:
            logger.error(f"EpgView watchlist fetch error: {e}")
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Main-thread render slots
    # ------------------------------------------------------------------

    def _on_data_loaded(self, payload: dict) -> None:
        tab = payload["tab"]
        if tab == "watchlist":
            # Read by _make_watchlist_item rather than threaded through
            # _render_watchlist, whose signature is already seven parameters
            # wide and has three call sites.
            self._rule_counts = payload.get("rule_counts", {})
            self._render_watchlist(
                payload["watchlist_data"],
                payload["live_data"],
                payload["recommendations"],
                payload["dismissed"],
                payload.get("channel_now", {}),
                payload.get("channel_names", {}),
                payload.get("channel_state", {}),
            )
        elif tab == "on_now":
            self._render_on_now(payload["programs"])
        elif tab == "browse":
            # Drop STALE async browse results: a payload tagged with a search string
            # that no longer matches the search box means a newer keystroke (or a
            # clear) superseded it. Without this guard a slow empty-search full-
            # schedule fetch can land after the user's search and revert Browse to
            # ALL content (flagged 454e01bf). This re-applies the active search box
            # on every refresh.
            payload_search = payload.get("search")
            if (
                payload_search is not None
                and payload_search != self.search_input.text().strip()
            ):
                return
            # Generation guard: a paginated "load more" page that arrives after the
            # user changed the anchor (a fresh reload bumped _browse_gen) is stale —
            # appending it to the freshly-cleared list would corrupt the order.
            gen = payload.get("gen")
            if gen is not None and gen != getattr(self, "_browse_gen", gen):
                return
            # Advance the keyset cursor / exhausted flag so the scroll handler knows
            # whether (and from where) to fetch the next page.
            self._browse_cursor = payload.get("cursor")
            self._browse_exhausted = payload.get("exhausted", True)
            self._browse_loading = False
            # Size the Phase-2 timeline scrubber from this fresh page's scoped guide
            # bounds (only sent on non-append pages; the helper no-ops without a
            # scrubber, so lightweight test hosts are unaffected).
            if not payload.get("append", False) and "guide_bounds" in payload:
                if hasattr(self, "_configure_scrubber"):
                    self._configure_scrubber(
                        payload.get("guide_bounds"),
                        payload.get("oldest_airing_start"),
                    )
            self._render_browse(
                payload["programs"],
                payload.get("placeholder", False),
                payload.get("guide_end"),
                payload.get("append", False),
            )
        elif tab == "events":
            self._events_dto_cache = payload["dtos"]
            self._render_events(self._events_dto_cache)

    # ── Watchlist render ───────────────────────────────────────────────

    def _render_watchlist(self, watchlist_data: dict, live_data: dict,
                          recommendations: list, dismissed: set,
                          channel_now: dict | None = None,
                          channel_names: dict | None = None,
                          channel_state: dict | None = None) -> None:

        old_wl = self.watchlist_scroll.takeWidget()
        if old_wl:
            old_wl.deleteLater()

        wl_content = QWidget()
        wl_outer = QVBoxLayout(wl_content)
        wl_outer.setContentsMargins(0, 4, 0, 8)
        wl_outer.setSpacing(0)

        patterns = watchlist.patterns(self.config)

        if not patterns:
            empty = QLabel("No watchlist items yet.\nAdd a show or keyword above to get started.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            _theme.style_fn(empty, lambda: f"color: {_theme.COLOR_MUTED_2}; font-size: {_theme.FONT_XL}; padding: 20px;")
            wl_outer.addWidget(empty)
            wl_outer.addStretch()
        else:
            on_now: list[tuple] = []
            upcoming_only: list[tuple] = []
            off_air: list[str] = []

            for pattern in patterns:
                live_progs = live_data.get(pattern, [])
                upc = watchlist_data.get(pattern, [])
                if live_progs:
                    on_now.append((pattern, live_progs, upc))
                elif upc:
                    upcoming_only.append((pattern, upc))
                else:
                    off_air.append(pattern)

            def _section_hdr(text: str) -> QLabel:
                lbl = QLabel(text)
                _theme.style(lbl, "SECTION_HDR")
                return lbl

            def _two_col_row(cards: list, h_estimates: list[int]) -> QWidget:
                """Greedy 2-column layout: always add each card to the shorter column.
                Preserves original order within each column."""
                col0_h, col0_cards = 0, []
                col1_h, col1_cards = 0, []
                for card, h in zip(cards, h_estimates):
                    if col0_h <= col1_h:
                        col0_cards.append(card)
                        col0_h += h
                    else:
                        col1_cards.append(card)
                        col1_h += h

                container = QWidget()
                h_layout = QHBoxLayout(container)
                h_layout.setContentsMargins(0, 0, 0, 0)
                h_layout.setSpacing(8)
                for col_cards in (col0_cards, col1_cards):
                    col_w = QWidget()
                    col_v = QVBoxLayout(col_w)
                    col_v.setContentsMargins(0, 0, 0, 0)
                    col_v.setSpacing(8)
                    for card in col_cards:
                        col_v.addWidget(card)
                    col_v.addStretch()
                    h_layout.addWidget(col_w, 1)
                return container

            if on_now:
                wl_outer.addWidget(_section_hdr(f"ON NOW  ·  {len(on_now)}"))
                cards = [self._make_watchlist_item(p, l, u[:3]) for p, l, u in on_now]
                h_ests = [max(len(l), 1) for p, l, u in on_now]
                wl_outer.addWidget(_two_col_row(cards, h_ests))

            if upcoming_only:
                wl_outer.addWidget(_section_hdr(f"UPCOMING  ·  {len(upcoming_only)}"))
                cards = [self._make_watchlist_item(p, [], u[:3]) for p, u in upcoming_only]
                h_ests = [max(len(u), 1) for p, u in upcoming_only]
                wl_outer.addWidget(_two_col_row(cards, h_ests))

            if off_air:
                wl_outer.addWidget(self._make_quiet_section(off_air))

            wl_outer.addStretch()

        self.watchlist_scroll.setWidget(wl_content)

        # MY CHANNELS
        while self.channels_layout.count():
            child = self.channels_layout.takeAt(0)
            w = child.widget()
            if w:
                if w is self.ch_empty_label:
                    w.setParent(None)
                else:
                    w.deleteLater()

        channel_ids = self.config.epg_watchlist_channels
        channel_now = channel_now or {}
        channel_names = channel_names or {}

        if not channel_ids:
            self.channels_layout.addWidget(self.ch_empty_label)
        else:
            channel_state = channel_state or {}
            for cid in channel_ids:
                prog = channel_now.get(cid)
                name = channel_names.get(cid, cid)
                self.channels_layout.addWidget(
                    self._make_channel_item(cid, name, prog, channel_state.get(cid, "ok"))
                )

        # Recommendations
        while self.rec_layout.count():
            child = self.rec_layout.takeAt(0)
            w = child.widget()
            if w:
                if w is self.rec_empty_label:
                    w.setParent(None)
                else:
                    w.deleteLater()

        if not recommendations:
            self.rec_layout.addWidget(self.rec_empty_label)
        else:
            for channel_db_id, channel_name, count in recommendations:
                self.rec_layout.addWidget(
                    self._make_recommendation_item(channel_db_id, channel_name, count)
                )

    def _watchlist_rank_key(self, prog: EpgProgramDB) -> tuple[int, int, str]:
        """Sort key ranking a channel within a watchlist title-match group.

        Order: quality tier desc (4K > FHD > HD > SD, via the canonical
        :func:`quality_tier_rank`), then previously-watched channels
        (``play_count > 0``) first, then a stable name tiebreak — so the
        ``_MAX_VISIBLE`` / ``[:2]`` display caps in ``_make_watchlist_item`` keep
        the best surviving streams instead of an arbitrary raw-SQL-order subset.

        Reads the ``_channel_quality_map`` / ``_channel_watch_map`` /
        ``_channel_title_map`` dicts populated by ``_build_name_map`` — no
        per-row query and no ``parse_channel_name()`` call (ingestion-only rule,
        CLAUDE.md).

        Args:
            prog: An ``EpgProgramDB`` row from a live or upcoming match group.

        Returns:
            A tuple sortable ascending (lower sorts first): ``(-tier, -watched,
            name)``.
        """
        cid = prog.channel_db_id or ""
        tier = quality_tier_rank(self._channel_quality_map.get(cid, ""))
        play_count = self._channel_watch_map.get(cid, (0, None))[0]
        watched = 1 if play_count > 0 else 0
        name = self._channel_title_map.get(cid) or self._channel_name_map.get(cid, "")
        return (-tier, -watched, name.casefold())

    def _make_watchlist_item(self, pattern: str, live: list[EpgProgramDB],
                              upcoming: list[EpgProgramDB]) -> QWidget:
        from collections import defaultdict

        w = QWidget()
        w.setMinimumWidth(320)
        w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        _theme.style(w, "CARD_BG")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(3)

        # ── Header ──────────────────────────────────────────────────────── #
        is_live = bool(live)
        icon = self.config.live_indicator_icon if is_live else self.config.watchlist_icon

        # Group live programmes by show title (most channels = most popular first).
        # Within each group, rank channels (best quality tier, then previously-
        # watched, then name) so the _MAX_VISIBLE display cap below keeps the best
        # surviving streams, not an arbitrary raw-SQL-order subset.
        title_groups: dict[str, list] = defaultdict(list)
        for prog in live:
            title_groups[prog.title].append(prog)
        for progs in title_groups.values():
            progs.sort(key=self._watchlist_rank_key)
        title_groups = dict(sorted(title_groups.items(), key=lambda kv: -len(kv[1])))

        header = QHBoxLayout()
        pattern_lbl = QLabel(f"{icon}  {pattern}")
        _theme.style(pattern_lbl, "LIST_TITLE")
        header.addWidget(pattern_lbl)

        search_btn = QPushButton("Show all in Search")
        search_btn.setFlat(True)
        _theme.style(search_btn, "LINK_BTN_SM")
        search_btn.setToolTip(f'Search all channels for "{pattern}"')
        search_btn.clicked.connect(lambda _=False, p=pattern: self.search_requested.emit(p))
        header.addWidget(search_btn)

        header.addStretch()

        if is_live:
            n = len(live)
            live_lbl = QLabel(f"ON NOW ({n})" if n > 1 else "ON NOW")
            _theme.style_fn(live_lbl, lambda: f"color: {_theme.COLOR_OK}; font-size: {_theme.FONT_LG};")
            header.addWidget(live_lbl)

        edit_btn = QPushButton(f"Edit {_icons.expand_icon}")
        edit_btn.setFlat(True)
        _theme.style(edit_btn, "LINK_BTN_SM")
        edit_btn.setToolTip(f'Change how "{pattern}" matches')
        header.addWidget(edit_btn)

        remove_btn = QPushButton(self.config.close_icon)
        remove_btn.setFixedWidth(24)
        remove_btn.setToolTip(f"Remove '{pattern}' from watchlist")
        _theme.style(remove_btn, "CLOSE_BTN")
        remove_btn.clicked.connect(lambda _=False, p=pattern: self._remove_pattern(p))
        header.addWidget(remove_btn)
        layout.addLayout(header)

        self._attach_rule_editor(layout, pattern, edit_btn)

        # ── Live title groups ────────────────────────────────────────────── #
        _MAX_VISIBLE = 3  # channels shown per title group before "more" toggle
        _MAX_GROUPS = 4   # title groups shown per card before "more programs" toggle

        def _ch_row(prog):
            """Build one channel row: Xm left [REGION] [LANG?] bare_name [QUALITY?] year? [▶]

            Reads stored detected_* maps (prefix/title/quality/region/year/audio) — no
            parse_channel_name() call (ingestion-only rule, CLAUDE.md).
            """
            cid = prog.channel_db_id or ""
            raw_name = self._channel_name_map.get(cid, prog.channel_epg_id)
            category = self._channel_prefix_map.get(cid, "")
            bare_name = self._channel_title_map.get(cid, raw_name)
            region = self._channel_region_map.get(cid, "")
            display_quality = self._channel_quality_map.get(cid, "")
            year = self._channel_year_map.get(cid, "")

            row_w = QWidget()
            cursor_affordance.set_clickable(row_w)
            row_w.mousePressEvent = lambda e, c=prog.channel_db_id: self._emit_channel_selected(c)
            row = QHBoxLayout(row_w)
            row.setContentsMargins(16, 0, 4, 0)
            row.setSpacing(4)

            time_lbl = QLabel(f"{_remaining_str(prog.stop_time)}  ·")
            time_lbl.setFixedWidth(90)
            time_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            _theme.style(time_lbl, "TIME_LABEL")
            row.addWidget(time_lbl)

            if category:
                row.addWidget(make_region_chip(category, row_w))
            if region:
                row.addWidget(make_region_chip(region, row_w))

            name_lbl = QLabel(bare_name)
            _theme.style(name_lbl, "CHANNEL_NAME_LIVE")
            row.addWidget(name_lbl, 1)

            if display_quality:
                row.addWidget(make_quality_chip(display_quality, row_w))
            if year:
                row.addWidget(make_year_chip(year, row_w))

            pb = QPushButton(self.config.play_icon)
            pb.setFixedSize(22, 20)
            pb.setFlat(True)
            pb.setToolTip(f"Play: {bare_name}")
            _theme.style(pb, "PLAY_BTN")
            cid = prog.channel_db_id
            pb.clicked.connect(lambda _=False, c=cid: self._play_channel(c))
            row.addWidget(pb)
            return row_w

        def _render_group(title: str, progs: list, target_layout) -> None:
            """Render one title group (label + channel rows + optional expand) into target_layout."""
            if title.casefold() != pattern.casefold():
                title_lbl = QLabel(title)
                title_lbl.setWordWrap(True)
                # Ignored policy: long titles don't inflate the card's minimum/preferred width
                title_lbl.setSizePolicy(
                    QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
                )
                _theme.style_fn(title_lbl, lambda: f"font-size: {_theme.FONT_MD}; color: {_theme.COLOR_TEXT_2}; font-weight: bold;"
                    " padding-left: 8px; padding-top: 4px;")
                target_layout.addWidget(title_lbl)

            for prog in progs[:_MAX_VISIBLE]:
                target_layout.addWidget(_ch_row(prog))

            if len(progs) > _MAX_VISIBLE:
                extra = progs[_MAX_VISIBLE:]
                n_more = len(extra)

                extra_container = QWidget()
                extra_inner = QVBoxLayout(extra_container)
                extra_inner.setContentsMargins(0, 0, 0, 0)
                extra_inner.setSpacing(2)
                for ep in extra:
                    extra_inner.addWidget(_ch_row(ep))
                extra_container.hide()

                expand_btn = QPushButton(f"{self.config.move_down_icon}  {n_more} more channels")
                expand_btn.setFlat(True)
                _theme.style_fn(expand_btn, lambda: f"QPushButton {{ color: {_theme.COLOR_MUTED_2}; font-size: {_theme.FONT_SM}; border: none;"
                    " text-align: left; padding-left: 16px; }"
                    f"QPushButton:hover {{ color: {_theme.COLOR_DIM_2}; }}")

                def _toggle(checked=False, btn=expand_btn, cont=extra_container, n=n_more):
                    if cont.isHidden():
                        cont.show()
                        btn.setText(f"{self.config.move_up_icon}  fewer channels")
                    else:
                        cont.hide()
                        btn.setText(f"{self.config.move_down_icon}  {n} more channels")

                expand_btn.clicked.connect(_toggle)
                target_layout.addWidget(expand_btn)
                target_layout.addWidget(extra_container)

        group_list = list(title_groups.items())
        visible_groups = group_list[:_MAX_GROUPS]
        extra_groups = group_list[_MAX_GROUPS:]

        for title, progs in visible_groups:
            _render_group(title, progs, layout)

        if extra_groups:
            n_extra_grps = len(extra_groups)
            extra_grp_container = QWidget()
            extra_grp_layout = QVBoxLayout(extra_grp_container)
            extra_grp_layout.setContentsMargins(0, 0, 0, 0)
            extra_grp_layout.setSpacing(3)
            for title, progs in extra_groups:
                _render_group(title, progs, extra_grp_layout)
            extra_grp_container.hide()

            more_grps_btn = QPushButton(
                f"{self.config.move_down_icon}  {n_extra_grps} more programs"
            )
            more_grps_btn.setFlat(True)
            _theme.style_fn(more_grps_btn, lambda: f"QPushButton {{ color: {_theme.COLOR_TEXT}; font-size: {_theme.FONT_SM}; border: none;"
                " text-align: left; padding: 2px 8px; }"
                f"QPushButton:hover {{ color: {_theme.COLOR_TEXT}; }}")

            def _toggle_groups(_, btn=more_grps_btn, cont=extra_grp_container, n=n_extra_grps):
                if cont.isHidden():
                    cont.show()
                    btn.setText(f"{self.config.move_up_icon}  fewer programs")
                else:
                    cont.hide()
                    btn.setText(f"{self.config.move_down_icon}  {n} more programs")

            more_grps_btn.clicked.connect(_toggle_groups)
            layout.addWidget(more_grps_btn)
            layout.addWidget(extra_grp_container)

        # ── Separator + upcoming ─────────────────────────────────────────── #
        if is_live and upcoming:
            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            _theme.style(sep, "SEPARATOR_LINE")
            sep.setMaximumHeight(1)
            layout.addWidget(sep)

        # Group upcoming by title (up to 3 title groups, up to 2 channels each).
        # Rank channels within each group (same key as the live groups above) so
        # the [:2] display cap keeps the best surviving streams.
        up_title_groups: dict[str, list] = defaultdict(list)
        for prog in upcoming:
            up_title_groups[prog.title].append(prog)
        for progs in up_title_groups.values():
            progs.sort(key=self._watchlist_rank_key)
        # Sort title groups by earliest start time (independent of the intra-group
        # channel ranking above — use min() rather than index [0], which no longer
        # points at the earliest-start row after the rank sort).
        up_title_groups = dict(
            sorted(
                up_title_groups.items(),
                key=lambda kv: min(p.start_time for p in kv[1]),
            )
        )

        def _up_row(prog):
            """Build one upcoming-row widget using stored detected_* maps.

            Mirrors _ch_row: reads prefix/title/quality/region/year/audio from
            pre-fetched maps — no parse_channel_name() call (ingestion-only rule, CLAUDE.md).
            """
            cid = prog.channel_db_id or ""
            raw_name = self._channel_name_map.get(cid, prog.channel_epg_id)
            category = self._channel_prefix_map.get(cid, "")
            bare_name = self._channel_title_map.get(cid, raw_name)
            region = self._channel_region_map.get(cid, "")
            display_quality = self._channel_quality_map.get(cid, "")
            year = self._channel_year_map.get(cid, "")

            now = _now_utc()
            if prog.start_time <= now:
                time_str = _remaining_str(prog.stop_time)
            else:
                mins = _minutes_away(prog.start_time)
                if mins < 120:
                    time_str = f"in {mins} min"
                elif _is_local_today(prog.start_time):
                    time_str = f"Today {_format_time(prog.start_time)}"
                else:
                    time_str = f"{_local_weekday(prog.start_time)} {_format_time(prog.start_time)}"

            row_w = QWidget()
            cursor_affordance.set_clickable(row_w)
            row_w.mousePressEvent = lambda e, c=prog.channel_db_id: self._emit_channel_selected(c)
            row = QHBoxLayout(row_w)
            row.setContentsMargins(16, 0, 4, 0)
            row.setSpacing(4)
            time_lbl = QLabel(f"{time_str}  ·")
            time_lbl.setFixedWidth(90)
            time_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            _theme.style(time_lbl, "TIME_LABEL_UPCOMING")
            row.addWidget(time_lbl)
            if category:
                row.addWidget(make_region_chip(category, row_w))
            if region:
                row.addWidget(make_region_chip(region, row_w))
            name_lbl = QLabel(bare_name)
            _theme.style(name_lbl, "CHANNEL_NAME_UPCOMING")
            row.addWidget(name_lbl, 1)
            if display_quality:
                row.addWidget(make_quality_chip(display_quality, row_w))
            if year:
                row.addWidget(make_year_chip(year, row_w))
            return row_w

        for title, progs in list(up_title_groups.items())[:3]:
            if title.casefold() != pattern.casefold():
                title_lbl = QLabel(title)
                title_lbl.setWordWrap(True)
                title_lbl.setSizePolicy(
                    QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
                )
                _theme.style_fn(title_lbl, lambda: f"font-size: {_theme.FONT_MD}; color: {_theme.COLOR_TEXT_LOW}; font-style: italic; padding-left: 8px;")
                layout.addWidget(title_lbl)
            for prog in progs[:2]:
                layout.addWidget(_up_row(prog))

        return w

    def _make_quiet_section(self, patterns: list[str]) -> QWidget:
        """Collapsible section for watchlist patterns that have no current or upcoming matches."""
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(0, 4, 0, 0)
        outer.setSpacing(4)

        collapsed = self.config.epg_watchlist_quiet_collapsed
        n = len(patterns)

        toggle_btn = QPushButton()
        toggle_btn.setFlat(True)
        _theme.style_fn(toggle_btn, lambda: f"QPushButton {{ color: {_theme.COLOR_TEXT}; font-size: {_theme.FONT_MD}; border: none;"
            " text-align: left; padding: 2px 4px; }"
            f"QPushButton:hover {{ color: {_theme.COLOR_TEXT}; }}")

        cards_container = QWidget()
        cards_layout = QVBoxLayout(cards_container)
        cards_layout.setContentsMargins(0, 0, 0, 0)
        cards_layout.setSpacing(6)
        for pattern in patterns:
            card = self._make_watchlist_item(pattern, [], [])
            card.setStyleSheet(card.styleSheet() + " opacity: 0.55;")
            cards_layout.addWidget(card)

        def _update_label():
            arrow = self.config.move_down_icon if cards_container.isHidden() else self.config.move_up_icon
            toggle_btn.setText(f"{arrow}  OFF AIR  ·  {n}")

        def _toggle(checked=False):
            if cards_container.isHidden():
                cards_container.show()
                self.config.epg_watchlist_quiet_collapsed = False
            else:
                cards_container.hide()
                self.config.epg_watchlist_quiet_collapsed = True
            self.config.save()
            _update_label()

        toggle_btn.clicked.connect(_toggle)
        outer.addWidget(toggle_btn)
        outer.addWidget(cards_container)

        if collapsed:
            cards_container.hide()
        _update_label()

        return w

    def _make_channel_item(self, channel_db_id: str, channel_name: str,
                           prog: EpgProgramDB | None,
                           state: str = "ok") -> QWidget:
        """The pinned-channel card — built by ``epg_channel_card``.

        Kept as a method because that is what every caller (and the card's own
        tests) reach for; the widget itself lives in its own module, see there.
        """
        from metatv.gui.epg_channel_card import build_pinned_channel_card

        return build_pinned_channel_card(self, channel_db_id, channel_name, prog, state)

    def _make_recommendation_item(self, channel_db_id: str, channel_name: str, count: int) -> QWidget:
        # Outer container holds header row + expandable matches sub-list.
        outer = QWidget()
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        # ── Header row (chips, name, count, buttons) ─────────────────────────
        header_w = QWidget()
        layout = QHBoxLayout(header_w)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(8)

        # Clicking the header row body → details pane
        # (QPushButtons consume their own clicks, so buttons remain independent.)
        cursor_affordance.set_clickable(header_w)
        header_w.mousePressEvent = lambda e, cid=channel_db_id: self._emit_channel_selected(cid)

        display_quality = self._channel_quality_map.get(channel_db_id, "")
        region = self._channel_region_map.get(channel_db_id, "")
        audio_form = self._channel_audio_map.get(channel_db_id, "")
        prefix = self._channel_prefix_map.get(channel_db_id, "")
        bare_name = self._channel_title_map.get(channel_db_id, channel_name)
        year = self._channel_year_map.get(channel_db_id, "")

        if region:
            layout.addWidget(make_region_chip(region, header_w))
        if audio_form:
            layout.addWidget(make_audio_chip(audio_form, header_w))
        if prefix:
            layout.addWidget(make_region_chip(prefix, header_w))
        name_lbl = QLabel(bare_name)
        _theme.style(name_lbl, "DISCOVER_REC_NAME")
        layout.addWidget(name_lbl)
        if display_quality:
            layout.addWidget(make_quality_chip(display_quality, header_w))
        if year:
            layout.addWidget(make_year_chip(year, header_w))

        # Expandable count toggle label
        _collapsed_state = [True]  # mutable cell to capture toggle state in closures

        count_lbl = QLabel(f"{_icons.expand_icon} {count} matches")
        _theme.style(count_lbl, "DISCOVER_REC_COUNT")
        cursor_affordance.set_clickable(count_lbl, keyboard=True)
        layout.addWidget(count_lbl)
        layout.addStretch()

        # + Channel button (pins to My Channels watch list)
        watch_btn = QPushButton("+ Channel")
        watch_btn.setFixedWidth(75)
        _theme.style(watch_btn, "DISCOVER_REC_PILL_BTN")
        watch_btn.setToolTip("Add to My Channels")
        watch_btn.clicked.connect(lambda _=False, cid=channel_db_id: self._watch_channel(cid))
        layout.addWidget(watch_btn)

        # Play button
        play_btn = QPushButton(_icons.play_icon)
        play_btn.setFixedWidth(28)
        _theme.style(play_btn, "DISCOVER_REC_PILL_BTN")
        play_btn.setToolTip("Play this channel")
        play_btn.clicked.connect(lambda _=False, cid=channel_db_id: self._play_channel(cid))
        layout.addWidget(play_btn)

        # Skip / dismiss button
        skip_btn = QPushButton(f"{_icons.close_icon} skip")
        skip_btn.setFixedWidth(55)
        _theme.style(skip_btn, "DISCOVER_REC_SKIP_BTN")
        skip_btn.setToolTip("Dismiss this recommendation for 7 days")
        skip_btn.clicked.connect(lambda _=False, cid=channel_db_id: self._dismiss_channel(cid))
        layout.addWidget(skip_btn)

        outer_layout.addWidget(header_w)

        # ── Expandable matches sub-list (lazy-loaded on first expand) ────────
        sub_list = QWidget()
        sub_list.hide()
        sub_layout = QVBoxLayout(sub_list)
        sub_layout.setContentsMargins(16, 2, 10, 4)
        sub_layout.setSpacing(1)
        outer_layout.addWidget(sub_list)

        _loaded = [False]  # lazy-load flag

        def _toggle_matches(_event=None) -> None:
            if _collapsed_state[0]:
                # Expand
                _collapsed_state[0] = False
                count_lbl.setText(f"{_icons.collapse_icon} {count} matches")
                if not _loaded[0]:
                    _loaded[0] = True
                    self._load_rec_matches(channel_db_id, sub_layout)
                sub_list.show()
            else:
                # Collapse
                _collapsed_state[0] = True
                count_lbl.setText(f"{_icons.expand_icon} {count} matches")
                sub_list.hide()

        count_lbl.mousePressEvent = _toggle_matches

        return outer

    def _load_rec_matches(self, channel_db_id: str, sub_layout: QVBoxLayout) -> None:
        """Fetch and render matching upcoming programmes into the sub-list.

        Runs inline (blocking) — the query is a tiny bounded single-channel
        lookup (limit 10) and is only triggered by an explicit user click.
        """
        from metatv.core.repositories import RepositoryFactory

        patterns = list(watchlist.patterns(self.config))
        provider_ids = self._filtered_provider_ids()

        try:
            with self.db.session_scope(commit=False) as session:
                repos = RepositoryFactory(session)
                rows = repos.epg.get_matching_programs(
                    channel_db_id=channel_db_id,
                    patterns=patterns,
                    provider_ids=provider_ids,
                )
        except Exception as exc:
            logger.warning(f"EpgView: failed to load rec matches for {channel_db_id}: {exc}")
            rows = []

        if not rows:
            lbl = QLabel("No upcoming matches found")
            _theme.style(lbl, "LABEL_MUTED")
            sub_layout.addWidget(lbl)
            return

        for title, start_time in rows:
            # start_time is UTC-naive; _format_time localizes internally (like the
            # _up_row sibling path). Pre-converting to local first double-shifts and
            # skews the displayed time by the UTC offset for non-UTC users.
            time_str = _format_time(start_time)
            row_lbl = QLabel(f"{time_str}  ·  {title}")
            _theme.style(row_lbl, "DISCOVER_REC_MATCH_ROW")
            sub_layout.addWidget(row_lbl)

    def _attach_rule_editor(self, layout, pattern: str, toggle_btn) -> None:
        """Hang the collapsed Option B rule row under a pattern card."""
        from metatv.gui.watch_rule_editor import attach_rule_editor

        attach_rule_editor(self, layout, pattern, toggle_btn)

    def _on_rule_changed(self, pattern: str, rule) -> None:
        """Persist an edited rule, then refresh everything that reads rules."""
        from metatv.gui.watch_rule_editor import apply_rule_change

        apply_rule_change(self, pattern, rule)

    # ── Pattern add/remove + dismiss ───────────────────────────────────

    def _toggle_compose(self) -> None:
        """Show or hide the new-entry form."""
        showing = not self._compose_editor.isVisible()
        self._compose_editor.setVisible(showing)
        caret = _icons.collapse_icon if showing else _icons.expand_icon
        self._new_item_btn.setText(f"{caret}  Track something new")
        if showing:
            self._compose_editor.include_input.setFocus()

    def _close_compose(self) -> None:
        """Hide the form and reset it, so the next open starts clean."""
        from metatv.core.watchlist_matching import WatchRule

        self._compose_editor.set_rule(WatchRule(term=""))
        self._compose_editor.setVisible(False)
        self._new_item_btn.setText(
            f"{_icons.expand_icon}  Track something new")

    def _on_compose_committed(self, rule) -> None:
        """Store a newly composed entry with every field it was given.

        Two writes rather than one: ``add`` creates the row (it is the only
        path that knows how to, and it de-duplicates), then ``update`` puts the
        match settings on it. Folding them into one ``add`` overload would give
        the store two ways to create a row, which is how the two-write bug in
        the first draft of this feature happened.
        """
        if not watchlist.add(self.config, rule.term):
            self._close_compose()
            return
        watchlist.update(
            self.config, rule.term,
            whole_word=rule.whole_word,
            exclude=rule.exclude,
            match_mode=rule.match_mode,
            search_description=rule.search_description,
        )
        self.watchlist_changed.emit()
        self._close_compose()
        self._reload_watchlist()

    def _add_pattern(self, pattern: str) -> None:
        if watchlist.add(self.config, pattern):
            self.watchlist_changed.emit()
            self._reload_watchlist()

    def _remove_pattern(self, pattern: str) -> None:
        if watchlist.remove(self.config, pattern):
            self.watchlist_changed.emit()
            self._reload_watchlist()

    def _dismiss_channel(self, channel_db_id: str) -> None:
        dismiss_until = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        self.config.epg_dismissed_channels[channel_db_id] = dismiss_until
        self.config.save()
        self._reload_watchlist()

    def _dismissed_ids(self) -> set[str]:
        now = _now_utc()
        return {
            cid for cid, ts_str in self.config.epg_dismissed_channels.items()
            if _parse_iso(ts_str) > now
        }

    def _manage_dismissed(self) -> None:
        dlg = _DismissedDialog(self.config, self)
        dlg.exec()
        self._reload_watchlist()
