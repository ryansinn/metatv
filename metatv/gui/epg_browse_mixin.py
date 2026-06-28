"""Mixin for the EPG View's Browse tab (Band 10 B10-4 file split).

``_EpgBrowseMixin`` is a plain Python mixin — it does NOT inherit from QWidget.
It is mixed into ``EpgView`` via multiple inheritance and accesses all shared
instance state through ``self`` at runtime (MRO resolution).

Methods moved here (verbatim from ``epg_view.py``):
    _build_browse_tab
    _reload_browse
    _fetch_browse
    _render_browse
    _browse_double_click
    _on_browse_context_menu
    _browse_selection_changed

All other helpers these methods call (``self._save_epg_sort``,
``self._filtered_provider_ids``, ``self._on_search_changed``,
``self._prompt_track``, ``self._watch_channel``, ``self._play_channel``,
``self._emit_channel_selected``, ``self._host``, the ``_channel_*_map``
dicts, etc.) remain in ``EpgView`` and resolve via ``self`` / MRO.
"""

from __future__ import annotations

from datetime import date, timedelta

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from loguru import logger

from metatv.core.database import ChannelDB, EpgProgramDB, ProviderDB
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.channel_menu import ChannelMenuContext, build_channel_menu
from metatv.gui.epg_widgets import (
    _EpgTreeItem,
    _SORT_ROLE,
)

from metatv.core.epg_utils import (
    fmt_time as _format_time,
    fmt_duration as _duration_str,
    to_local as _to_local,
)


