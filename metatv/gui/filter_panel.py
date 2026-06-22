"""Faceted filter panel — resizable vertical sidebar inside the channel list area.

Sections (Language OR Region OR Platform OR Uncategorized grows the pool;
Quality filters it):
  Media        — Live / Movies / Series
  Language     — language groups + locale sub-groups
  Region       — geographic hierarchy: group → individual prefix codes
  Platform     — individual streaming brands
  Quality      — resolution/encoding tiers  (AND/restrictive)
  Uncategorized — prefix codes not mapped to any known group; each individually selectable
  Unknown      — channels with no detectable region/language or quality tag

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

    # Section keys in display order
    _SECTION_KEYS = ["media", "language", "region", "platform",
                     "quality", "genre", "unidentified", "untagged"]

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._restoring = False

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

        self._unid_sec = _Section(
            "unidentified", "Uncategorized",
            initially_expanded=_expanded("unidentified", False),
            info_text=(
                "Channels that have a prefix code the app hasn't classified "
                "into a known language, region, or platform group.\n\n"
                "The prefix is there — we just don't know what it means yet. "
                "Uncheck a code to exclude those channels from results."
            ),
            info_icon=_ii, config=self.config)
        self._unid_sec.changed.connect(self._on_changed)
        self._sl.addWidget(self._unid_sec)
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

        # Wire right-click signals from all sections
        for sec in self._all_sections():
            sec.item_right_clicked.connect(self._on_item_right_clicked)
            # collapse_toggled saves state but does NOT emit filter_changed
            sec.collapse_toggled.connect(self._on_collapse_toggled)

        self.restore_state()

    # ── public API ──────────────────────────────────────────────────────────

    def update_data(self, stats: dict):
        """Populate sections from get_prefix_stats() result dict.

        On first call (startup), the in-memory ``prev`` selections are all empty
        because the items don't exist yet when ``restore_state()`` runs at init.
        In that case we fall back to the persisted config selections so that saved
        filter choices survive a restart.  On subsequent calls (e.g. after a source
        refresh) we preserve the user's current in-memory selection instead.
        """
        prefix_counts: dict[str, int] = stats.get('prefix_counts', {})

        # Build the startup fallback: config_attr → persisted set of keys.
        # Uses the same (config_attr, section) mapping as restore_state() so there
        # is exactly one place that knows the attr names.
        _persisted: dict[object, set[str]] = {
            sec: set(getattr(self.config, attr, []) or [])
            for attr, sec in self._persisted_section_attrs()
        }

        def _restore(sec: object, prev: set[str]) -> None:
            """Apply selection: in-memory prev if present, else persisted startup value."""
            if prev:
                sec.restore_selection(prev)
            else:
                fallback = _persisted.get(sec)
                if fallback:
                    sec.restore_selection(fallback)

        # ── Media — update counts only (items are static)

        # ── Language — flat, sorted by count
        lang_groups = stats.get('language_groups', {})
        lang_items = sorted(
            [(k, k, v) for k, v in lang_groups.items() if v > 0],
            key=lambda x: (-x[2], x[1]),
        )
        prev_lang = set(self._lang_sec.get_selected_keys())
        self._lang_sec.set_flat_items(lang_items)
        _restore(self._lang_sec, prev_lang)

        # ── Region — hierarchical: group → individual prefix codes
        regional_groups = self.config.filter_regional_groups
        region_counts = stats.get('region_groups', {})
        region_data: list[tuple[str, int, list[tuple[str, str, int]]]] = []
        for group_name in sorted(regional_groups.keys()):
            total = region_counts.get(group_name, 0)
            if total == 0:
                continue
            children = [
                (code, self._region_label(code), prefix_counts.get(code, 0))
                for code in regional_groups[group_name]
                if prefix_counts.get(code, 0) > 0
            ]
            children.sort(key=lambda x: -x[2])
            if children:
                region_data.append((group_name, total, children))
        prev_region = set(self._region_sec.get_selected_keys())
        self._region_sec.set_grouped_items(region_data)
        _restore(self._region_sec, prev_region)

        # ── Platform — flat, sorted by count
        platform_groups = stats.get('platform_groups', {})
        plat_items = sorted(
            [(k, k, v) for k, v in platform_groups.items() if v > 0],
            key=lambda x: (-x[2], x[1]),
        )
        prev_plat = set(self._platform_sec.get_selected_keys())
        self._platform_sec.set_flat_items(plat_items)
        _restore(self._platform_sec, prev_plat)

        # ── Quality — fixed tier order
        quality_order = ["RAW", "4K / UHD", "HD", "HQ", "SD", "LQ",
                         "CAM / Pre-release"]
        quality_groups = stats.get('quality_groups', {})
        qual_items = [
            (n, n, quality_groups[n]) for n in quality_order
            if n in quality_groups and quality_groups[n] > 0
        ]
        for n, v in quality_groups.items():
            if n not in quality_order and v > 0:
                qual_items.append((n, n, v))
        prev_qual = set(self._quality_sec.get_selected_keys())
        self._quality_sec.set_flat_items(qual_items)
        _restore(self._quality_sec, prev_qual)

        # ── Genre — flat, sorted by count descending (alphabetically within same count)
        genre_counts: dict[str, int] = stats.get('genre_counts', {})
        genre_items = sorted(
            [(g, g, c) for g, c in genre_counts.items()],
            key=lambda x: (-x[2], x[1]),
        )
        prev_genre = set(self._genre_sec.get_selected_keys())
        self._genre_sec.set_flat_items(genre_items)
        if prev_genre:
            self._genre_sec.restore_selection(prev_genre)
        else:
            persisted_genre = _persisted.get(self._genre_sec)
            if persisted_genre:
                # Startup: apply saved genre selection
                self._genre_sec.restore_selection(persisted_genre)
            else:
                # Fresh install / no saved selection: show everything
                self._genre_sec.select_all()

        # ── Unidentified — individual prefix codes, sorted by count
        # (Not persisted — dynamic content that varies by channel library)
        unmapped: list[str] = stats.get('unmapped_prefixes', [])
        unid_items = sorted(
            [(p, p, prefix_counts.get(p, 0)) for p in unmapped
             if prefix_counts.get(p, 0) > 0],
            key=lambda x: -x[2],
        )
        prev_unid = set(self._unid_sec.get_selected_keys())
        self._unid_sec.set_flat_items(unid_items)
        if prev_unid:
            self._unid_sec.restore_selection(prev_unid)

        # ── Untagged — update counts; items are static (set in __init__)
        no_prefix_count  = stats.get('channels_without_prefix',  0)
        no_quality_count = stats.get('channels_without_quality', 0)
        prev_untagged = set(self._untagged_sec.get_selected_keys())
        self._untagged_sec.set_flat_items([
            ("no_prefix",  "Region / Language", no_prefix_count),
            ("no_quality", "Playback Quality",  no_quality_count),
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

        logger.debug(
            f"FilterPanel updated: {len(lang_items)} lang groups, "
            f"{len(region_data)} region groups, {len(plat_items)} platform, "
            f"{len(qual_items)} quality, {len(genre_items)} genres, "
            f"{len(unid_items)} unidentified"
        )

    def get_filter_state(self) -> dict:
        """Return resolved filter state for main_window.load_channels()."""
        media_sel = set(self._media_sec.get_selected_keys())
        media_all = {"live", "movie", "series"}
        media_types = list(media_sel) if media_sel != media_all else list(media_all)

        lang_all   = self._lang_sec.is_all_selected()
        region_all = self._region_sec.is_all_selected()
        plat_all   = self._platform_sec.is_all_selected()
        qual_all   = self._quality_sec.is_all_selected()
        genre_all  = self._genre_sec.is_all_selected()
        unid_all   = self._unid_sec.is_all_selected()

        # Resolve language prefix codes from selected group names
        language_prefixes: list[str] = []
        if not lang_all:
            for grp in self._lang_sec.get_selected_keys():
                language_prefixes.extend(
                    self.config.filter_language_groups.get(grp, []))

        # Region: already individual prefix codes from the hierarchical selection
        region_prefixes: list[str] = (
            [] if region_all else self._region_sec.get_selected_keys()
        )

        # Platform prefix codes from selected group names
        platform_prefixes: list[str] = []
        if not plat_all:
            for grp in self._platform_sec.get_selected_keys():
                platform_prefixes.extend(
                    self.config.filter_platform_groups.get(grp, []))

        # Snapshot whether any *named* axis is restricted BEFORE adding unid codes.
        # Unid-only selection must NOT trigger cross-axis expansion — expansion would
        # add all language/region/platform codes and make the filter a no-op.
        named_axis_active = bool(language_prefixes or region_prefixes or platform_prefixes)

        # Unidentified codes join the language pool (same OR logic).
        if not unid_all:
            language_prefixes.extend(self._unid_sec.get_selected_keys())

        # Cross-axis expansion: when a named axis (lang/region/plat) is restricted, the
        # SQL identity filter activates and unrestricted axes must be explicitly expanded
        # so their channels aren't excluded (e.g. platform channels when filtering language).
        # When ONLY unidentified codes are selected this expansion is skipped — the
        # intent is "show only these specific prefixes", not "show everything else too".
        if named_axis_active:
            if lang_all:
                for codes in self.config.filter_language_groups.values():
                    language_prefixes.extend(codes)
            if unid_all:
                language_prefixes.extend(self._unid_sec.get_all_keys())
            if region_all:
                for codes in self.config.filter_regional_groups.values():
                    region_prefixes.extend(codes)
            if plat_all:
                for codes in self.config.filter_platform_groups.values():
                    platform_prefixes.extend(codes)

        # Quality prefix codes
        quality_prefixes: list[str] = []
        if not qual_all:
            for grp in self._quality_sec.get_selected_keys():
                quality_prefixes.extend(
                    self.config.filter_quality_groups.get(grp, []))

        untagged_selected = set(self._untagged_sec.get_selected_keys())
        include_untagged         = "no_prefix"  in untagged_selected
        include_untagged_quality = "no_quality" in untagged_selected

        genre_filters = None if genre_all else self._genre_sec.get_selected_keys()

        return {
            'media_types':        media_types,
            'language_groups':    self._lang_sec.get_selected_keys(),
            'region_groups':      self._region_sec.get_selected_keys(),
            'quality_groups':     self._quality_sec.get_selected_keys(),
            'platform_groups':    self._platform_sec.get_selected_keys(),
            'genre_filters':      self._genre_sec.get_selected_keys(),
            'include_untagged':          include_untagged,
            'include_untagged_quality':  include_untagged_quality,
            'adult_mode':         getattr(self.config, 'filter_adult_mode', 'hide'),
            'excluded_provider_ids': [],
            # Resolved for SQL — used directly by load_channels
            '_language_prefixes': language_prefixes or None,
            '_region_prefixes':   region_prefixes or None,
            '_platform_prefixes': platform_prefixes or None,
            '_quality_prefixes':  quality_prefixes or None,
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

    def select_only_genre(self, genre: str) -> None:
        """Filter to a single genre — called when the user clicks a genre chip in the details pane.

        Uses check_only() which emits changed → _on_changed → filter_changed,
        so load_channels() fires automatically.
        """
        self._genre_sec.check_only(genre)

    def save_state(self):
        try:
            state = self.get_filter_state()
            self.config.filter_included_languages  = state['language_groups']
            self.config.filter_included_regions    = state['region_groups']
            self.config.filter_included_qualities  = state['quality_groups']
            self.config.filter_included_platforms  = state['platform_groups']
            self.config.filter_included_genres     = state['genre_filters']
            self.config.filter_adult_mode          = state['adult_mode']

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
                saved = getattr(self.config, attr, [])
                if saved:
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
                self._platform_sec, self._quality_sec, self._genre_sec,
                self._unid_sec, self._untagged_sec]

    def _persisted_section_attrs(self) -> list[tuple[str, object]]:
        """Return (config_attr_name, section) pairs for all dynamic sections.

        Single source of truth for the config-key → section mapping, shared by
        ``restore_state`` (startup) and ``update_data`` (startup fallback path).
        """
        return [
            ('filter_included_languages', self._lang_sec),
            ('filter_included_regions',   self._region_sec),
            ('filter_included_qualities', self._quality_sec),
            ('filter_included_platforms', self._platform_sec),
            ('filter_included_genres',    self._genre_sec),
        ]

    def _add_divider(self):
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet(f"background:{_theme.COLOR_LINE_DARK}; border:none;")
        self._sl.addWidget(line)

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
    _GLOBALLY_EXCLUDABLE = {"unidentified", "language", "region", "platform"}

    def _on_item_right_clicked(self, item_key: str, section_key: str, pos: QPoint):
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background:{_theme.COLOR_LINE_DARK}; color:{_theme.COLOR_TEXT}; border:1px solid {_theme.COLOR_BORDER}; }}"
            f"QMenu::item:selected {{ background:{_theme.COLOR_BORDER}; }}"
        )

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
        if section_key == "unidentified":
            prefixes = [item_key]
        elif section_key == "language":
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
