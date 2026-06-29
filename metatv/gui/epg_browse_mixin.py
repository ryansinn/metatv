"""Mixin for the EPG View's Browse tab (Band 10 B10-4 file split).

``_EpgBrowseMixin`` is a plain Python mixin — it does NOT inherit from QWidget.
It is mixed into ``EpgView`` via multiple inheritance and accesses all shared
instance state through ``self`` at runtime (MRO resolution).

Browse is **forward-looking** (Phase 1): instead of a calendar-day × bounded
time-slot picker it offers a single *start anchor* (Now / Tonight / Tomorrow / …)
and lists programmes chronologically forward from there — never the past — paged
in via keyset pagination as the user scrolls. The Phase-2 timeline scrubber will
reuse the same forward repository query (``EpgRepository.get_schedule_forward``).

Methods here:
    _build_browse_tab
    _refresh_browse_anchors
    _reload_browse
    _load_more_browse
    _on_browse_scroll
    _fetch_browse
    _render_browse
    _browse_placeholder_text
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

from datetime import timedelta

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from loguru import logger

from metatv.core.database import ChannelDB, EpgProgramDB
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.channel_menu import ChannelMenuContext, build_channel_menu
from metatv.gui.epg_widgets import (
    _EpgTreeItem,
    _SORT_ROLE,
)

from metatv.core.epg_utils import (
    browse_anchors as _browse_anchors,
    fmt_time as _format_time,
    fmt_duration as _duration_str,
    to_local as _to_local,
    now_utc as _now_utc,
    scrubber_bounds as _scrubber_bounds,
    scrubber_time_for as _scrubber_time_for,
    scrubber_value_for as _scrubber_value_for,
    scrubber_label as _scrubber_label,
)

# Forward-list page size — one keyset page fetched per scroll-to-bottom.
_BROWSE_PAGE_SIZE = 200

# Per-item role storing the programme's UTC-naive start_time datetime — read by the
# scroll→handle sync to map the topmost visible row back to a scrubber position.
# (_SORT/_PROGRESS/_REMAIN use UserRole +2/+3/+4 in epg_widgets; +5 is distinct.)
_START_ROLE = int(Qt.ItemDataRole.UserRole) + 5


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

        # Forward-list pagination state.
        self._browse_cursor: tuple | None = None   # keyset (start_time, id) of last row
        self._browse_exhausted: bool = True         # no more pages to fetch
        self._browse_loading: bool = False          # a fetch is in flight
        self._browse_gen: int = 0                   # reload generation (drops stale async pages)

        # Timeline-scrubber (Phase 2) state. The slider value is in increment units;
        # _scrubber_left/right are the track's UTC-naive bounds (sized from the scoped
        # guide bounds on each fresh load). _scrubber_syncing guards the seek↔scroll
        # feedback loop: any PROGRAMMATIC setValue (scroll-driven sync, combo jump,
        # bounds reconfigure) sets it True so valueChanged never fires a seek back.
        self._scrubber_left: "datetime | None" = None
        self._scrubber_right: "datetime | None" = None
        self._scrubber_increment: int = 30
        self._scrubber_ready: bool = False          # bounds configured at least once
        self._scrubber_syncing: bool = False        # True ⇒ a programmatic setValue
        self._last_seek_value: int | None = None    # de-dup repeated seeks to same step

        # Search row with clear button
        search_row = QHBoxLayout()
        search_row.setSpacing(4)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search programmes…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._on_search_changed)
        search_row.addWidget(self.search_input, 1)
        layout.addLayout(search_row)

        # Filter row — a single forward START-ANCHOR combo (replaces the old
        # calendar-day + bounded time-slot pair). Selecting an anchor sets where the
        # forward list begins; it then runs chronologically until data runs out.
        filter_row = QHBoxLayout()

        anchor_label = QLabel("Starting:")
        anchor_label.setStyleSheet(_theme.LABEL_MUTED)
        filter_row.addWidget(anchor_label)

        self.anchor_combo = QComboBox()
        self.anchor_combo.setMinimumWidth(180)
        self.anchor_combo.setToolTip(
            "Start browsing the guide forward from this point in time. "
            "The list runs chronologically and never shows the past."
        )
        self._refresh_browse_anchors()
        # The anchor combo is now a set of quick-jumps that MOVE the scrubber handle
        # (and seek there) — it stays as a fast way to leap to Now/Tonight/Tomorrow.
        self.anchor_combo.currentIndexChanged.connect(self._on_anchor_selected)

        self.hide_filler_btn = QPushButton("Hide Filler ✓")
        self.hide_filler_btn.setCheckable(True)
        self.hide_filler_btn.setChecked(self.config.epg_hide_filler)
        self.hide_filler_btn.setFixedWidth(100)
        self.hide_filler_btn.setToolTip("Hide placeholder / off-air filler programmes.")
        self.hide_filler_btn.clicked.connect(self._reload_browse)

        filter_row.addWidget(self.anchor_combo)
        filter_row.addStretch()
        filter_row.addWidget(self.hide_filler_btn)
        layout.addLayout(filter_row)

        # ── Timeline scrubber (Phase 2) ─────────────────────────────────────
        # A horizontal handle across the guide's time range, two-way synced to the
        # list: drag → seek the list to that time; scroll → the handle tracks the
        # topmost visible programme. Snap granularity is config-driven (15/30/60).
        scrubber_row = QHBoxLayout()
        scrubber_row.setSpacing(8)
        self._scrubber_left_label = QLabel("")
        self._scrubber_left_label.setStyleSheet(_theme.LABEL_MUTED)
        scrubber_row.addWidget(self._scrubber_left_label)

        self._browse_scrubber = QSlider(Qt.Orientation.Horizontal)
        self._browse_scrubber.setEnabled(False)  # enabled once bounds are known
        self._browse_scrubber.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._browse_scrubber.setToolTip(
            "Scrub the guide timeline — drag to seek the schedule to a point in time. "
            "Scrolling the list moves the handle; dragging snaps to your chosen interval."
        )
        self._browse_scrubber.valueChanged.connect(self._on_scrubber_value_changed)
        self._browse_scrubber.sliderReleased.connect(self._scrubber_seek)
        scrubber_row.addWidget(self._browse_scrubber, 1)

        self._scrubber_right_label = QLabel("")
        self._scrubber_right_label.setStyleSheet(_theme.LABEL_MUTED)
        scrubber_row.addWidget(self._scrubber_right_label)
        layout.addLayout(scrubber_row)

        # Current-handle position label (updates live while dragging).
        self._scrubber_pos_label = QLabel("")
        self._scrubber_pos_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scrubber_pos_label.setStyleSheet(_theme.EPG_SCRUBBER_POS)
        layout.addWidget(self._scrubber_pos_label)

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
        # Lazy-load the next chronological page when scrolled near the bottom.
        self.browse_list.verticalScrollBar().valueChanged.connect(self._on_browse_scroll)
        # Restore persisted sort
        _bcol = self.config.epg_filter_state.get("browse_sort_col", 0)
        _bord = Qt.SortOrder(self.config.epg_filter_state.get("browse_sort_order", 0))
        self.browse_list.sortByColumn(_bcol, _bord)
        self.browse_list.header().sortIndicatorChanged.connect(
            lambda col, order: self._save_epg_sort("browse", col, order)
        )
        self.browse_list.setVisible(False)
        layout.addWidget(self.browse_list)

        self.browse_placeholder = QLabel("Loading the upcoming schedule…")
        self.browse_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.browse_placeholder.setStyleSheet(f"color: {_theme.COLOR_FAINT}; font-size: {_theme.FONT_XL}; padding: 40px;")
        layout.addWidget(self.browse_placeholder)

        self.browse_stats = QLabel("")
        self.browse_stats.setStyleSheet(_theme.LABEL_MUTED)
        layout.addWidget(self.browse_stats)

        self.stack.addWidget(page)

    def _refresh_browse_anchors(self) -> None:
        """(Re)populate the start-anchor combo with freshly-resolved local times.

        Called at build and again on each activation so "Now"/"Tonight"/"Tomorrow"
        resolve against the current clock (the resolved local time shows in each
        label). The current selection index is preserved. Signals are blocked so a
        rebuild never triggers a spurious reload.
        """
        prev = self.anchor_combo.currentIndex() if self.anchor_combo.count() else 0
        self.anchor_combo.blockSignals(True)
        self.anchor_combo.clear()
        for label, anchor in _browse_anchors():
            self.anchor_combo.addItem(label, anchor)
        if 0 <= prev < self.anchor_combo.count():
            self.anchor_combo.setCurrentIndex(prev)
        self.anchor_combo.blockSignals(False)

    def _reload_browse(self) -> None:
        # Forward-looking schedule browser. A fresh reload (anchor change, search
        # keystroke, or filler toggle) restarts the chronological list from page 1.
        #
        # ``search`` is captured up-front and threaded through the fetch → payload so
        # the main-thread render can drop STALE async results: a slow page must not
        # land after a newer keystroke and revert Browse. The render guard re-applies
        # the active search box AND a per-reload generation token on every refresh.
        search = self.search_input.text().strip()
        # New generation → any in-flight page (e.g. a slow "load more" for a prior
        # anchor/search) is dropped on arrival; reset the keyset cursor to page 1.
        self._browse_gen = getattr(self, "_browse_gen", 0) + 1
        gen = self._browse_gen
        self._browse_cursor = None
        self._browse_exhausted = False
        self._browse_loading = True

        provider_ids = self._filtered_provider_ids()
        if not provider_ids:
            # No EPG sources configured/active → nothing to browse. Surface the
            # placeholder rather than firing a query that can only return empty.
            self._browse_loading = False
            self._browse_exhausted = True
            self._data_loaded.emit({
                "tab": "browse", "programs": [], "placeholder": True,
                "search": search, "append": False, "gen": gen,
                "cursor": None, "exhausted": True,
            })
            return

        anchor = self._scrubber_anchor()
        hide_filler = self.hide_filler_btn.isChecked()
        self._executor.submit(
            self._fetch_browse, provider_ids, anchor, search, hide_filler, None, False, gen
        )

    def _load_more_browse(self) -> None:
        """Fetch + append the next chronological page using the keyset cursor."""
        if getattr(self, "_browse_loading", False) or getattr(self, "_browse_exhausted", True):
            return
        cursor = getattr(self, "_browse_cursor", None)
        if cursor is None:
            return
        provider_ids = self._filtered_provider_ids()
        if not provider_ids:
            return
        self._browse_loading = True
        gen = getattr(self, "_browse_gen", 0)
        search = self.search_input.text().strip()
        anchor = self._scrubber_anchor()
        hide_filler = self.hide_filler_btn.isChecked()
        self._executor.submit(
            self._fetch_browse, provider_ids, anchor, search, hide_filler, cursor, True, gen
        )

    def _on_browse_scroll(self, _value: int = 0) -> None:
        """Trigger the next page when scrolled near the bottom; sync the scrubber.

        Scroll → handle: the scrubber tracks the topmost visible programme's start
        time (mapped through the snap helpers). This runs on every scroll, including
        the scrollbar reset after a fresh load, and is feedback-loop safe — the
        programmatic ``setValue`` is wrapped in the ``_scrubber_syncing`` guard so it
        can never bounce back into a seek.
        """
        self._sync_scrubber_to_scroll()
        if getattr(self, "_browse_loading", False) or getattr(self, "_browse_exhausted", True):
            return
        sb = self.browse_list.verticalScrollBar()
        maximum = sb.maximum()
        if maximum <= 0:
            return
        # "Near bottom": within ~1.5 viewport-pages of the end (or already at it).
        threshold = max(maximum - sb.pageStep() * 3 // 2, 0)
        if sb.value() >= threshold:
            self._load_more_browse()

    # ── Timeline scrubber (Phase 2) ────────────────────────────────────────

    def _scrubber_anchor(self):
        """The anchor (UTC-naive) for the next fetch — the scrubber handle's time.

        Falls back to the anchor combo's data before the scrubber has been sized
        (first load) or in lightweight unit hosts without a scrubber, so the Phase-1
        reload path stays valid.
        """
        scrubber = getattr(self, "_browse_scrubber", None)
        if scrubber is None or not getattr(self, "_scrubber_ready", False):
            return self.anchor_combo.currentData()
        return _scrubber_time_for(
            self._scrubber_left, scrubber.value(), self._scrubber_increment
        )

    def _configure_scrubber(self, guide_bounds, oldest_airing_start=None) -> None:
        """Size the scrubber track from the scoped guide bounds (main thread).

        Called from the browse data-loaded dispatch on a fresh (non-append) page.
        Re-reads the snap increment from config each time so a Settings change takes
        effect on the next load. The current handle TIME is preserved across a
        re-size (the track rarely changes), defaulting to "now" on first configure.

        ``oldest_airing_start`` (start of the oldest currently-airing show, from the
        same fresh page) is the track's DEFAULT left edge — so the timeline reaches
        back to the beginning of everything on right now, but no further by default.
        """
        if getattr(self, "_browse_scrubber", None) is None:
            return
        min_start, max_start = guide_bounds or (None, None)
        now = _now_utc()

        # Resolve the handle's current TIME using the OLD bounds/increment BEFORE they
        # are overwritten — so a re-size (or a Settings snap change) never yanks the
        # handle. Defaults to NOW on first open / on view re-activation (reset flag).
        reset = getattr(self, "_scrubber_reset_to_now", False)
        keep = (
            getattr(self, "_scrubber_ready", False)
            and self._scrubber_left is not None
            and not reset
        )
        prev_time = (
            _scrubber_time_for(self._scrubber_left, self._browse_scrubber.value(),
                               self._scrubber_increment)
            if keep else now
        )
        self._scrubber_reset_to_now = False

        self._scrubber_increment = (
            getattr(self.config, "epg_scrubber_increment_minutes", 30) or 30
        )
        inc = self._scrubber_increment
        left, right = _scrubber_bounds(
            min_start, max_start,
            getattr(self.config, "epg_browse_hide_older_than_hours", 0) or 0,
            oldest_airing_start=oldest_airing_start,
            _now=now,
        )

        self._scrubber_left = left
        self._scrubber_right = right
        steps = max(1, _scrubber_value_for(left, right, inc))
        value = min(max(_scrubber_value_for(left, prev_time, inc), 0), steps)

        self._scrubber_syncing = True
        self._browse_scrubber.setRange(0, steps)
        self._browse_scrubber.setTickInterval(max(1, round(24 * 60 / inc)))  # day marks
        self._browse_scrubber.setValue(value)
        self._browse_scrubber.setEnabled(min_start is not None)
        self._scrubber_syncing = False

        self._scrubber_ready = True
        self._last_seek_value = value
        self._update_scrubber_labels()

    def _set_scrubber_time(self, dt) -> None:
        """Move the handle to a datetime PROGRAMMATICALLY (no seek), e.g. combo jump."""
        if getattr(self, "_browse_scrubber", None) is None or not self._scrubber_ready:
            return
        value = _scrubber_value_for(self._scrubber_left, dt, self._scrubber_increment)
        value = min(max(value, self._browse_scrubber.minimum()),
                    self._browse_scrubber.maximum())
        self._scrubber_syncing = True
        self._browse_scrubber.setValue(value)
        self._scrubber_syncing = False
        self._last_seek_value = value
        self._update_scrubber_labels()

    def _on_anchor_selected(self) -> None:
        """Anchor combo changed → jump the handle to that time, then seek there."""
        anchor = self.anchor_combo.currentData()
        if anchor is not None and getattr(self, "_scrubber_ready", False):
            self._set_scrubber_time(anchor)
        self._reload_browse()

    def _on_scrubber_value_changed(self, _value: int = 0) -> None:
        """Slider value changed — refresh the live label; seek unless it's a sync.

        Mid-drag (``isSliderDown``) we only update the label and defer the seek to
        ``sliderReleased``; a PROGRAMMATIC change (``_scrubber_syncing``) never seeks
        — that is the feedback-loop guard for scroll-driven / combo / re-size moves.
        Keyboard and page-click changes (not down, not syncing) seek immediately.
        """
        self._update_scrubber_labels()
        if getattr(self, "_scrubber_syncing", False):
            return
        if self._browse_scrubber.isSliderDown():
            return
        self._scrubber_seek()

    def _scrubber_seek(self) -> None:
        """Reload the list anchored at the handle's (snapped) time. De-duped."""
        if not getattr(self, "_scrubber_ready", False):
            return
        value = self._browse_scrubber.value()
        if value == getattr(self, "_last_seek_value", None):
            return
        self._last_seek_value = value
        self._reload_browse()

    def _sync_scrubber_to_scroll(self) -> None:
        """Move the handle to the topmost visible programme's time (no seek)."""
        if not getattr(self, "_scrubber_ready", False):
            return
        scrubber = getattr(self, "_browse_scrubber", None)
        if scrubber is None or self._scrubber_left is None:
            return
        item = self.browse_list.itemAt(2, 2)  # top-left of the viewport
        if item is None:
            return
        start = item.data(0, _START_ROLE)
        if start is None:
            return
        value = _scrubber_value_for(self._scrubber_left, start, self._scrubber_increment)
        value = min(max(value, scrubber.minimum()), scrubber.maximum())
        if value == scrubber.value():
            return
        self._scrubber_syncing = True
        scrubber.setValue(value)
        self._scrubber_syncing = False
        # The list now reflects this position; record it so a release here is a no-op.
        self._last_seek_value = value
        self._update_scrubber_labels()

    def _update_scrubber_labels(self) -> None:
        """Refresh the live position label + the two end labels (local day-context)."""
        if getattr(self, "_scrubber_pos_label", None) is None:
            return
        if not getattr(self, "_scrubber_ready", False) or self._scrubber_left is None:
            return
        now = _now_utc()
        current = _scrubber_time_for(
            self._scrubber_left, self._browse_scrubber.value(), self._scrubber_increment
        )
        self._scrubber_pos_label.setText(_scrubber_label(current, _now=now))
        self._scrubber_left_label.setText(_scrubber_label(self._scrubber_left, _now=now))
        self._scrubber_right_label.setText(_scrubber_label(self._scrubber_right, _now=now))

    def _fetch_browse(self, provider_ids: list[str], anchor, search: str,
                      hide_filler: bool, after, append: bool, gen: int) -> None:
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
            hours = getattr(self.config, "epg_browse_hide_older_than_hours", 0) or 0
            max_age = timedelta(hours=hours) if hours > 0 else None

            # Chronological, keyset-paginated. Inclusion is stop_time > anchor so the
            # "now" anchor lists currently-airing shows (mid-progress) plus upcoming.
            # With a configured "Allow browsing back" window (max_age) the scrubber may
            # seek BACK into the bounded recent past (floor_to_now=False); with hours==0
            # a past anchor floors to now (currently-airing + upcoming, no earlier).
            # Search narrows within either.
            programs = repo.get_schedule_forward(
                provider_ids=provider_ids,
                anchor=anchor,
                search_query=search,
                hide_filler=hide_filler,
                filler_patterns=filler,
                excluded_channel_provider_ids=excluded_ch_provider_ids,
                after=after,
                limit=_BROWSE_PAGE_SIZE,
                max_age=max_age,
                floor_to_now=(max_age is None),
            )

            # Honest coverage for the empty-state (first page only): the LAST
            # CONTIGUOUS programme the scoped sources actually carry from now (stops
            # at the first hole) — NOT the inflated max stop_time anywhere.
            guide_end = None
            guide_bounds = None
            oldest_airing = None
            if not append:
                guide_end = repo.get_contiguous_guide_end(
                    provider_ids,
                    excluded_channel_provider_ids=excluded_ch_provider_ids,
                )
                # Scoped (min_start, max_start) → sizes the scrubber track. Computed
                # on the first page only so a "load more" never resizes the track.
                guide_bounds = repo.get_guide_bounds(
                    provider_ids,
                    excluded_channel_provider_ids=excluded_ch_provider_ids,
                )
                # Start of the oldest currently-airing show → the scrubber's DEFAULT
                # left bound (reach back to the beginning of everything on now).
                oldest_airing = repo.get_oldest_airing_start(
                    provider_ids,
                    excluded_channel_provider_ids=excluded_ch_provider_ids,
                )

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

            # Keyset cursor = last (start_time, id) of this page; a short page (fewer
            # than the requested limit) means the forward timeline is exhausted.
            cursor = (programs[-1].start_time, programs[-1].id) if programs else after
            exhausted = len(programs) < _BROWSE_PAGE_SIZE

            self._data_loaded.emit({
                "tab": "browse",
                "programs": programs,
                "guide_end": guide_end,
                "guide_bounds": guide_bounds,
                "oldest_airing_start": oldest_airing,
                "search": search,
                "append": append,
                "gen": gen,
                "cursor": cursor,
                "exhausted": exhausted,
            })
        except Exception as e:
            logger.error(f"EpgView browse fetch error: {e}")
            self._browse_loading = False
        finally:
            session.close()

    def _render_browse(self, programs: list[EpgProgramDB], placeholder: bool = False,
                       guide_end=None, append: bool = False) -> None:
        if not append and (placeholder or not programs):
            # No data (no EPG sources, or nothing upcoming from the anchor/search) →
            # show the placeholder instead of an empty tree.
            self.browse_list.setVisible(False)
            self.browse_placeholder.setText(self._browse_placeholder_text(guide_end=guide_end))
            self.browse_placeholder.setVisible(True)
            self.browse_stats.clear()
            self.status_message.emit("EPG: 0 programmes")
            return
        self.browse_placeholder.setVisible(False)
        self.browse_list.setVisible(True)
        self.browse_list.setSortingEnabled(False)
        if not append:
            # Fresh load replaces the list; a "load more" page appends to it.
            self.browse_list.clear()
        patterns = [p.lower() for p in self.config.epg_watchlist_patterns]

        for prog in programs:
            cid = prog.channel_db_id or ""
            # Show the clean detected_title (prefix/quality/region stripped at
            # ingestion); fall back to the raw name, then the EPG channel id.
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
            # Raw UTC-naive start_time for the scroll→scrubber-handle mapping.
            item.setData(0, _START_ROLE, prog.start_time)

            if any(pat in prog.title.lower() for pat in patterns):
                for col in range(4):
                    item.setForeground(col, QColor(_theme.COLOR_ACCENT_HOVER))
                font = item.font(2)
                font.setBold(True)
                item.setFont(2, font)

            self.browse_list.addTopLevelItem(item)

        self.browse_list.setSortingEnabled(True)
        count = self.browse_list.topLevelItemCount()
        more = "" if getattr(self, "_browse_exhausted", True) else "+"
        self.browse_stats.setText(f"{count:,}{more} programmes")
        self.status_message.emit(f"EPG: {count:,} programmes")

    def _browse_placeholder_text(self, guide_end=None) -> str:
        """Context-aware empty-state message for the forward-looking Browse tab.

        When nothing is upcoming from the chosen anchor but guide_end is known, the
        message reports exactly how far the guide actually reaches (the last
        contiguous programme) so an empty list reads as "guide only goes to
        <date/time>" rather than a blank list that looks like a bug.
        """
        if not self._filtered_provider_ids():
            return "No EPG sources — enable a source's guide to browse the schedule."
        if self.search_input.text().strip():
            return "No upcoming programmes match your search."
        if guide_end is not None:
            local_end = _to_local(guide_end)
            end_str = local_end.strftime("%a %b %-d at %-I:%M %p")
            return f"No more programmes from here — this source's guide currently reaches {end_str}."
        return "No upcoming programmes in the guide."

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