class _EpgBrowseMixin:
    """Browse-tab methods for EpgView.

    Mixed into ``EpgView`` — all ``self.*`` references resolve via MRO.
    """

    # ── Tab: Browse ────────────────────────────────────────────────────

    def _build_browse_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        # Search row with clear button
        search_row = QHBoxLayout()
        search_row.setSpacing(4)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search programmes…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._on_search_changed)
        search_row.addWidget(self.search_input, 1)
        layout.addLayout(search_row)

        # Filter row
        filter_row = QHBoxLayout()

        self.date_combo = QComboBox()
        self.date_combo.setFixedWidth(110)
        today = date.today()
        for i in range(6):
            d = today + timedelta(days=i)
            label = "Today" if i == 0 else ("Tomorrow" if i == 1 else d.strftime("%a %b %d"))
            self.date_combo.addItem(label, d)
        self.date_combo.currentIndexChanged.connect(self._reload_browse)

        self.time_combo = QComboBox()
        self.time_combo.setFixedWidth(120)
        for label, val in [
            ("All Day", "all"),
            ("Morning 6–12", "morning"),
            ("Afternoon 12–6", "afternoon"),
            ("Prime Time 6–11", "primetime"),
            ("Late Night 11–3", "latenight"),
        ]:
            self.time_combo.addItem(label, val)
        self.time_combo.currentIndexChanged.connect(self._reload_browse)

        self.hide_filler_btn = QPushButton("Hide Filler ✓")
        self.hide_filler_btn.setCheckable(True)
        self.hide_filler_btn.setChecked(self.config.epg_hide_filler)
        self.hide_filler_btn.setFixedWidth(100)
        self.hide_filler_btn.clicked.connect(self._reload_browse)

        filter_row.addWidget(self.date_combo)
        filter_row.addWidget(self.time_combo)
        filter_row.addStretch()
        filter_row.addWidget(self.hide_filler_btn)
        layout.addLayout(filter_row)

        # Programme tree: Time | Channel | Show | Duration
        self.browse_list = QTreeWidget()
        self.browse_list.setAlternatingRowColors(True)
        self.browse_list.setRootIsDecorated(False)
        self.browse_list.setUniformRowHeights(True)
        self.browse_list.setSortingEnabled(True)
        self.browse_list.setColumnCount(4)
        self.browse_list.setHeaderLabels(["Time", "Channel", "Show", "Duration"])
        hdr = self.browse_list.header()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.browse_list.itemDoubleClicked.connect(self._browse_double_click)
        self.browse_list.currentItemChanged.connect(self._browse_selection_changed)
        self.browse_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.browse_list.customContextMenuRequested.connect(self._on_browse_context_menu)
        # Restore persisted sort
        _bcol = self.config.epg_filter_state.get("browse_sort_col", 0)
        _bord = Qt.SortOrder(self.config.epg_filter_state.get("browse_sort_order", 0))
        self.browse_list.sortByColumn(_bcol, _bord)
        self.browse_list.header().sortIndicatorChanged.connect(
            lambda col, order: self._save_epg_sort("browse", col, order)
        )
        self.browse_list.setVisible(False)
        layout.addWidget(self.browse_list)

        self.browse_placeholder = QLabel("Search for a programme, sport, or show above")
        self.browse_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.browse_placeholder.setStyleSheet(f"color: {_theme.COLOR_FAINT}; font-size: {_theme.FONT_XL}; padding: 40px;")
        layout.addWidget(self.browse_placeholder)

        self.browse_stats = QLabel("")
        self.browse_stats.setStyleSheet(_theme.LABEL_MUTED)
        layout.addWidget(self.browse_stats)

        self.stack.addWidget(page)

    def _reload_browse(self) -> None:
        # Browse is a date/time-driven schedule browser. An empty search shows the
        # full schedule for the selected day + time slot (get_schedule); a non-empty
        # search narrows to matching upcoming programmes (search_programs). Both
        # branches live in _fetch_browse — never early-return on an empty search, or
        # the schedule view (the tab's primary function) is dead and only text search
        # works (regression introduced in dd576bf).
        #
        # ``search`` is captured up-front and threaded through the fetch → payload so
        # the main-thread render can drop STALE async results (flagged 454e01bf): a
        # slow empty-search full-schedule fetch must not land after a newer keystroke
        # and revert Browse to ALL content. The render guard re-applies the active
        # search box on every refresh.
        search = self.search_input.text().strip()
        provider_ids = self._filtered_provider_ids()
        if not provider_ids:
            # No EPG sources configured/active → nothing to browse. Surface the
            # placeholder rather than firing a query that can only return empty.
            self._data_loaded.emit(
                {"tab": "browse", "programs": [], "placeholder": True, "search": search}
            )
            return
        target_date = self.date_combo.currentData()
        time_slot = self.time_combo.currentData()
        hide_filler = self.hide_filler_btn.isChecked()
        self._executor.submit(
            self._fetch_browse, provider_ids, target_date, time_slot, search, hide_filler
        )

    def _fetch_browse(self, provider_ids: list[str], target_date: date,
                      time_slot: str, search: str, hide_filler: bool) -> None:
        from metatv.core.repositories import RepositoryFactory

        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            repo = repos.epg
            # Scope Browse to visible sources exactly like On Now: exclude channels
            # belonging to hidden providers (inactive ∪ expired ∪ orphaned) so the
            # global Exclusions are honoured (active-source scoping, DR-0007).
            excluded_ch_provider_ids = set(repos.providers.get_hidden_provider_ids())
            filler = self.config.epg_filler_patterns if hide_filler else []

            if search:
                programs = repo.search_programs(
                    search, provider_ids, hours_ahead=168,
                    excluded_channel_provider_ids=excluded_ch_provider_ids,
                )
            else:
                programs = repo.get_schedule(
                    target_date=target_date,
                    provider_ids=provider_ids,
                    hide_filler=hide_filler,
                    filler_patterns=filler,
                    time_slot=time_slot,
                    excluded_channel_provider_ids=excluded_ch_provider_ids,
                )

            # Fetch the shallowest epg_data_end among the active providers so the empty
            # state can tell the user exactly how far the guide actually reaches.
            rows = (
                session.query(ProviderDB.epg_data_end)
                .filter(ProviderDB.id.in_(provider_ids))
                .filter(ProviderDB.epg_data_end.isnot(None))
                .all()
            )
            guide_end = min((r.epg_data_end for r in rows), default=None)

            # Build channel display maps from stored detected_* fields (computed at
            # ingestion). Render reads the clean detected_title — never parse_channel_name
            # at render time (CLAUDE.md: channel-name fields computed at ingestion).
            name_map: dict[str, str] = {}
            title_map: dict[str, str] = {}
            for p in programs:
                cid = p.channel_db_id
                if cid and cid not in name_map:
                    ch = session.query(ChannelDB).filter_by(id=cid).first()
                    if ch:
                        name_map[cid] = ch.name
                        title_map[cid] = ch.detected_title or ch.name
            self._channel_name_map.update(name_map)
            self._channel_title_map.update(title_map)

            self._data_loaded.emit({
                "tab": "browse",
                "programs": programs,
                "guide_end": guide_end,
                "search": search,
            })
        except Exception as e:
            logger.error(f"EpgView browse fetch error: {e}")
        finally:
            session.close()

    def _render_browse(self, programs: list[EpgProgramDB], placeholder: bool = False,
                       guide_end=None) -> None:
        if placeholder or not programs:
            # No data (no EPG sources, or the selected day/slot/search has no
            # programmes) → show the placeholder instead of an empty tree.
            self.browse_list.setVisible(False)
            self.browse_placeholder.setText(self._browse_placeholder_text(guide_end=guide_end))
            self.browse_placeholder.setVisible(True)
            self.browse_stats.clear()
            self.status_message.emit("EPG: 0 programmes")
            return
        self.browse_placeholder.setVisible(False)
        self.browse_list.setVisible(True)
        self.browse_list.setSortingEnabled(False)
        self.browse_list.clear()
        patterns = [p.lower() for p in self.config.epg_watchlist_patterns]

        for prog in programs:
            cid = prog.channel_db_id or ""
            # Show the clean detected_title (prefix/quality/region stripped at
            # ingestion); fall back to the raw name, then the EPG channel id
            # (flagged 8f941952).
            ch_name = (
                self._channel_title_map.get(cid)
                or self._channel_name_map.get(cid)
                or prog.channel_epg_id
            )
            time_str = _format_time(prog.start_time)
            dur = _duration_str(prog.start_time, prog.stop_time)
            title = prog.title
            if prog.is_live:
                title += " ᴸᶦᵛᵉ"
            if prog.is_new:
                title += " ᴺᵉʷ"

            item = _EpgTreeItem([time_str, ch_name, title, dur])
            item.setData(0, Qt.ItemDataRole.UserRole, prog.channel_db_id)
            item.setData(0, _SORT_ROLE, prog.start_time.timestamp())

            if any(pat in prog.title.lower() for pat in patterns):
                for col in range(4):
                    item.setForeground(col, QColor(_theme.COLOR_ACCENT_HOVER))
                font = item.font(2)
                font.setBold(True)
                item.setFont(2, font)

            self.browse_list.addTopLevelItem(item)

        self.browse_list.setSortingEnabled(True)
        count = len(programs)
        self.browse_stats.setText(f"{count:,} programmes")
        self.status_message.emit(f"EPG: {count:,} programmes")

    def _browse_placeholder_text(self, guide_end=None) -> str:
        """Context-aware empty-state message for the Browse tab.

        When the selected day/time window has no programmes but guide_end is known
        (from the provider's stored epg_data_end), the message tells the user exactly
        how far the guide actually reaches, so an empty prime-time slot reads as
        "guide only goes to <date/time>" rather than a blank list that looks like a bug.
        """
        if not self._filtered_provider_ids():
            return "No EPG sources — enable a source's guide to browse the schedule."
        if self.search_input.text().strip():
            return "No programmes match your search."
        if guide_end is not None:
            local_end = _to_local(guide_end)
            end_str = local_end.strftime("%a %b %-d at %-I:%M %p")
            return f"No programmes scheduled in this window — this source's guide currently reaches {end_str}."
        return "No programmes for the selected day and time."

    def _browse_double_click(self, item: QTreeWidgetItem, _col: int) -> None:
        self._play_channel(item.data(0, Qt.ItemDataRole.UserRole))

    def _on_browse_context_menu(self, pos) -> None:
        from metatv.core.repositories import RepositoryFactory

        item = self.browse_list.itemAt(pos)
        if not item:
            return

        title = item.text(2).split(" ᴸᶦᵛᵉ")[0].split(" ᴺᵉʷ")[0].strip()
        cid = item.data(0, Qt.ItemDataRole.UserRole)

        # ── Build context ────────────────────────────────────────────────────
        ctx_kwargs: dict = dict(
            channel_ids=[cid] if cid else [],
            surface="epg_browse",
        )

        if cid:
            with self.db.session_scope(commit=False) as session:
                repos = RepositoryFactory(session)
                ch = repos.channels.get_by_id(cid)
                if ch:
                    ctx_kwargs.update(
                        media_type=ch.media_type or "",
                        is_favorite=ch.is_favorite or False,
                        in_queue=repos.queue.is_queued(cid),
                        rating=repos.ratings.get(cid) or 0,
                        is_hidden=ch.is_hidden or False,
                        channel_name=ch.name or "",
                        channel_found=True,
                    )
                else:
                    ctx_kwargs["channel_found"] = False
        else:
            ctx_kwargs["channel_found"] = False

        ctx = ChannelMenuContext(**ctx_kwargs)

        # ── Build handlers ───────────────────────────────────────────────────
        host = self._host()
        handlers: dict = {}

        if cid and ctx.channel_found:
            is_fav = ctx.is_favorite

            def _play_h(c=cid):
                if hasattr(host, "play_channel_by_id"):
                    host.play_channel_by_id(c)
                else:
                    self._play_channel(c)

            def _play_new_h(c=cid):
                if hasattr(host, "play_channel_new_window_by_id"):
                    host.play_channel_new_window_by_id(c)

            def _fav_h(c=cid, f=is_fav):
                if hasattr(host, "_toggle_favorite_by_id"):
                    host._toggle_favorite_by_id(c, not f)

            def _queue_h(c=cid, iq=ctx.in_queue):
                if hasattr(host, "_add_to_queue") and hasattr(host, "_remove_from_queue"):
                    if iq:
                        host._remove_from_queue(c)
                    else:
                        host._add_to_queue(c)

            handlers["play"] = _play_h
            handlers["play_new_window"] = _play_new_h
            handlers["favorite"] = _fav_h
            handlers["queue"] = _queue_h

            if ctx.media_type in ("movie", "series"):
                def _like_h(c=cid):
                    if hasattr(host, "_toggle_rating"):
                        host._toggle_rating(c, 1)

                def _dislike_h(c=cid):
                    if hasattr(host, "_toggle_rating"):
                        host._toggle_rating(c, -1)

                handlers["like"] = _like_h
                handlers["dislike"] = _dislike_h

            # epg_watch: only when not already watched
            if cid not in self.config.epg_watchlist_channels:
                handlers["epg_watch"] = lambda c=cid: self._watch_channel(c)

        # epg_track_show is always offered when there's a title
        if title:
            handlers["epg_track_show"] = lambda t=title: self._prompt_track(t)

        menu = build_channel_menu(ctx, handlers, parent=self)
        menu.exec(self.browse_list.viewport().mapToGlobal(pos))

    def _browse_selection_changed(self, current, _) -> None:
        if not current:
            return
        self._emit_channel_selected(current.data(0, Qt.ItemDataRole.UserRole))
