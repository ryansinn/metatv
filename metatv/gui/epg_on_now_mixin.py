"""Mixin for the EPG View's On-Now tab (Band 10 B10-4 file split).

``_EpgOnNowMixin`` is a plain Python mixin — it does NOT inherit from QWidget.
It is mixed into ``EpgView`` via multiple inheritance and accesses all shared
instance state through ``self`` at runtime (MRO resolution).

Methods moved here (verbatim from ``epg_view.py``):
    _build_on_now_tab
    _reload_on_now
    _fetch_on_now
    _on_now_hidden_prefixes   (staticmethod)
    _render_on_now
    _apply_on_now_filters
    _on_now_item_clicked
    _on_now_context_menu
    _bulk_assign_category
    _remove_category_overrides
    _bulk_hide_channels
    _bulk_hide_titles
    _known_categories
    _track_shows_from_items
    _save_on_now_header_state
    _on_now_double_click
    _on_now_selection_changed

All other helpers these methods call (``self._save_epg_sort``,
``self._filtered_provider_ids``, ``self._play_channel``,
``self._emit_channel_selected``, ``self._host``, ``self._watch_channel``,
``self._unwatch_channel``, ``self._prompt_track``, ``self._show_hide_dialog``,
``self._hide_title``, ``self._hide_channel``, ``self._hide_category``,
``self._reload_on_now`` itself, ``self._render_hidden``,
``self._update_filler_btn_label``, the ``_channel_*_map`` dicts, etc.) remain
in ``EpgView`` and resolve via ``self`` / MRO.
"""

from __future__ import annotations

import re

from PyQt6.QtCore import Qt, QByteArray
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
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

from metatv.core.channel_name_utils import REGION_FULL_NAMES
from metatv.core.database import ChannelDB, EpgProgramDB
from metatv.core.filter_utils import global_exclusion_set, is_channel_excluded
from metatv.core.epg_utils import (
    now_utc as _now_utc,
    remaining_str as _remaining_str,
)
from metatv.gui import theme as _theme
from metatv.gui.channel_menu import ChannelMenuContext, build_channel_menu
from metatv.gui.details_versions import resolve_category_name
from metatv.gui.epg_widgets import (
    _AssignCategoryDialog,
    _EpgTreeItem,
    _PROGRESS_ROLE,
    _REMAIN_ROLE,
    _SORT_ROLE,
    _ProgressBarDelegate,
)


