"""Faceted filter panel — resizable vertical sidebar inside the channel list area.

Sections (Language OR Region OR Platform OR Unidentified grows the pool;
Quality narrows it):
  Media       — Live / Movies / Series
  Language    — language groups + locale sub-groups
  Region      — geographic hierarchy: group → individual prefix codes
  Platform    — individual streaming brands
  Quality     — resolution/encoding tiers  (AND/restrictive)
  Unidentified — unmapped prefix codes; each individually selectable

All sections persist their collapsed/expanded state and selection state to config.
Panel width persists via the QSplitter in main_window.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)
from loguru import logger


# ── Accent colours per section ─────────────────────────────────────────────────
_ACCENT = {
    "media":        "#4488ff",
    "language":     "#4488ff",
    "region":       "#44aa77",
    "platform":     "#9966cc",
    "quality":      "#f0a040",
    "unidentified": "#cc7722",
}


def _fmt(n: int) -> str:
    return f"{n:,}" if n >= 1000 else str(n)


# ── Tri-state header checkbox ──────────────────────────────────────────────────

class _TriCheckbox(QCheckBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTristate(True)
        self.setStyleSheet("QCheckBox { color: #cccccc; }")

    def mousePressEvent(self, event):
        state = self.checkState()
        if state == Qt.CheckState.Checked:
            self.setCheckState(Qt.CheckState.Unchecked)
        else:
            self.setCheckState(Qt.CheckState.Checked)
        self.stateChanged.emit(self.checkState().value)


# ── Single item row ────────────────────────────────────────────────────────────

class _ItemRow(QWidget):
    toggled = pyqtSignal(str, bool)

    def __init__(self, key: str, label: str, count: int,
                 indent: int = 0, parent=None):
        super().__init__(parent)
        self._key = key
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8 + indent, 2, 8, 2)
        layout.setSpacing(6)

        self._cb = QCheckBox()
        self._cb.setChecked(True)
        self._cb.setStyleSheet("QCheckBox { color: #cccccc; }")
        layout.addWidget(self._cb)

        lbl = QLabel(label)
        lbl.setStyleSheet("font-size: 12px; color: #cccccc;")
        lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(lbl)

        if count > 0:
            cnt = QLabel(_fmt(count))
            cnt.setStyleSheet("font-size: 11px; color: #555555;")
            cnt.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            layout.addWidget(cnt)

        self._cb.stateChanged.connect(
            lambda state: self.toggled.emit(self._key,
                                            state == Qt.CheckState.Checked.value)
        )

    def is_checked(self) -> bool:
        return self._cb.isChecked()

    def set_checked(self, checked: bool, block: bool = True):
        if block:
            self._cb.blockSignals(True)
        self._cb.setChecked(checked)
        if block:
            self._cb.blockSignals(False)

    def key(self) -> str:
        return self._key


# ── Expandable group row (Region hierarchy) ────────────────────────────────────

class _GroupRow(QWidget):
    changed = pyqtSignal()

    def __init__(self, group_name: str, total_count: int,
                 child_items: list[tuple[str, str, int]],
                 indent: int = 0, parent=None):
        super().__init__(parent)
        self._children: list[_ItemRow] = []
        self._expanded = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget()
        hl = QHBoxLayout(header)
        hl.setContentsMargins(8 + indent, 3, 8, 3)
        hl.setSpacing(4)

        self._expand_btn = QPushButton("▶")
        self._expand_btn.setFixedSize(16, 16)
        self._expand_btn.setFlat(True)
        self._expand_btn.setStyleSheet("QPushButton { color: #666; font-size: 9px; }")
        self._expand_btn.clicked.connect(self._toggle_expand)
        hl.addWidget(self._expand_btn)

        self._tri = _TriCheckbox()
        self._tri.setCheckState(Qt.CheckState.Checked)
        self._tri.stateChanged.connect(self._on_tri_changed)
        hl.addWidget(self._tri)

        name_lbl = QLabel(group_name)
        name_lbl.setStyleSheet("font-size: 12px; color: #bbbbbb;")
        name_lbl.setSizePolicy(QSizePolicy.Policy.Expanding,
                                QSizePolicy.Policy.Preferred)
        hl.addWidget(name_lbl)

        if total_count > 0:
            cnt = QLabel(_fmt(total_count))
            cnt.setStyleSheet("font-size: 11px; color: #555555;")
            cnt.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            hl.addWidget(cnt)

        outer.addWidget(header)

        self._child_container = QWidget()
        cl = QVBoxLayout(self._child_container)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        for key, label, count in child_items:
            row = _ItemRow(key, label, count, indent=indent + 16)
            row.toggled.connect(self._on_child_toggled)
            cl.addWidget(row)
            self._children.append(row)

        self._child_container.hide()
        outer.addWidget(self._child_container)

    def _toggle_expand(self):
        self._expanded = not self._expanded
        self._child_container.setVisible(self._expanded)
        self._expand_btn.setText("▼" if self._expanded else "▶")

    def _on_tri_changed(self, state_val: int):
        state = Qt.CheckState(state_val)
        if state == Qt.CheckState.PartiallyChecked:
            return
        checked = (state == Qt.CheckState.Checked)
        for row in self._children:
            row.set_checked(checked)
        self.changed.emit()

    def _on_child_toggled(self, key: str, checked: bool):
        self._update_tri()
        self.changed.emit()

    def _update_tri(self):
        states = [r.is_checked() for r in self._children]
        self._tri.blockSignals(True)
        if all(states):
            self._tri.setCheckState(Qt.CheckState.Checked)
        elif any(states):
            self._tri.setCheckState(Qt.CheckState.PartiallyChecked)
        else:
            self._tri.setCheckState(Qt.CheckState.Unchecked)
        self._tri.blockSignals(False)

    def get_selected_keys(self) -> list[str]:
        return [r.key() for r in self._children if r.is_checked()]

    def set_all_checked(self, checked: bool):
        self._tri.blockSignals(True)
        self._tri.setCheckState(
            Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self._tri.blockSignals(False)
        for row in self._children:
            row.set_checked(checked)

    def is_all_checked(self) -> bool:
        return all(r.is_checked() for r in self._children)

    def restore_selection(self, selected_keys: set[str]):
        for row in self._children:
            row.set_checked(row.key() in selected_keys)
        self._update_tri()


# ── Section widget ─────────────────────────────────────────────────────────────

class _Section(QWidget):
    changed = pyqtSignal()

    def __init__(self, section_key: str, title: str,
                 and_axis: bool = False,
                 initially_expanded: bool = False,
                 parent=None):
        super().__init__(parent)
        self._key = section_key
        self._rows: list[_ItemRow] = []
        self._groups: list[_GroupRow] = []
        self._expanded = initially_expanded

        accent = _ACCENT.get(section_key, "#4488ff")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header
        header = QWidget()
        header.setObjectName("sectionHeader")
        header.setStyleSheet(
            f"QWidget#sectionHeader {{ background: #1e1e1e; "
            f"border-left: 3px solid {accent}; }}"
        )
        header.setFixedHeight(30)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(6, 0, 6, 0)
        hl.setSpacing(4)

        self._collapse_btn = QPushButton("▼" if initially_expanded else "▶")
        self._collapse_btn.setFixedSize(16, 16)
        self._collapse_btn.setFlat(True)
        self._collapse_btn.setStyleSheet(
            "QPushButton { color: #888; font-size: 9px; }")
        self._collapse_btn.clicked.connect(self._toggle_collapse)
        hl.addWidget(self._collapse_btn)

        title_lbl = QLabel(title.upper())
        title_lbl.setStyleSheet(
            "font-size: 11px; font-weight: bold; color: #cccccc; "
            "letter-spacing: 1px;")
        hl.addWidget(title_lbl)

        if and_axis:
            narrows = QLabel("— narrows")
            narrows.setStyleSheet(
                "font-size: 10px; color: #f0a04077; font-style: italic;")
            hl.addWidget(narrows)

        hl.addStretch()

        self._summary_lbl = QLabel("")
        self._summary_lbl.setStyleSheet("font-size: 10px; color: #666666;")
        hl.addWidget(self._summary_lbl)

        self._select_all = _TriCheckbox()
        self._select_all.setCheckState(Qt.CheckState.Checked)
        self._select_all.setToolTip("Select all / deselect all")
        self._select_all.stateChanged.connect(self._on_select_all)
        hl.addWidget(self._select_all)

        outer.addWidget(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #2a2a2a;")
        outer.addWidget(sep)

        # Content
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 2, 0, 4)
        self._content_layout.setSpacing(0)
        self._content.setVisible(initially_expanded)
        outer.addWidget(self._content)

    # ── public ─────────────────────────────────────────────────────────────

    def section_key(self) -> str:
        return self._key

    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool):
        self._expanded = expanded
        self._content.setVisible(expanded)
        self._collapse_btn.setText("▼" if expanded else "▶")

    def set_flat_items(self, items: list[tuple[str, str, int]]):
        self._clear()
        for key, label, count in items:
            row = _ItemRow(key, label, count)
            row.toggled.connect(self._on_item_toggled)
            self._content_layout.addWidget(row)
            self._rows.append(row)
        self._update_ui()

    def set_grouped_items(self,
                          groups: list[tuple[str, int, list[tuple[str, str, int]]]]):
        self._clear()
        for group_name, total, children in groups:
            g = _GroupRow(group_name, total, children)
            g.changed.connect(self._on_group_changed)
            self._content_layout.addWidget(g)
            self._groups.append(g)
        self._update_ui()

    def get_selected_keys(self) -> list[str]:
        keys = [r.key() for r in self._rows if r.is_checked()]
        for grp in self._groups:
            keys.extend(grp.get_selected_keys())
        return keys

    def is_all_selected(self) -> bool:
        if self._rows:
            return all(r.is_checked() for r in self._rows)
        return all(g.is_all_checked() for g in self._groups) if self._groups else True

    def select_all(self):
        self._select_all.blockSignals(True)
        self._select_all.setCheckState(Qt.CheckState.Checked)
        self._select_all.blockSignals(False)
        for r in self._rows:
            r.set_checked(True)
        for g in self._groups:
            g.set_all_checked(True)

    def select_none(self):
        self._select_all.blockSignals(True)
        self._select_all.setCheckState(Qt.CheckState.Unchecked)
        self._select_all.blockSignals(False)
        for r in self._rows:
            r.set_checked(False)
        for g in self._groups:
            g.set_all_checked(False)

    def restore_selection(self, selected_keys: set[str]):
        for r in self._rows:
            r.set_checked(r.key() in selected_keys)
        for g in self._groups:
            g.restore_selection(selected_keys)
        self._update_ui()

    # ── private ────────────────────────────────────────────────────────────

    def _clear(self):
        for w in self._rows + self._groups:
            w.deleteLater()
        self._rows.clear()
        self._groups.clear()

    def _toggle_collapse(self):
        self.set_expanded(not self._expanded)
        self.changed.emit()  # so parent can save collapse state

    def _on_select_all(self, state_val: int):
        state = Qt.CheckState(state_val)
        if state == Qt.CheckState.PartiallyChecked:
            return
        checked = (state == Qt.CheckState.Checked)
        for r in self._rows:
            r.set_checked(checked)
        for g in self._groups:
            g.set_all_checked(checked)
        self._update_summary()
        self.changed.emit()

    def _on_item_toggled(self, key: str, checked: bool):
        self._update_ui()
        self.changed.emit()

    def _on_group_changed(self):
        self._update_ui()
        self.changed.emit()

    def _update_ui(self):
        self._update_select_all_state()
        self._update_summary()

    def _update_select_all_state(self):
        self._select_all.blockSignals(True)
        if self.is_all_selected():
            self._select_all.setCheckState(Qt.CheckState.Checked)
        elif self.get_selected_keys():
            self._select_all.setCheckState(Qt.CheckState.PartiallyChecked)
        else:
            self._select_all.setCheckState(Qt.CheckState.Unchecked)
        self._select_all.blockSignals(False)

    def _update_summary(self):
        """Show active selections in header when collapsed."""
        sel = self.get_selected_keys()
        total = len(self._rows) + sum(len(g._children) for g in self._groups)
        if not sel or len(sel) == total:
            self._summary_lbl.setText("")
        elif len(sel) <= 3:
            self._summary_lbl.setText(", ".join(sel[:3]))
        else:
            self._summary_lbl.setText(f"{len(sel)}/{total}")


# ── Main FilterPanel ───────────────────────────────────────────────────────────

class FilterPanel(QWidget):
    """Vertical faceted filter panel — lives in a QSplitter left of the channel list."""

    filter_changed = pyqtSignal()
    settings_requested = pyqtSignal()

    # Section keys in display order
    _SECTION_KEYS = ["media", "language", "region", "platform",
                     "quality", "unidentified"]

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._restoring = False

        self.setMinimumWidth(160)
        self.setMaximumWidth(400)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.setStyleSheet("background: #1a1a1a;")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Panel header
        ph = QWidget()
        ph.setStyleSheet("background: #111111;")
        ph.setFixedHeight(36)
        phl = QHBoxLayout(ph)
        phl.setContentsMargins(10, 0, 8, 0)
        QLabel("Filters", ph).setStyleSheet(
            "font-size: 13px; font-weight: bold; color: #dddddd;")
        phl.addWidget(QLabel("Filters", ph))
        phl.addStretch()
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedHeight(22)
        clear_btn.setStyleSheet("""
            QPushButton { background:#333; color:#aaa; border:1px solid #444;
                border-radius:3px; padding:0 8px; font-size:11px; }
            QPushButton:hover { background:#444; color:#ddd; }
        """)
        clear_btn.setToolTip("Reset all filters — show everything")
        clear_btn.clicked.connect(self.clear_all)
        phl.addWidget(clear_btn)
        outer.addWidget(ph)

        # Scrollable sections
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea { border:none; background:#1a1a1a; }
            QScrollBar:vertical { background:#222; width:6px; border-radius:3px; }
            QScrollBar::handle:vertical { background:#444; border-radius:3px; }
        """)

        sc = QWidget()
        sc.setStyleSheet("background:#1a1a1a;")
        self._sl = QVBoxLayout(sc)
        self._sl.setContentsMargins(0, 0, 0, 0)
        self._sl.setSpacing(0)

        # Read saved collapse states
        saved_states: dict = getattr(self.config, 'filter_section_states', {})

        def _expanded(key: str, default: bool) -> bool:
            return saved_states.get(key, default)

        # Build sections
        self._media_sec = _Section(
            "media", "Media",
            initially_expanded=_expanded("media", True))
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
            initially_expanded=_expanded("language", False))
        self._lang_sec.changed.connect(self._on_changed)
        self._sl.addWidget(self._lang_sec)
        self._add_divider()

        self._region_sec = _Section(
            "region", "Region",
            initially_expanded=_expanded("region", False))
        self._region_sec.changed.connect(self._on_changed)
        self._sl.addWidget(self._region_sec)
        self._add_divider()

        self._platform_sec = _Section(
            "platform", "Platform",
            initially_expanded=_expanded("platform", False))
        self._platform_sec.changed.connect(self._on_changed)
        self._sl.addWidget(self._platform_sec)
        self._add_divider()

        self._quality_sec = _Section(
            "quality", "Quality", and_axis=True,
            initially_expanded=_expanded("quality", False))
        self._quality_sec.changed.connect(self._on_changed)
        self._sl.addWidget(self._quality_sec)
        self._add_divider()

        self._unid_sec = _Section(
            "unidentified", "Unidentified",
            initially_expanded=_expanded("unidentified", False))
        self._unid_sec.changed.connect(self._on_changed)
        self._sl.addWidget(self._unid_sec)

        self._sl.addStretch()
        scroll.setWidget(sc)
        outer.addWidget(scroll, 1)

        # Settings button at bottom
        settings_btn = QPushButton("⚙  Settings")
        settings_btn.setFixedHeight(32)
        settings_btn.setStyleSheet("""
            QPushButton {
                background:#111; color:#888; border-top:1px solid #333;
                border-radius:0; font-size:12px; text-align:left;
                padding-left:12px;
            }
            QPushButton:hover { background:#1e1e1e; color:#aaa; }
        """)
        settings_btn.clicked.connect(self.settings_requested)
        outer.addWidget(settings_btn)

        self.restore_state()

    # ── public API ──────────────────────────────────────────────────────────

    def update_data(self, stats: dict):
        """Populate sections from get_prefix_stats() result dict."""
        prefix_counts: dict[str, int] = stats.get('prefix_counts', {})

        # ── Media — update counts only (items are static)
        from sqlalchemy import func
        # We don't have per-type counts in stats, leave at 0

        # ── Language — flat, sorted by count
        lang_groups = stats.get('language_groups', {})
        lang_items = sorted(
            [(k, k, v) for k, v in lang_groups.items() if v > 0],
            key=lambda x: (-x[2], x[1]),
        )
        prev_lang = set(self._lang_sec.get_selected_keys())
        self._lang_sec.set_flat_items(lang_items)
        if prev_lang:
            self._lang_sec.restore_selection(prev_lang)

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
        if prev_region:
            self._region_sec.restore_selection(prev_region)

        # ── Platform — flat, sorted by count
        platform_groups = stats.get('platform_groups', {})
        plat_items = sorted(
            [(k, k, v) for k, v in platform_groups.items() if v > 0],
            key=lambda x: (-x[2], x[1]),
        )
        prev_plat = set(self._platform_sec.get_selected_keys())
        self._platform_sec.set_flat_items(plat_items)
        if prev_plat:
            self._platform_sec.restore_selection(prev_plat)

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
        if prev_qual:
            self._quality_sec.restore_selection(prev_qual)

        # ── Unidentified — individual prefix codes, sorted by count
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

        logger.debug(
            f"FilterPanel updated: {len(lang_items)} lang groups, "
            f"{len(region_data)} region groups, {len(plat_items)} platform, "
            f"{len(qual_items)} quality, {len(unid_items)} unidentified"
        )

    def get_filter_state(self) -> dict:
        """Return resolved filter state for main_window.load_channels()."""
        media_sel = set(self._media_sec.get_selected_keys())
        media_all = {"live", "movie", "series"}
        media_types = list(media_sel) if media_sel != media_all else list(media_all)

        lang_all  = self._lang_sec.is_all_selected()
        region_all = self._region_sec.is_all_selected()
        plat_all  = self._platform_sec.is_all_selected()
        qual_all  = self._quality_sec.is_all_selected()
        unid_all  = self._unid_sec.is_all_selected()

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

        # Unidentified prefixes join the language pool (same OR logic)
        if not unid_all:
            language_prefixes.extend(self._unid_sec.get_selected_keys())

        # Quality prefix codes
        quality_prefixes: list[str] = []
        if not qual_all:
            for grp in self._quality_sec.get_selected_keys():
                quality_prefixes.extend(
                    self.config.filter_quality_groups.get(grp, []))

        return {
            'media_types':        media_types,
            'language_groups':    self._lang_sec.get_selected_keys(),
            'region_groups':      self._region_sec.get_selected_keys(),
            'quality_groups':     self._quality_sec.get_selected_keys(),
            'platform_groups':    self._platform_sec.get_selected_keys(),
            'include_untagged':   unid_all,
            'adult_mode':         getattr(self.config, 'filter_adult_mode', 'hide'),
            'excluded_provider_ids': [],
            # Resolved for SQL — used directly by load_channels
            '_language_prefixes': language_prefixes or None,
            '_region_prefixes':   region_prefixes or None,
            '_platform_prefixes': platform_prefixes or None,
            '_quality_prefixes':  quality_prefixes or None,
        }

    def clear_all(self):
        self._restoring = True
        try:
            for sec in self._all_sections():
                sec.select_all()
        finally:
            self._restoring = False
        self.save_state()
        self.filter_changed.emit()

    def save_state(self):
        try:
            state = self.get_filter_state()
            self.config.filter_included_languages  = state['language_groups']
            self.config.filter_included_regions    = state['region_groups']
            self.config.filter_included_qualities  = state['quality_groups']
            self.config.filter_included_platforms  = state['platform_groups']
            self.config.filter_adult_mode          = state['adult_mode']

            # Save per-section collapse states
            self.config.filter_section_states = {
                sec.section_key(): sec.is_expanded()
                for sec in self._all_sections()
            }
            # Save media selection
            self.config.filter_enabled_media_types = state['media_types']
            self.config.save()
        except Exception as e:
            logger.warning(f"Could not save filter panel state: {e}")

    def restore_state(self):
        self._restoring = True
        try:
            for attr, sec in [
                ('filter_included_languages', self._lang_sec),
                ('filter_included_regions',   self._region_sec),
                ('filter_included_qualities', self._quality_sec),
                ('filter_included_platforms', self._platform_sec),
            ]:
                saved = getattr(self.config, attr, [])
                if saved:
                    sec.restore_selection(set(saved))

            # Restore media chips
            enabled = getattr(self.config, 'filter_enabled_media_types',
                              ['live', 'movie', 'series']) or ['live', 'movie', 'series']
            self._media_sec.restore_selection(set(enabled))

        except Exception as e:
            logger.warning(f"Could not restore filter panel state: {e}")
        finally:
            self._restoring = False

    # ── private ─────────────────────────────────────────────────────────────

    def _all_sections(self) -> list[_Section]:
        return [self._media_sec, self._lang_sec, self._region_sec,
                self._platform_sec, self._quality_sec, self._unid_sec]

    def _add_divider(self):
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet("background:#2a2a2a; border:none;")
        self._sl.addWidget(line)

    def _on_changed(self):
        if not self._restoring:
            self.save_state()
        self.filter_changed.emit()

    def _region_label(self, code: str) -> str:
        from metatv.core.channel_name_utils import REGION_FULL_NAMES
        return REGION_FULL_NAMES.get(code, code)
