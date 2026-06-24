"""Faceted filter panel — resizable vertical sidebar inside the channel list area.

Sections (Language OR Region OR Platform grows the pool; Quality filters it):
  Media     — Live / Movies / Series
  Language  — language groups + locale sub-groups
  Region    — geographic hierarchy: group → individual prefix codes
  Platform  — individual streaming brands
  Quality   — resolution/encoding tiers  (AND/restrictive)
  Genre     — canonical genre names (Movies / Series only)
  Unknown   — channels with no detectable region/language or quality tag

All sections persist their collapsed/expanded state and selection state to config.
Panel width persists via the QSplitter in main_window.
"""

from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMenu, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)
from loguru import logger

from metatv.gui import theme as _theme
from metatv.gui.filter_group_row import _ACCENT, _fmt, _TriCheckbox, _ItemRow, _GroupRow, _Section


# ── Main FilterPanel ───────────────────────────────────────────────────────────

class FilterPanel(QWidget):
    """Vertical faceted filter panel — lives in a QSplitter left of the channel list."""

    filter_changed = pyqtSignal()
    settings_requested = pyqtSignal()

    # Section keys in display order.
    # "category" (live-channel kind: Sports/News/Kids…) sits between quality and
    # genre — both are content descriptors; category is the live-channel variant.
    # subtitle/dub/format sit after genre — audio presentation axis.
    _SECTION_KEYS = ["media", "language", "region", "platform",
                     "quality", "category", "genre", "subtitle", "dub",
                     "format", "untagged"]

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._restoring = False
        # Set True at the END of the first update_data() call.  Until then, dynamic
        # sections (Language, Region, Platform, Quality, Genre) have no items, so
        # save_state() must NOT overwrite their persisted config values with an empty
        # list.  Static sections (Media, Untagged) are populated in __init__ and are
        # always safe to save.
        self._stats_loaded = False

        self.setMinimumWidth(160)
        self.setMaximumWidth(400)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(f"background: {_theme.COLOR_BG_SECTION};")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Panel header
        ph = QWidget()
        ph.setStyleSheet(f"background: {_theme.COLOR_BG_DEEP};")
        ph.setFixedHeight(36)
        phl = QHBoxLayout(ph)
        phl.setContentsMargins(10, 0, 8, 0)
        filters_lbl = QLabel("Includes:")
        filters_lbl.setStyleSheet(
            f"font-size: {_theme.FONT_XL}; font-weight: bold; color: {_theme.COLOR_TEXT_2};")
        phl.addWidget(filters_lbl)
        phl.addStretch()

        all_btn = QPushButton("All")
        all_btn.setFixedHeight(22)
        all_btn.setStyleSheet(_theme.PANEL_BTN)
        all_btn.setToolTip("Select all — show everything, no filter active")
        all_btn.clicked.connect(self.select_all_sections)
        phl.addWidget(all_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.setFixedHeight(22)
        clear_btn.setStyleSheet(_theme.PANEL_BTN)
        clear_btn.setToolTip("Clear all — uncheck everything, then pick exactly what to include")
        clear_btn.clicked.connect(self.clear_all)
        phl.addWidget(clear_btn)

        outer.addWidget(ph)

        # Scrollable sections
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"""
            QScrollArea {{ border:none; background:{_theme.COLOR_BG_SECTION}; }}
            QScrollBar:vertical {{ background:{_theme.COLOR_BG_BAR}; width:6px; border-radius:3px; }}
            QScrollBar::handle:vertical {{ background:{_theme.COLOR_BORDER}; border-radius:3px; }}
        """)

        sc = QWidget()
        sc.setStyleSheet(f"background:{_theme.COLOR_BG_SECTION};")
        self._sl = QVBoxLayout(sc)
        self._sl.setContentsMargins(0, 0, 0, 0)
        self._sl.setSpacing(0)

        # Read saved collapse states
        saved_states: dict = getattr(self.config, 'filter_section_states', {})

        def _expanded(key: str, default: bool) -> bool:
            return saved_states.get(key, default)

        _ii = self.config.info_icon

        # Build sections
        self._media_sec = _Section(
            "media", "Media",
            initially_expanded=_expanded("media", True),
            info_text="Filter by content type. Uncheck a type to hide all channels of that kind.",
            info_icon=_ii, config=self.config)
        self._media_sec.set_flat_items([
            ("live",   "Live",   0),
            ("movie",  "Movies", 0),
            ("series", "Series", 0),
        ])
        self._media_sec.changed.connect(self._on_changed)
        self._sl.addWidget(self._media_sec)
        self._add_divider()

        self._lang_sec = _Section(
            "language", "Language",
            initially_expanded=_expanded("language", False),
            info_text=(
                "Show channels by language or locale prefix (e.g. EN, FR, DE).\n"
                "Language, Region, and Platform work as a union — "
                "checking more always expands results, never shrinks them."
            ),
            info_icon=_ii, config=self.config)
        self._lang_sec.changed.connect(self._on_changed)
        self._sl.addWidget(self._lang_sec)
        self._add_divider()

        self._region_sec = _Section(
            "region", "Region",
            initially_expanded=_expanded("region", False),
            info_text=(
                "Show channels by geographic region code (e.g. US, CA, MX).\n"
                "Works together with Language and Platform as a union — "
                "checking more always adds to results."
            ),
            info_icon=_ii, config=self.config)
        self._region_sec.changed.connect(self._on_changed)
        self._sl.addWidget(self._region_sec)
        self._add_divider()

        self._platform_sec = _Section(
            "platform", "Platform",
            initially_expanded=_expanded("platform", False),
            info_text=(
                "Show channels from specific streaming platforms (e.g. Netflix, EAR, Disney+).\n"
                "Works together with Language and Region as a union — "
                "checking more always adds to results."
            ),
            info_icon=_ii, config=self.config)
        self._platform_sec.changed.connect(self._on_changed)
        self._sl.addWidget(self._platform_sec)
        self._add_divider()

        self._quality_sec = _Section(
            "quality", "Quality", and_axis=True,
            initially_expanded=_expanded("quality", False),
            info_text=(
                "Filter by video quality tier.\n\n"
                "Unlike other sections, this works differently: unchecking a tier "
                "hides channels explicitly tagged with that quality. "
                "Channels with no quality information are always shown."
            ),
            info_icon=_ii, config=self.config)
        self._quality_sec.changed.connect(self._on_changed)
        self._sl.addWidget(self._quality_sec)
        self._add_divider()

        self._category_sec = _Section(
            "category", "Category",
            initially_expanded=_expanded("category", False),
            info_text=(
                "Filter live channels by programming kind (e.g. Sports, News, Kids).\n\n"
                "Check kinds to include — live channels of any checked kind are shown. "
                "Live channels with no category data are always included.\n"
                "Only applies to Live channels; movies and series are unaffected."
            ),
            info_icon=_ii, config=self.config)
        self._category_sec.changed.connect(self._on_changed)
        self._sl.addWidget(self._category_sec)
        self._add_divider()

        self._genre_sec = _Section(
            "genre", "Genre",
            initially_expanded=_expanded("genre", False),
            info_text=(
                "Filter movies and series by genre.\n\n"
                "Check genres to include — channels of any checked genre are shown. "
                "Channels with no genre data are always included.\n"
                "Only applies to Movies and Series; live channels are unaffected."
            ),
            info_icon=_ii, config=self.config)
        self._genre_sec.changed.connect(self._on_changed)
        self._sl.addWidget(self._genre_sec)
        self._add_divider()

        self._subtitle_sec = _Section(
            "subtitle", "Subtitle Language",
            initially_expanded=_expanded("subtitle", False),
            info_text=(
                "Filter by subtitle language detected in the channel name.\n\n"
                "Multi = channel offers subtitles in multiple languages."
            ),
            info_icon=_ii, config=self.config)
        self._subtitle_sec.changed.connect(self._on_changed)
        self._sl.addWidget(self._subtitle_sec)
        self._add_divider()

        self._dub_sec = _Section(
            "dub", "Dub Language",
            initially_expanded=_expanded("dub", False),
            info_text=(
                "Filter by dub (dubbed audio) language detected in the channel name."
            ),
            info_icon=_ii, config=self.config)
        self._dub_sec.changed.connect(self._on_changed)
        self._sl.addWidget(self._dub_sec)
        self._add_divider()

        self._format_sec = _Section(
            "format", "Audio Format",
            initially_expanded=_expanded("format", False),
            info_text=(
                "Filter by audio presentation format detected in the channel name.\n\n"
                "Dub = dubbed audio track. Original = original-language audio with "
                "subtitles. Multi = multiple subtitle languages. Dual = two audio tracks."
            ),
            info_icon=_ii, config=self.config)
        self._format_sec.changed.connect(self._on_changed)
        self._sl.addWidget(self._format_sec)
        self._add_divider()

        self._untagged_sec = _Section(
            "untagged", "Unknown",
            initially_expanded=_expanded("untagged", True),
            info_text=(
                "Channels where no identifying information could be detected at all "
                "(not even an unrecognised prefix).\n\n"
                "Region / Language: channels with no language or region prefix.\n"
                "Playback Quality: channels with no quality marker.\n\n"
                "Uncheck either to hide that group from results."
            ),
            info_icon=_ii, config=self.config)
        self._untagged_sec.set_flat_items([
            ("no_prefix",  "Region / Language",  0),
            ("no_quality", "Playback Quality",   0),
        ])
        self._untagged_sec.changed.connect(self._on_changed)
        self._sl.addWidget(self._untagged_sec)

        self._sl.addStretch()
        scroll.setWidget(sc)
        outer.addWidget(scroll, 1)

        # Wire right-click and "Only" button signals from all sections
        for sec in self._all_sections():
            sec.item_right_clicked.connect(self._on_item_right_clicked)
            sec.item_only_requested.connect(self._on_item_only_requested)
            # collapse_toggled saves state but does NOT emit filter_changed
            sec.collapse_toggled.connect(self._on_collapse_toggled)

        self.restore_state()

    # ── public API ──────────────────────────────────────────────────────────

    def update_data(self, tag_counts: dict[str, dict[str, int]]):
        """Populate dynamic sections from ``TagRepository.get_facet_value_counts()``.

        ``tag_counts`` is a nested dict ``{facet_type: {value: channel_count}}``
        returned by the tag-facet stats query.  Recognised facet types:
        ``language``, ``region``, ``platform``, ``quality``, ``genre``.

        On first call (startup), the in-memory ``prev`` selections are all empty
        because the items don't exist yet when ``restore_state()`` runs at init.
        In that case we fall back to the persisted config selections so that saved
        filter choices survive a restart.  On subsequent calls (e.g. after a source
        refresh) we preserve the user's current in-memory selection instead.

        After the first call completes, emits ``filter_changed`` so that
        ``MainWindow.on_filter_changed`` re-runs ``load_channels()`` with the
        now-restored dynamic filters applied.  Subsequent calls (source refresh)
        do NOT emit — the list is already reflecting the live in-memory selection.
        """
        # Capture whether this is the first call BEFORE any state is modified.
        was_first = not self._stats_loaded

        # Build the startup fallback: config_attr → persisted set of keys.
        # Uses the same (config_attr, section) mapping as restore_state() so there
        # is exactly one place that knows the attr names.
        # None means "never configured" → leave section at all-selected default.
        # [] means "explicitly none" → restore to none-selected.
        _persisted_raw: dict[object, list | None] = {
            sec: getattr(self.config, attr, None)
            for attr, sec in self._persisted_section_attrs()
        }

        def _restore(sec: object, prev: set[str]) -> None:
            """Apply selection: in-memory prev if present, else persisted startup value.

            Sentinel semantics for the persisted value:
              None → never configured; skip (leave section at all-selected default).
              []   → explicitly none; call restore_selection(set()) → uncheck all.
              [..] → restore those specific keys.
            """
            if prev:
                sec.restore_selection(prev)
            else:
                saved = _persisted_raw.get(sec)
                if saved is not None:
                    sec.restore_selection(set(saved))

        # ── Media — static items (no change needed)

        # ── Language — tag values are group names (e.g. "English", "French")
        lang_values: dict[str, int] = tag_counts.get('language', {})
        lang_items = sorted(
            [(k, k, v) for k, v in lang_values.items() if v > 0],
            key=lambda x: (-x[2], x[1]),
        )
        prev_lang = set(self._lang_sec.get_selected_keys())
        self._lang_sec.set_flat_items(lang_items)
        _restore(self._lang_sec, prev_lang)

        # ── Region — tag values are individual ISO codes (e.g. "US", "CA").
        # Display hierarchically using config.filter_regional_groups: each group is a
        # parent, and children are only the ISO codes present in the tag counts.
        region_values: dict[str, int] = tag_counts.get('region', {})
        regional_groups = self.config.filter_regional_groups
        # Build reverse lookup: ISO code (uppercased) → group name(s)
        code_to_groups: dict[str, list[str]] = {}
        for group_name, codes in regional_groups.items():
            for code in codes:
                code_to_groups.setdefault(code.upper(), []).append(group_name)
        # Accumulate group totals from tag counts
        group_totals: dict[str, int] = {}
        for code, cnt in region_values.items():
            for grp in code_to_groups.get(code.upper(), []):
                group_totals[grp] = group_totals.get(grp, 0) + cnt
        # Build region_data for set_grouped_items
        region_data: list[tuple[str, int, list[tuple[str, str, int]]]] = []
        for group_name in sorted(regional_groups.keys()):
            total = group_totals.get(group_name, 0)
            if total == 0:
                continue
            children: list[tuple[str, str, int]] = [
                (code, self._region_label(code), region_values.get(code, 0))
                for code in regional_groups[group_name]
                if region_values.get(code, 0) > 0
            ]
            children.sort(key=lambda x: -x[2])
            if children:
                region_data.append((group_name, total, children))
        prev_region = set(self._region_sec.get_selected_keys())
        self._region_sec.set_grouped_items(region_data)
        _restore(self._region_sec, prev_region)

        # ── Platform — tag values are group names (e.g. "Netflix", "Disney+")
        platform_values: dict[str, int] = tag_counts.get('platform', {})
        plat_items = sorted(
            [(k, k, v) for k, v in platform_values.items() if v > 0],
            key=lambda x: (-x[2], x[1]),
        )
        prev_plat = set(self._platform_sec.get_selected_keys())
        self._platform_sec.set_flat_items(plat_items)
        _restore(self._platform_sec, prev_plat)

        # ── Quality — tag values are group names (e.g. "HD", "4K / UHD"); fixed display order
        quality_order = ["RAW", "4K / UHD", "HD", "HQ", "SD", "LQ",
                         "CAM / Pre-release"]
        quality_values: dict[str, int] = tag_counts.get('quality', {})
        qual_items = [
            (n, n, quality_values[n]) for n in quality_order
            if n in quality_values and quality_values[n] > 0
        ]
        for n, v in quality_values.items():
            if n not in quality_order and v > 0:
                qual_items.append((n, n, v))
        prev_qual = set(self._quality_sec.get_selected_keys())
        self._quality_sec.set_flat_items(qual_items)
        _restore(self._quality_sec, prev_qual)

        # ── Category — tag values are live-channel kinds (e.g. "Sports", "News")
        category_values: dict[str, int] = tag_counts.get('category', {})
        category_items = sorted(
            [(k, k, v) for k, v in category_values.items() if v > 0],
            key=lambda x: (-x[2], x[1]),
        )
        prev_category = set(self._category_sec.get_selected_keys())
        self._category_sec.set_flat_items(category_items)
        if prev_category:
            self._category_sec.restore_selection(prev_category)
        else:
            persisted_category = _persisted_raw.get(self._category_sec)
            if persisted_category is not None:
                self._category_sec.restore_selection(set(persisted_category))
            else:
                # Fresh install / no saved selection (None): show everything
                self._category_sec.select_all()

        # ── Genre — tag values are canonical genre names (e.g. "Drama")
        genre_values: dict[str, int] = tag_counts.get('genre', {})
        genre_items = sorted(
            [(g, g, c) for g, c in genre_values.items() if c > 0],
            key=lambda x: (-x[2], x[1]),
        )
        prev_genre = set(self._genre_sec.get_selected_keys())
        self._genre_sec.set_flat_items(genre_items)
        if prev_genre:
            self._genre_sec.restore_selection(prev_genre)
        else:
            persisted_genre = _persisted_raw.get(self._genre_sec)
            if persisted_genre is not None:
                # Startup: apply saved genre selection ([] = none, [..] = subset)
                self._genre_sec.restore_selection(set(persisted_genre))
            else:
                # Fresh install / no saved selection (None): show everything
                self._genre_sec.select_all()

        # ── Subtitle language
        subtitle_values: dict[str, int] = tag_counts.get('subtitle', {})
        subtitle_items = sorted(
            [(k, k, v) for k, v in subtitle_values.items() if v > 0],
            key=lambda x: (-x[2], x[1]),
        )
        prev_subtitle = set(self._subtitle_sec.get_selected_keys())
        self._subtitle_sec.set_flat_items(subtitle_items)
        _restore(self._subtitle_sec, prev_subtitle)

        # ── Dub language
        dub_values: dict[str, int] = tag_counts.get('dub', {})
        dub_items = sorted(
            [(k, k, v) for k, v in dub_values.items() if v > 0],
            key=lambda x: (-x[2], x[1]),
        )
        prev_dub = set(self._dub_sec.get_selected_keys())
        self._dub_sec.set_flat_items(dub_items)
        _restore(self._dub_sec, prev_dub)

        # ── Audio format
        format_order = ["Dub", "Original", "Multi", "Dual"]
        format_values: dict[str, int] = tag_counts.get('format', {})
        format_items = [
            (n, n, format_values[n]) for n in format_order
            if n in format_values and format_values[n] > 0
        ]
        for n, v in format_values.items():
            if n not in format_order and v > 0:
                format_items.append((n, n, v))
        prev_format = set(self._format_sec.get_selected_keys())
        self._format_sec.set_flat_items(format_items)
        _restore(self._format_sec, prev_format)

        # ── Untagged — static items (no count source in tag model; counts stay at 0).
        # This section controls whether channels with NO prefix/quality tag pass through
        # the filter. It remains functional even without accurate counts.
        prev_untagged = set(self._untagged_sec.get_selected_keys())
        self._untagged_sec.set_flat_items([
            ("no_prefix",  "Region / Language", 0),
            ("no_quality", "Playback Quality",  0),
        ])
        if prev_untagged:
            self._untagged_sec.restore_selection(prev_untagged)
        else:
            # Startup: restore persisted untagged selection (default both on)
            saved_untagged = set(
                getattr(self.config, 'filter_untagged_selected',
                        ['no_prefix', 'no_quality']) or ['no_prefix', 'no_quality']
            )
            self._untagged_sec.restore_selection(saved_untagged)

        # Dynamic sections are now populated — safe for save_state() to persist them.
        self._stats_loaded = True

        logger.debug(
            f"FilterPanel updated (tag model): {len(lang_items)} languages, "
            f"{len(region_data)} region groups, {len(plat_items)} platforms, "
            f"{len(qual_items)} quality tiers, {len(category_items)} categories, "
            f"{len(genre_items)} genres, {len(subtitle_items)} subtitle langs, "
            f"{len(dub_items)} dub langs, {len(format_items)} audio formats"
        )

        # On the very first call the channel list was loaded before dynamic
        # sections were populated (restore_search_state fires load_channels while
        # Language/Region/etc. are still empty).  Emit filter_changed now so the
        # main-window handler re-runs load_channels with the restored filters.
        # Subsequent calls (source refresh) must NOT re-emit — the list already
        # reflects the live in-memory selection and a spurious reload would discard
        # any context-filter chip the user had active.
        if was_first:
            self.filter_changed.emit()

    def get_filter_state(self) -> dict:
        """Return resolved filter state for main_window.load_channels().

        Tag-model (Slice B): sections are now driven by tag facet values.  The
        resolved state includes a ``tag_includes`` dict — one entry per constrained
        facet — that ``_query_channels`` passes directly to
        ``ChannelRepository.get_all(tag_includes=…)``.

        A facet is *unconstrained* (= show all values) when its section is
        all-selected or has no items.  Unconstrained facets are omitted from
        ``tag_includes`` so the EXISTS subquery is not generated and no channels
        are excluded on that axis.

        Cross-axis expansion is no longer needed: each facet is an independent
        AND axis — selecting Language=English AND Platform=Disney+ returns only
        channels that carry *both* tags (intersection), which is the correct
        behaviour.  The old expansion was required to work around the OR-pool
        identity model; it is deleted here.
        """
        media_sel = set(self._media_sec.get_selected_keys())
        media_all = {"live", "movie", "series"}
        media_types = list(media_sel) if media_sel != media_all else list(media_all)

        untagged_selected = set(self._untagged_sec.get_selected_keys())
        include_untagged         = "no_prefix"  in untagged_selected
        include_untagged_quality = "no_quality" in untagged_selected

        # ── Build tag_includes: {facet_type: set(selected_values)} ──────────────
        # Facet is constrained only when NOT all items are selected AND the section
        # has items (empty section = no data for that facet → no constraint).
        tag_includes: dict[str, set[str]] = {}

        # Language facet
        if not self._lang_sec.is_all_selected() and self._lang_sec.get_all_keys():
            selected = set(self._lang_sec.get_selected_keys())
            if selected:
                tag_includes["language"] = selected

        # Region facet — selected keys are individual ISO codes (leaf-level)
        if not self._region_sec.is_all_selected() and self._region_sec.get_all_keys():
            selected = set(self._region_sec.get_selected_keys())
            if selected:
                tag_includes["region"] = selected

        # Platform facet
        if not self._platform_sec.is_all_selected() and self._platform_sec.get_all_keys():
            selected = set(self._platform_sec.get_selected_keys())
            if selected:
                tag_includes["platform"] = selected

        # Quality facet
        if not self._quality_sec.is_all_selected() and self._quality_sec.get_all_keys():
            selected = set(self._quality_sec.get_selected_keys())
            if selected:
                tag_includes["quality"] = selected

        # Category facet (live-channel kinds: Sports, News, Kids…)
        if not self._category_sec.is_all_selected() and self._category_sec.get_all_keys():
            selected = set(self._category_sec.get_selected_keys())
            if selected:
                tag_includes["category"] = selected

        # Genre facet
        genre_all = self._genre_sec.is_all_selected()
        genre_filters = None if genre_all else self._genre_sec.get_selected_keys()
        if not genre_all and self._genre_sec.get_all_keys():
            selected = set(self._genre_sec.get_selected_keys())
            if selected:
                tag_includes["genre"] = selected

        # Subtitle language facet
        if not self._subtitle_sec.is_all_selected() and self._subtitle_sec.get_all_keys():
            selected = set(self._subtitle_sec.get_selected_keys())
            if selected:
                tag_includes["subtitle"] = selected

        # Dub language facet
        if not self._dub_sec.is_all_selected() and self._dub_sec.get_all_keys():
            selected = set(self._dub_sec.get_selected_keys())
            if selected:
                tag_includes["dub"] = selected

        # Audio format facet
        if not self._format_sec.is_all_selected() and self._format_sec.get_all_keys():
            selected = set(self._format_sec.get_selected_keys())
            if selected:
                tag_includes["format"] = selected

        return {
            'media_types':        media_types,
            'language_groups':    self._lang_sec.get_selected_keys(),
            'region_groups':      self._region_sec.get_selected_keys(),
            'quality_groups':     self._quality_sec.get_selected_keys(),
            'platform_groups':    self._platform_sec.get_selected_keys(),
            'category_filters':   self._category_sec.get_selected_keys(),
            'genre_filters':      self._genre_sec.get_selected_keys(),
            'subtitle_filters':   self._subtitle_sec.get_selected_keys(),
            'dub_filters':        self._dub_sec.get_selected_keys(),
            'format_filters':     self._format_sec.get_selected_keys(),
            'include_untagged':          include_untagged,
            'include_untagged_quality':  include_untagged_quality,
            'adult_mode':         getattr(self.config, 'filter_adult_mode', 'hide'),
            'excluded_provider_ids': [],
            # Tag-facet includes — used by _query_channels → get_all(tag_includes=…).
            # None means no tag filter active (all channels pass on this axis).
            'tag_includes': tag_includes or None,
            # Legacy prefix fields — kept so the old fallback path in load_channels
            # (no filter_panel) still has these keys; they are now always None when
            # routing through the tag model.
            '_language_prefixes': None,
            '_region_prefixes':   None,
            '_platform_prefixes': None,
            '_quality_prefixes':  None,
            '_genre_filters':     genre_filters,
        }

    def select_all_sections(self):
        """Check everything — show all content, no active filter."""
        self._restoring = True
        try:
            for sec in self._all_sections():
                sec.select_all()
        finally:
            self._restoring = False
        self.save_state()
        self.filter_changed.emit()

    def clear_all(self):
        """Uncheck everything — start from scratch to select exactly what to include."""
        self._restoring = True
        try:
            for sec in self._all_sections():
                sec.select_none()
        finally:
            self._restoring = False
        self.save_state()
        self.filter_changed.emit()

    def select_only_group(self, item_key: str, section_key: str) -> None:
        """Panel-wide "Only" action — clear all sections, then select one group.

        Clears every group in EVERY facet section (calls select_none on all),
        then selects only the target group in its section, then emits
        filter_changed exactly once.  This is the back-end of the per-row
        "Only" button added in filter_group_row.py.
        """
        self._restoring = True
        try:
            for sec in self._all_sections():
                sec.select_none()
            for sec in self._all_sections():
                if sec.section_key() == section_key:
                    sec.select_only_group(item_key)
                    break
        finally:
            self._restoring = False
        self.save_state()
        self.filter_changed.emit()

    def select_only_genre(self, genre: str) -> None:
        """Filter to a single genre — called when the user clicks a genre chip in the details pane.

        Uses check_only() which emits changed → _on_changed → filter_changed,
        so load_channels() fires automatically.
        """
        self._genre_sec.check_only(genre)

    def save_state(self):
        try:
            state = self.get_filter_state()

            # Dynamic sections (Language/Region/Quality/Platform/Genre) have no items
            # between __init__ and the first update_data() call.  Writing empty lists
            # to config here would clobber a persisted subset before update_data() can
            # restore it — the exact bug this guard prevents.  Static sections (Media,
            # Untagged) are always safe to save because they are populated in __init__.
            if self._stats_loaded:
                self.config.filter_included_languages   = state['language_groups']
                self.config.filter_included_regions     = state['region_groups']
                self.config.filter_included_qualities   = state['quality_groups']
                self.config.filter_included_platforms   = state['platform_groups']
                self.config.filter_included_categories  = state['category_filters']
                self.config.filter_included_genres      = state['genre_filters']
                self.config.filter_included_subtitles   = state['subtitle_filters']
                self.config.filter_included_dubs        = state['dub_filters']
                self.config.filter_included_formats     = state['format_filters']
            self.config.filter_adult_mode = state['adult_mode']

            # Save per-section collapse states
            self.config.filter_section_states = {
                sec.section_key(): sec.is_expanded()
                for sec in self._all_sections()
            }
            # Save media selection and untagged toggles
            self.config.filter_enabled_media_types = state['media_types']
            self.config.filter_untagged_selected = self._untagged_sec.get_selected_keys()
            self.config.save()
        except Exception as e:
            logger.warning(f"Could not save filter panel state: {e}")

    def restore_state(self):
        self._restoring = True
        try:
            for attr, sec in self._persisted_section_attrs():
                saved = getattr(self.config, attr, None)
                # None = never configured → skip (leave at all-selected default).
                # [] = explicitly none → restore_selection(set()) unchecks all.
                if saved is not None:
                    sec.restore_selection(set(saved))

            # Restore media chips
            enabled = getattr(self.config, 'filter_enabled_media_types',
                              ['live', 'movie', 'series']) or ['live', 'movie', 'series']
            self._media_sec.restore_selection(set(enabled))

            # Restore untagged catchall toggles (default both checked)
            saved_untagged = getattr(self.config, 'filter_untagged_selected',
                                     ['no_prefix', 'no_quality'])
            if saved_untagged is not None:
                self._untagged_sec.restore_selection(set(saved_untagged))

        except Exception as e:
            logger.warning(f"Could not restore filter panel state: {e}")
        finally:
            self._restoring = False

    # ── private ─────────────────────────────────────────────────────────────

    def _all_sections(self) -> list[_Section]:
        return [self._media_sec, self._lang_sec, self._region_sec,
                self._platform_sec, self._quality_sec, self._category_sec,
                self._genre_sec, self._subtitle_sec, self._dub_sec,
                self._format_sec, self._untagged_sec]

    def _persisted_section_attrs(self) -> list[tuple[str, object]]:
        """Return (config_attr_name, section) pairs for all dynamic sections.

        Single source of truth for the config-key → section mapping, shared by
        ``restore_state`` (startup) and ``update_data`` (startup fallback path).
        """
        return [
            ('filter_included_languages',  self._lang_sec),
            ('filter_included_regions',    self._region_sec),
            ('filter_included_qualities',  self._quality_sec),
            ('filter_included_platforms',  self._platform_sec),
            ('filter_included_categories', self._category_sec),
            ('filter_included_genres',     self._genre_sec),
            ('filter_included_subtitles',  self._subtitle_sec),
            ('filter_included_dubs',       self._dub_sec),
            ('filter_included_formats',    self._format_sec),
        ]

    def _add_divider(self):
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet(f"background:{_theme.COLOR_LINE_DARK}; border:none;")
        self._sl.addWidget(line)

    def _on_item_only_requested(self, item_key: str, section_key: str) -> None:
        """Slot for the per-row 'Only' button — delegates to select_only_group."""
        self.select_only_group(item_key, section_key)

    def _on_collapse_toggled(self):
        """Save collapse state when a section header is toggled — no filter reload."""
        if not self._restoring:
            self.save_state()

    def _on_changed(self):
        if not self._restoring:
            self.save_state()
        self.filter_changed.emit()

    def _region_label(self, code: str) -> str:
        from metatv.core.channel_name_utils import REGION_FULL_NAMES
        return REGION_FULL_NAMES.get(code, code)

    # ── Right-click context menu ────────────────────────────────────────────────

    # Sections where "Exclude globally" makes sense — maps section key to the
    # config lookup that resolves a display key to its prefix codes.
    _GLOBALLY_EXCLUDABLE = {"language", "region", "platform", "subtitle", "dub", "format"}

    def _on_item_right_clicked(self, item_key: str, section_key: str, pos: QPoint):
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background:{_theme.COLOR_LINE_DARK}; color:{_theme.COLOR_TEXT}; border:1px solid {_theme.COLOR_BORDER}; }}"
            f"QMenu::item:selected {{ background:{_theme.COLOR_BORDER}; }}"
        )

        only_act = menu.addAction(f"Only '{item_key}'")
        only_act.setToolTip("Show only this group — clears all other filters")
        only_act.triggered.connect(lambda: self.select_only_group(item_key, section_key))

        solo_act = menu.addAction(f"Check only '{item_key}'")
        solo_act.triggered.connect(lambda: self._check_only(item_key, section_key))

        if section_key in self._GLOBALLY_EXCLUDABLE:
            menu.addSeparator()
            excl_act = menu.addAction(f"Exclude '{item_key}' globally…")
            excl_act.triggered.connect(
                lambda: self._exclude_globally(item_key, section_key)
            )

        menu.exec(pos)

    def _check_only(self, item_key: str, section_key: str):
        for sec in self._all_sections():
            if sec.section_key() == section_key:
                sec.check_only(item_key)
                self.save_state()
                break

    def _exclude_globally(self, item_key: str, section_key: str):
        """Add the item's prefix codes to global_filter_excluded_prefixes."""
        # Resolve display key → list of raw prefix codes
        if section_key == "language":
            prefixes = self.config.filter_language_groups.get(item_key, [item_key])
        elif section_key == "region":
            prefixes = [item_key]
        elif section_key == "platform":
            prefixes = self.config.filter_platform_groups.get(item_key, [item_key])
        else:
            return

        excluded: list[str] = list(getattr(self.config, 'global_filter_excluded_prefixes', []))
        added = False
        for p in prefixes:
            if p not in excluded:
                excluded.append(p)
                added = True
        if not added:
            return

        self.config.global_filter_excluded_prefixes = excluded
        self.config.save()
        logger.info(f"Globally excluded {prefixes} via filter panel (key={item_key!r})")

        # Also uncheck the item locally so the UI is consistent
        for sec in self._all_sections():
            if sec.section_key() == section_key:
                for r in sec._rows:
                    if r.key() == item_key:
                        r.set_checked(False, block=False)
                        break
                sec._update_ui()
                break
        self.save_state()
        self.filter_changed.emit()