class _EpgOnNowMixin:
    """On-Now-tab methods for EpgView.

    Mixed into ``EpgView`` — all ``self.*`` references resolve via MRO.
    """

    # Regex extracts the prefix from "BE ★ Channel Name", "US| Channel Name",
    # "ARGENTINA ★ ...", "EPL ★ ...", "EFL-L1 ★ ..." — allows hyphens/digits for
    # competition/league codes. Best-effort; not all prefixes are countries.
    _PREFIX_RE = re.compile(
        r'^([A-Z][A-Z0-9\-]{1,11})\s*(?:[★|]|-\s+)\s*(.+)$',
        re.IGNORECASE,
    )

    # Normalize full country names that appear as prefixes → short codes for display
    _COUNTRY_ABBREV: dict[str, str] = {
        "ARGENTINA": "ARG",
        "AUSTRALIA": "AUS",
        "AUSTRIA": "AUT",
        "BELGIUM": "BEL",
        "BOLIVIA": "BOL",
        "BRAZIL": "BRA",
        "CANADA": "CAN",
        "CHILE": "CHL",
        "COLOMBIA": "COL",
        "CROATIA": "HRV",
        "DENMARK": "DEN",
        "ECUADOR": "ECU",
        "FINLAND": "FIN",
        "FRANCE": "FRA",
        "GERMANY": "GER",
        "GREECE": "GRE",
        "HUNGARY": "HUN",
        "IRELAND": "IRL",
        "ITALY": "ITA",
        "MEXICO": "MEX",
        "NETHERLANDS": "NED",
        "NORWAY": "NOR",
        "PARAGUAY": "PAR",
        "PERU": "PER",
        "POLAND": "POL",
        "PORTUGAL": "POR",
        "ROMANIA": "ROU",
        "RUSSIA": "RUS",
        "SPAIN": "ESP",
        "SWEDEN": "SWE",
        "SWITZERLAND": "SUI",
        "TURKEY": "TUR",
        "UKRAINE": "UKR",
        "URUGUAY": "URY",
        "VENEZUELA": "VEN",
    }

    # ── Tab: On Now ────────────────────────────────────────────────────

    def _build_on_now_tab(self) -> None:
        from metatv.gui.filter_bar import FilterDropdown

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        # Filter row: search | region dropdown | → | Hide Hidden
        filter_row = QHBoxLayout()
        filter_row.setSpacing(6)

        self.on_now_search = QLineEdit()
        self.on_now_search.setPlaceholderText("Search On Now…")
        self.on_now_search.setFixedWidth(180)
        self.on_now_search.setClearButtonEnabled(True)
        self.on_now_search.textChanged.connect(self._apply_on_now_filters)
        filter_row.addWidget(self.on_now_search)

        self.on_now_prefix_dropdown = FilterDropdown("Category", {}, all_selected=True)
        self.on_now_prefix_dropdown.filter_changed.connect(self._apply_on_now_filters)
        filter_row.addWidget(self.on_now_prefix_dropdown)

        filter_row.addStretch()

        self.filler_check_btn = QPushButton("Show All")
        self.filler_check_btn.setCheckable(True)
        self.filler_check_btn.setChecked(True)
        self.filler_check_btn.setFixedWidth(110)
        self.filler_check_btn.clicked.connect(self._on_filler_toggled)
        filter_row.addWidget(self.filler_check_btn)

        layout.addLayout(filter_row)

        # Programme tree: Category | Channel | Quality | Show | Progress | [hide]
        # Logical columns: 0=Category(""), 1=Channel, 2=Quality, 3=Show, 4=Progress, 5=Hide
        self.on_now_list = QTreeWidget()
        self.on_now_list.setAlternatingRowColors(True)
        self.on_now_list.setRootIsDecorated(False)
        self.on_now_list.setUniformRowHeights(True)
        self.on_now_list.setSortingEnabled(True)
        self.on_now_list.setColumnCount(6)
        self.on_now_list.setHeaderLabels(["", "Channel", "Quality", "Show", "Progress", "Hide"])
        hdr = self.on_now_list.header()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        hdr.setStretchLastSection(False)
        hdr.setSectionsMovable(True)
        hdr.resizeSection(1, 220)
        self.on_now_list.setColumnWidth(2, 44)
        self.on_now_list.setColumnWidth(4, 64)
        self.on_now_list.setColumnWidth(5, 22)
        self.on_now_list.headerItem().setToolTip(0, "Category / prefix extracted from channel name")
        self.on_now_list.headerItem().setToolTip(2, "Stream quality (4K / FHD / HD / etc.)")
        self.on_now_list.headerItem().setToolTip(4, "Progress through current show (hover for time remaining)")
        self._progress_delegate = _ProgressBarDelegate(self.on_now_list)
        self.on_now_list.setItemDelegateForColumn(4, self._progress_delegate)
        self.on_now_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.on_now_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.on_now_list.customContextMenuRequested.connect(self._on_now_context_menu)
        self.on_now_list.itemDoubleClicked.connect(self._on_now_double_click)
        self.on_now_list.itemClicked.connect(self._on_now_item_clicked)
        self.on_now_list.currentItemChanged.connect(self._on_now_selection_changed)
        # Restore persisted header state (column order + widths) or apply default visual order.
        # Default visual order: [Category(0), Progress(4), Show(3), Channel(1), Hide(5), Quality(2)]
        _saved_header = self.config.epg_filter_state.get("on_now_header_state")
        if _saved_header:
            try:
                hdr.restoreState(QByteArray.fromBase64(_saved_header.encode("ascii")))
                hdr.setStretchLastSection(False)  # re-assert after restoreState
            except Exception:
                _saved_header = None  # fall through to default order
        if not _saved_header:
            # Apply default visual order: logical indices [0, 4, 3, 1, 5, 2]
            # moveSection(from_visual, to_visual) — apply in order to avoid conflicts
            hdr.moveSection(hdr.visualIndex(4), 1)  # Progress → visual 1
            hdr.moveSection(hdr.visualIndex(3), 2)  # Show    → visual 2
            hdr.moveSection(hdr.visualIndex(1), 3)  # Channel → visual 3
            hdr.moveSection(hdr.visualIndex(5), 4)  # Hide    → visual 4
            # Quality ends up at visual 5 (last) naturally
        # Restore persisted sort; save whenever user clicks a header
        _col = self.config.epg_filter_state.get("on_now_sort_col", 0)
        _ord = Qt.SortOrder(self.config.epg_filter_state.get("on_now_sort_order", 0))
        self.on_now_list.sortByColumn(_col, _ord)
        hdr.sortIndicatorChanged.connect(
            lambda col, order: self._save_epg_sort("on_now", col, order)
        )
        hdr.sectionMoved.connect(self._save_on_now_header_state)
        layout.addWidget(self.on_now_list)

        self.on_now_stats = QLabel("")
        self.on_now_stats.setStyleSheet(_theme.LABEL_MUTED)
        layout.addWidget(self.on_now_stats)

        self.stack.addWidget(page)

    def _reload_on_now(self) -> None:
        provider_ids = self._filtered_provider_ids()
        hide_filler = self.filler_check_btn.isChecked()
        # Show loading state immediately so the list isn't blank during the 10–15 s query.
        if self.on_now_list.topLevelItemCount() == 0:
            from PyQt6.QtWidgets import QTreeWidgetItem
            placeholder = QTreeWidgetItem(["", "Loading channels on now…", "", "", "", ""])
            placeholder.setFlags(placeholder.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            placeholder.setForeground(1, QColor(_theme.COLOR_MUTED))
            self.on_now_list.addTopLevelItem(placeholder)
        self.on_now_stats.setText("Loading…")
        self._executor.submit(self._fetch_on_now, provider_ids, hide_filler)

    def _fetch_on_now(self, provider_ids: list[str], hide_filler: bool) -> None:
        if not provider_ids:
            logger.warning("EpgView on-now: no EPG provider IDs — is EPG loaded?")
            self._data_loaded.emit({"tab": "on_now", "programs": []})
            return
        session = self.db.get_session()
        try:
            from metatv.core.repositories import RepositoryFactory
            repos = RepositoryFactory(session)
            excluded_ch_provider_ids = set(repos.providers.get_hidden_provider_ids())
            repo = repos.epg
            filler = self.config.epg_filler_patterns if hide_filler else []
            dismissed = self._dismissed_ids()
            programs = repo.get_current_programs(
                provider_ids=provider_ids,
                hide_filler=hide_filler,
                filler_patterns=filler,
                dismissed_channel_ids=dismissed,
                hidden_titles=list(self.config.epg_hidden_titles or []),
                hidden_channel_ids=list(self.config.epg_hidden_channels or []),
                excluded_channel_provider_ids=excluded_ch_provider_ids,
            )
            logger.debug(f"EpgView on-now: {len(programs)} programmes from providers {provider_ids}")
            # Build name + quality + prefix + title + region + year maps from stored DB fields
            name_map: dict[str, str] = {}
            quality_map: dict[str, str] = {}
            prefix_map: dict[str, str] = {}
            title_map: dict[str, str] = {}
            region_map: dict[str, str] = {}
            year_map: dict[str, str] = {}
            for p in programs:
                if p.channel_db_id and p.channel_db_id not in name_map:
                    ch = session.query(ChannelDB).filter_by(id=p.channel_db_id).first()
                    if ch:
                        name_map[p.channel_db_id] = ch.name
                        if ch.detected_quality:
                            quality_map[p.channel_db_id] = ch.detected_quality.upper()
                        prefix_map[p.channel_db_id] = ch.detected_prefix or ""
                        title_map[p.channel_db_id] = ch.detected_title or ch.name
                        region_map[p.channel_db_id] = ch.detected_region or ""
                        year_map[p.channel_db_id] = ch.detected_year or ""
            self._channel_name_map.update(name_map)
            self._channel_quality_map.update(quality_map)
            self._channel_prefix_map.update(prefix_map)
            self._channel_title_map.update(title_map)
            self._channel_region_map.update(region_map)
            self._channel_year_map.update(year_map)

            self._data_loaded.emit({"tab": "on_now", "programs": programs})
        except Exception as e:
            logger.error(f"EpgView on-now fetch error: {e}")
            self._data_loaded.emit({"tab": "on_now", "programs": []})
        finally:
            session.close()

    @staticmethod
    def _on_now_hidden_prefixes(config) -> tuple[set[str], set[str]]:
        """The two On-Now exclusion layers, kept separate by matching semantics.

        Returns ``(epg_hidden, global_excluded)``:

        - **epg_hidden** — the EPG-specific ``epg_hidden_prefixes`` layer, a
          *prefix-only* membership set (never region), and NOT gated by
          ``global_filter_paused``.
        - **global_excluded** — the user's Global Exclusions, built by the
          canonical :func:`~metatv.core.filter_utils.global_exclusion_set`
          (paused-aware, group→leaf-expanded). The render loop feeds this to
          :func:`~metatv.core.filter_utils.is_channel_excluded` so the same
          "prefix wins, region is the no-prefix fallback" rule the channel list
          uses applies here too (P1-6) — hence the two sets cannot be merged
          into one prefix-membership set anymore.
        """
        epg_hidden = set(config.epg_hidden_prefixes or [])
        return epg_hidden, global_exclusion_set(config)

    def _render_on_now(self, programs: list[EpgProgramDB]) -> None:
        self.on_now_list.setSortingEnabled(False)
        self.on_now_list.clear()
        patterns = [p.lower() for p in self.config.epg_watchlist_patterns]
        epg_hidden, global_excluded = self._on_now_hidden_prefixes(self.config)
        now = _now_utc()
        prefix_counts: dict[str, int] = {}

        for prog in programs:
            ch_name = self._channel_name_map.get(prog.channel_db_id or "", prog.channel_epg_id)
            title = prog.title
            if prog.is_live:
                title += " ᴸᶦᵛᵉ"
            if prog.is_new:
                title += " ᴺᵉʷ"

            override_cat = self.config.epg_category_overrides.get(prog.channel_db_id or "")
            if override_cat:
                category = override_cat
                bare_name = ch_name
            else:
                category = self._channel_prefix_map.get(prog.channel_db_id or "", "")
                bare_name = self._channel_title_map.get(prog.channel_db_id or "", ch_name)

            # Two exclusion layers with different semantics (P1-6): the EPG-specific
            # layer is prefix-only; the global layer applies the shared predicate
            # (prefix wins, region is the no-prefix fallback) so a prefix-less
            # channel from an excluded region is hidden here just like the list.
            if category in epg_hidden:
                continue
            region = self._channel_region_map.get(prog.channel_db_id or "", "")
            if is_channel_excluded(category, region, global_excluded):
                continue

            if category:
                prefix_counts[category] = prefix_counts.get(category, 0) + 1

            # Progress bar data
            total_secs = max(1, (prog.stop_time - prog.start_time).total_seconds())
            elapsed_secs = max(0, (now - prog.start_time).total_seconds())
            pct = int(min(100, elapsed_secs / total_secs * 100))
            remaining_text = _remaining_str(prog.stop_time)
            secs_remaining = max(0.0, (prog.stop_time - now).total_seconds())

            quality = self._channel_quality_map.get(prog.channel_db_id or "", "")
            # Columns: Category | Channel | Quality | Show | Progress bar | 🚫
            item = _EpgTreeItem([category, bare_name, quality, title, "", self.config.hide_icon])
            item.setData(0, Qt.ItemDataRole.UserRole, prog.channel_db_id)
            item.setData(0, Qt.ItemDataRole.UserRole + 1, category)  # store category for dialog
            item.setTextAlignment(2, Qt.AlignmentFlag.AlignCenter)
            item.setData(4, _SORT_ROLE, secs_remaining)
            item.setData(4, _PROGRESS_ROLE, pct)
            item.setData(4, _REMAIN_ROLE, remaining_text)
            item.setToolTip(4, remaining_text)
            item.setData(5, Qt.ItemDataRole.UserRole, prog.title)
            item.setTextAlignment(5, Qt.AlignmentFlag.AlignCenter)
            item.setToolTip(5, "Click to hide…")

            if category:
                item.setToolTip(0, resolve_category_name(category, self.config) or category)

            if any(pat in prog.title.lower() for pat in patterns):
                for col in range(5):
                    item.setForeground(col, QColor(_theme.COLOR_ACCENT_HOVER))
                font = item.font(3)
                font.setBold(True)
                item.setFont(3, font)

            self.on_now_list.addTopLevelItem(item)

        self.on_now_prefix_dropdown.update_groups(prefix_counts)
        self.on_now_list.setSortingEnabled(True)
        self._apply_on_now_filters()
        self._update_filler_btn_label()
        count = self.on_now_list.topLevelItemCount()
        self.on_now_stats.setText(f"{count:,} channels on now")
        self.status_message.emit(f"EPG: {count:,} on now")

    def _apply_on_now_filters(self) -> None:
        """Client-side filter on the On Now tree: search text + region prefix."""
        q = self.on_now_search.text().strip().lower()
        selected = set(self.on_now_prefix_dropdown.get_selected())
        all_prefixes = set(self.on_now_prefix_dropdown.groups.keys())
        filter_prefix = bool(selected) and selected != all_prefixes

        for i in range(self.on_now_list.topLevelItemCount()):
            item = self.on_now_list.topLevelItem(i)
            visible = True

            if q:
                region = item.text(0).lower()
                ch = item.text(1).lower()
                show = item.text(3).lower()
                if q not in region and q not in ch and q not in show:
                    visible = False

            if visible and filter_prefix:
                if item.text(0) not in selected:
                    visible = False

            item.setHidden(not visible)

    def _on_now_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        if column == 5 and len(self.on_now_list.selectedItems()) == 1:
            title = item.data(5, Qt.ItemDataRole.UserRole)
            ch_id = item.data(0, Qt.ItemDataRole.UserRole)
            ch_name = item.text(1)
            category = item.data(0, Qt.ItemDataRole.UserRole + 1) or ""
            if title or ch_id:
                self._show_hide_dialog(title, ch_id, ch_name, category)

    def _on_now_context_menu(self, pos) -> None:
        from metatv.core.repositories import RepositoryFactory

        items = self.on_now_list.selectedItems()
        if not items:
            return

        ch_ids = [i.data(0, Qt.ItemDataRole.UserRole) for i in items]
        valid_ch_ids = [cid for cid in ch_ids if cid]
        is_single = len(items) == 1

        # ── Build context ────────────────────────────────────────────────────
        ctx_kwargs: dict = dict(
            channel_ids=valid_ch_ids or ch_ids,
            surface="epg_on_now",
        )

        if is_single and valid_ch_ids:
            cid = valid_ch_ids[0]
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
            ctx_kwargs["channel_found"] = True

        ctx = ChannelMenuContext(**ctx_kwargs)

        # ── Build handlers ───────────────────────────────────────────────────
        host = self._host()
        handlers: dict = {}

        # Core single-select handlers (only offered for single selection)
        if is_single and valid_ch_ids:
            cid = valid_ch_ids[0]
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

        # EPG-extra handlers
        watched = [cid for cid in valid_ch_ids if cid in self.config.epg_watchlist_channels]
        unwatched = [cid for cid in valid_ch_ids if cid not in self.config.epg_watchlist_channels]
        items_snap = items[:]
        valid_ids_snap = valid_ch_ids[:]

        if unwatched:
            _unwatched_snap = unwatched[:]
            handlers["epg_watch"] = lambda ids=_unwatched_snap: [
                self._watch_channel(c) for c in ids
            ]

        if watched:
            _watched_snap = watched[:]
            handlers["epg_unwatch"] = lambda ids=_watched_snap: [
                self._unwatch_channel(c) for c in ids
            ]

        # Track show — only when there are recognizable show titles
        show_titles = list({
            i.text(3).split(" ᴸᶦᵛᵉ")[0].split(" ᴺᵉʷ")[0].strip() for i in items
        })
        if show_titles:
            handlers["epg_track_show"] = lambda its=items_snap: self._track_shows_from_items(its)

        handlers["epg_assign_category"] = lambda its=items_snap: self._bulk_assign_category(its)

        has_override = any(
            cid in self.config.epg_category_overrides for cid in valid_ch_ids
        )
        if has_override:
            handlers["epg_remove_override"] = lambda ids=valid_ids_snap: (
                self._remove_category_overrides(ids)
            )

        handlers["epg_hide_channel"] = lambda ids=valid_ids_snap: self._bulk_hide_channels(ids)
        handlers["epg_hide_show"] = lambda its=items_snap: self._bulk_hide_titles(its)

        menu = build_channel_menu(ctx, handlers, parent=self)
        menu.exec(self.on_now_list.viewport().mapToGlobal(pos))

    def _bulk_assign_category(self, items: list[QTreeWidgetItem]) -> None:
        dlg = _AssignCategoryDialog(self._known_categories(), self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        code = dlg.category_code()
        if not code:
            return
        overrides = dict(self.config.epg_category_overrides)
        for item in items:
            cid = item.data(0, Qt.ItemDataRole.UserRole)
            if cid:
                overrides[cid] = code
        self.config.epg_category_overrides = overrides
        self.config.save()
        self._reload_on_now()

    def _remove_category_overrides(self, ch_ids: list[str]) -> None:
        overrides = dict(self.config.epg_category_overrides)
        for cid in ch_ids:
            overrides.pop(cid, None)
        self.config.epg_category_overrides = overrides
        self.config.save()
        self._reload_on_now()
        self._render_hidden()

    def _bulk_hide_channels(self, ch_ids: list[str]) -> None:
        hidden = list(self.config.epg_hidden_channels or [])
        for cid in ch_ids:
            if cid and cid not in hidden:
                hidden.append(cid)
        self.config.epg_hidden_channels = hidden
        self.config.save()
        self._reload_on_now()

    def _bulk_hide_titles(self, items: list[QTreeWidgetItem]) -> None:
        hidden = list(self.config.epg_hidden_titles or [])
        for item in items:
            title = item.data(5, Qt.ItemDataRole.UserRole)
            if title and title not in hidden:
                hidden.append(title)
        self.config.epg_hidden_titles = hidden
        self.config.save()
        self._reload_on_now()

    def _known_categories(self) -> list[str]:
        existing = set(self.config.epg_category_overrides.values())
        visible = {
            self.on_now_list.topLevelItem(i).text(0)
            for i in range(self.on_now_list.topLevelItemCount())
            if self.on_now_list.topLevelItem(i).text(0)
        }
        return sorted(existing | visible | set(REGION_FULL_NAMES.keys()))

    def _save_on_now_header_state(self) -> None:
        """Persist On Now column order/widths so they survive restarts."""
        raw = bytes(self.on_now_list.header().saveState().toBase64()).decode("ascii")
        self.config.epg_filter_state["on_now_header_state"] = raw
        self.config.save()

    def _track_shows_from_items(self, items: list[QTreeWidgetItem]) -> None:
        from PyQt6.QtWidgets import QInputDialog
        titles = list({
            i.text(3).split(" ᴸᶦᵛᵉ")[0].split(" ᴺᵉʷ")[0].strip() for i in items
        })
        default = titles[0] if len(titles) == 1 else ""
        text, ok = QInputDialog.getText(
            self, "Track show",
            "Add watchlist pattern — edit to a keyword for broader matching:",
            text=default,
        )
        if ok and text.strip():
            self._add_pattern(text.strip())

    def _on_now_double_click(self, item: QTreeWidgetItem, _col: int) -> None:
        self._play_channel(item.data(0, Qt.ItemDataRole.UserRole))

    def _on_now_selection_changed(self, current, _) -> None:
        if not current:
            return
        self._emit_channel_selected(current.data(0, Qt.ItemDataRole.UserRole))
