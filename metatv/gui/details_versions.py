"""Version chips and category-name types for the details pane."""
import re as _re
from dataclasses import dataclass

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QFrame, QPushButton, QLabel,
    QMenu, QLineEdit, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal


from metatv.core.channel_name_utils import (
    normalize_region_code, REGION_FULL_NAMES, AUDIO_LANG_WORD_MAP, quality_display,
)
from metatv.gui import cursor_affordance
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.details_section_header import CollapsibleHeader, CollapsibleMixin
from metatv.gui.details_version_groups import (
    DEFAULT_VISIBLE_REGIONS as VISIBLE_REGIONS,
    GROUPING_THRESHOLD,
    group_by_region,
    summarise,
)
from metatv.gui.flow_layout import FlowLayout
from metatv.gui.qt_text_utils import escape_mnemonic

# ---------------------------------------------------------------------------
# Lookup tables
# ---------------------------------------------------------------------------

_CHANNEL_PREFIX_RE = _re.compile(r'^([A-Z][A-Z0-9\-]{1,11})\s*([★|])\s*(.+)$')


def resolve_category_name(prefix: str, config=None) -> str:
    """Return the human-readable name for a prefix code, checking user overrides first."""
    if config is not None:
        overrides = getattr(config, "category_name_overrides", {})
        if prefix in overrides:
            return overrides[prefix]
    code = normalize_region_code(prefix)
    # Region name if it's a place; else the language name (a language code like AR
    # resolves to "Arabic", NOT the region "Argentina"); else "" so the caller falls
    # back to the raw code.  Single source of truth for a code's human-readable name.
    return (
        REGION_FULL_NAMES.get(code)
        or REGION_FULL_NAMES.get(prefix)
        or AUDIO_LANG_WORD_MAP.get(code)
        or AUDIO_LANG_WORD_MAP.get(prefix)
        or ""
    )


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ChannelVersion:
    """A single alternative version of the currently displayed channel."""
    channel_id: str
    name: str
    in_queue: bool
    detected_prefix: str | None = None
    detected_title: str | None = None   # stored bare title (ingestion) — render without re-parse
    detected_year: str | None = None    # stored year (ingestion)
    detected_quality: str | None = None # e.g. "HD", "FHD", "4K" — shown in source-picker chip
    detected_region: str | None = None  # e.g. "US", "FR" — shown in source-picker chip
    is_preferred: bool = False
    is_filtered: bool = False
    is_hidden: bool = False
    is_hidden_category: bool = False
    is_favorite: bool = False
    in_history: bool = False
    provider_name: str | None = None
    provider_id: str | None = None      # for source-picker chip play action + icon lookup
    is_inactive: bool = False           # True when provider is toggled off (inactive)
    media_type: str = ""            # "movie" | "series" | "live" | ""
    user_rating: int = 0            # +1 liked, -1 disliked, 0 no rating


# ---------------------------------------------------------------------------
# FlowLayout call sites (the class itself now lives in flow_layout.py)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# _CategoryNamePopup
# ---------------------------------------------------------------------------

class _CategoryNamePopup(QFrame):
    """Inline popup for naming/renaming a category prefix."""

    name_saved = pyqtSignal(str, str)   # prefix, new_name

    def __init__(self, prefix: str, current_name: str, config, parent=None):
        super().__init__(parent, Qt.WindowType.ToolTip)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        _theme.style_fn(self, lambda: f"QFrame {{ background: {_theme.COLOR_BG_CARD}; border: 1px solid {_theme.COLOR_BORDER}; border-radius: 4px; }}")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)
        prefix_lbl = QLabel(prefix)
        _theme.style_fn(prefix_lbl, lambda: f"color: {_theme.COLOR_TEXT}; font-size: {_theme.FONT_MD}; font-weight: bold;")
        layout.addWidget(prefix_lbl)
        self._edit = QLineEdit(current_name)
        self._edit.setClearButtonEnabled(True)
        self._edit.setPlaceholderText(f"Name for {prefix}…")
        self._edit.setMinimumWidth(160)
        self._edit.returnPressed.connect(self._on_save)
        layout.addWidget(self._edit)
        save_btn = QPushButton(config.watched_icon)
        save_btn.setFixedSize(28, 28)
        save_btn.setToolTip("Save category name")
        save_btn.clicked.connect(self._on_save)
        layout.addWidget(save_btn)
        self._prefix = prefix
        self._edit.setFocus()

    def _on_save(self) -> None:
        self.name_saved.emit(self._prefix, self._edit.text().strip())
        self.close()


# ---------------------------------------------------------------------------
# _VersionSection
# ---------------------------------------------------------------------------

class _VersionSection(CollapsibleMixin, QWidget):
    """Preferred-version nudge banner + wrapping source-picker chip row.

    Each chip shows the source icon (from *provider_map*), region/prefix, and
    quality tier.  Left-clicking a chip shows that variant's details in the
    details pane via ``version_selected``; right-clicking opens the full context
    menu (play / favorite / queue / hide / filter / reactivate).
    Inactive-source chips are dimmed and offer a "Reactivate & play" menu option
    via right-click only.
    """

    COLLAPSE_KEY = "versions"

    version_selected         = pyqtSignal(str)        # channel_id — show details
    play_version_requested   = pyqtSignal(str)        # channel_id — play that variant
    favorite_toggled         = pyqtSignal(str)        # channel_id
    queue_toggled            = pyqtSignal(str)        # channel_id
    hide_requested           = pyqtSignal(str)        # channel_id
    prefix_block_requested   = pyqtSignal(str)        # prefix
    prefix_unblock_requested = pyqtSignal(str)        # prefix
    prefix_name_saved        = pyqtSignal(str, str)   # prefix, name
    manage_filters_requested = pyqtSignal()

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._active_versions: list = []
        self._region_expanded: str | None = None
        self._show_all_regions: bool = False
        self._setup()

    def _setup(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # Preferred version nudge banner (green)
        self._pref_nudge = QFrame()
        _theme.style_fn(self._pref_nudge, lambda: f"QFrame {{ background: {_theme.OVERLAY_GREEN_15}; border-radius: 4px;"
            f" border: 1px solid {_theme.OVERLAY_GREEN_40}; }}")
        nudge_row = QHBoxLayout(self._pref_nudge)
        nudge_row.setContentsMargins(8, 4, 8, 4)
        self._pref_nudge_lbl = QLabel()
        _theme.style_fn(self._pref_nudge_lbl, lambda: f"font-size: {_theme.FONT_MD}; color: {_theme.COLOR_PREF_NUDGE};")
        self._pref_nudge_lbl.setWordWrap(True)
        self._pref_nudge_switch_btn = QPushButton("Switch")
        self._pref_nudge_switch_btn.setFlat(True)
        _theme.style_fn(self._pref_nudge_switch_btn, lambda: f"color: {_theme.COLOR_PREF_NUDGE}; font-size: {_theme.FONT_MD}; font-weight: bold; border: none;")
        self._pref_nudge_switch_btn.setToolTip("Switch the details pane to show your preferred version")
        nudge_row.addWidget(self._pref_nudge_lbl, 1)
        nudge_row.addWidget(self._pref_nudge_switch_btn)
        self._pref_nudge.hide()
        layout.addWidget(self._pref_nudge)

        # Chip section: "Also available as:" label above chips (vertical stack, full width)
        self._row_container = QWidget()
        row_layout = QVBoxLayout(self._row_container)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(4)

        # Header — the shared collapsible one, so this section folds away like
        # every other and its "65 versions · 19 regions" sits where every other
        # section's count sits.
        self._header = CollapsibleHeader("Also Available")
        row_layout.addWidget(self._header)

        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(4)
        row_layout.addWidget(self._content)

        # Active chips — full width
        self._chips_row = QWidget()
        self._chips_row.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self._chips_layout = FlowLayout(self._chips_row, h_spacing=4, v_spacing=4)
        content_layout.addWidget(self._chips_row)

        # Two collapsible chip sub-sections, built by ONE factory.
        #
        # "Filtered variants" is the soft bucket: things the user's own filters
        # excluded, revealable on demand. "Offline sources" is the hard one:
        # variants on a source that is turned off or expired. They must not be
        # the same list — CRITICAL_RULES "hidden-provider content is an absolute
        # gate ... never a soft filter" — but they ARE the same widget, and
        # hand-rolling the second copy of 45 lines of header plumbing is how
        # they drift apart.
        (self._filtered_section, self._filtered_toggle_btn, self._filtered_hdr_lbl,
         self._filtered_chips_row, self._filtered_chips_layout) = self._build_chip_subsection(
            "FILTERED VARIANTS", "Show/hide filtered variants",
            self._toggle_filtered_section,
        )
        self._filtered_collapsed: bool = True
        content_layout.addWidget(self._filtered_section)

        (self._offline_section, self._offline_toggle_btn, self._offline_hdr_lbl,
         self._offline_chips_row, self._offline_chips_layout) = self._build_chip_subsection(
            "OFFLINE SOURCES", "Variants on a source you have turned off or that has expired",
            self._toggle_offline_section,
        )
        self._offline_collapsed: bool = True
        content_layout.addWidget(self._offline_section)

        self._wire_header()

        self._row_container.hide()
        layout.addWidget(self._row_container)

    def load(
        self,
        versions: list[ChannelVersion],
        provider_map: dict | None = None,
    ) -> None:
        """Rebuild the chip row from a fresh version list.

        Args:
            versions: Alternative versions of the current channel.
            provider_map: Optional ``{provider_id: {"icon": str, "name": str}}`` map
                from ``DetailsPaneWidget._provider_map``.  When provided, chips show
                the provider icon to the left of the region/quality label.
        """
        self._provider_map: dict = provider_map or {}
        # Clear active chips layout
        layout = self._chips_layout
        while layout.count():
            item = layout.takeAt(0)
            if w := item.widget():
                w.deleteLater()
        # Clear both sub-section chip layouts. Missing the second one here is
        # how a reload leaves a previous title's offline chips on screen.
        for sub_layout in (self._filtered_chips_layout, self._offline_chips_layout):
            while sub_layout.count():
                item = sub_layout.takeAt(0)
                if w := item.widget():
                    w.deleteLater()

        try:
            self._pref_nudge_switch_btn.clicked.disconnect()
        except (RuntimeError, TypeError):
            pass
        self._pref_nudge.hide()
        self._row_container.hide()
        # Both sub-sections reset to hidden-and-collapsed on every load.
        self._filtered_section.hide()
        self._filtered_collapsed = True
        self._filtered_chips_row.hide()
        self._filtered_toggle_btn.setText(_icons.expand_icon)
        self._offline_section.hide()
        self._offline_collapsed = True
        self._offline_chips_row.hide()
        self._offline_toggle_btn.setText(_icons.expand_icon)

        if not versions:
            return

        # THREE buckets, not two. A variant on a source the user has turned
        # off (or that expired) used to land in `active`: rendered among the
        # available versions, counted in the "3 versions · 2 regions" header,
        # and distinguishable only by being slightly dimmer with an explanatory
        # tooltip. That is a hidden-provider leak into a forward-looking view —
        # CRITICAL_RULES:188 says such content "must never appear" there, and
        # the only documented exception is the record/engaged views (History,
        # Favorites, Queue). It also broke the colour-alone accessibility rule,
        # since dimness was the entire visual signal.
        #
        # It is NOT folded into `filtered` either. That bucket is the user's own
        # soft exclusions, revealable on demand; an inactive source is an
        # absolute gate (CRITICAL_RULES:219), and merging them would let
        # "reveal filtered" surface disabled-source content.
        #
        # The variants are still SHOWN, in their own section, because the chip
        # already offers "right-click to reactivate & play" and that recovery
        # path is the point — it just must not read as "available now".
        offline  = [v for v in versions if v.is_inactive and not v.is_hidden]
        active   = [v for v in versions
                    if not v.is_filtered and not v.is_hidden and not v.is_inactive]
        filtered = [v for v in versions
                    if v.is_filtered and not v.is_hidden and not v.is_inactive]

        # A source glyph on every chip is only information when the chips span
        # more than one source; with a single source it repeats the same symbol
        # down the whole list and crowds out the label that actually varies
        # (region/quality). Counted across active AND filtered so expanding
        # "Filtered variants" can't change the rule mid-render. The source is
        # still named in each chip's tooltip either way.
        self._show_source_icons = len({
            v.provider_id for v in (active + filtered + offline) if v.provider_id
        }) > 1

        if not active and not filtered and not offline:
            return

        preferred = next((v for v in versions if v.is_preferred), None)
        if preferred:
            self._pref_nudge_lbl.setText(
                f"{self.config.preferred_version_icon} Preferred: {preferred.name}"
            )
            self._pref_nudge_switch_btn.clicked.connect(
                lambda: self.version_selected.emit(preferred.channel_id)
            )
            self._pref_nudge.show()

        # Active variants render GROUPED BY REGION (see
        # details_version_groups.py — 65 chips become 12 plus a tail). Filtered
        # variants stay one chip per version: that list is short, already
        # behind a collapsed disclosure, and its whole purpose is naming the
        # individual thing that got filtered.
        self._active_versions = list(active)
        self._region_expanded = None
        self._show_all_regions = False
        self._render_region_grid()
        for v in filtered:
            self._filtered_chips_layout.addWidget(self._make_greyed_chip(v))

        for v in offline:
            # _make_active_chip, NOT _make_greyed_chip. Both render a quiet chip,
            # but the greyed one wires the FILTERED context menu and a tooltip
            # saying "filtered" — using it here would silently drop the
            # "right-click to reactivate & play" recovery path, which is the
            # entire reason these are still shown rather than dropped.
            # _make_active_chip already branches on is_inactive and every
            # variant in this list has it set.
            self._offline_chips_layout.addWidget(self._make_active_chip(v))
        self._offline_section.setVisible(bool(offline))

        if filtered:
            self._filtered_section.show()
        else:
            # Belt-and-suspenders: ensure the section is hidden even if a previous
            # load left it visible and this reload has zero filtered variants.
            self._filtered_section.hide()

        self._row_container.show()

        # Hide the active grid entirely when nothing is IN it. Before offline
        # variants moved to their own section, `active` was almost never empty
        # — an inactive-source variant landed here and filled it. Now a title
        # whose every variant is filtered or offline leaves an empty flow
        # layout under the "Also Available" header, which renders as a gap with
        # nothing in it (owner report, screenshot 2026-08-29). An empty
        # container still occupies its margins; it has to be hidden, not just
        # left unpopulated.
        self._chips_row.setVisible(bool(active))

        self._chips_row.updateGeometry()
        if filtered:
            self._filtered_chips_row.updateGeometry()
        if offline:
            self._offline_chips_row.updateGeometry()

    def _clear_active_chips(self) -> None:
        """Empty the grid — and take the old chips OFF THE SCREEN, now.

        ``deleteLater()`` alone does not: it schedules destruction for the next
        event-loop pass, and until then the widget is still a visible child of
        the row, painting where it was. Taking it out of the LAYOUT only stops
        it being positioned, so re-rendering in place (drilling into a region)
        drew the new chips straight over the old ones. ``setParent(None)``
        detaches it immediately; deleteLater then frees it.
        """
        while self._chips_layout.count():
            item = self._chips_layout.takeAt(0)
            if w := item.widget():
                w.setParent(None)
                w.deleteLater()

    def _render_region_grid(self) -> None:
        """Draw the active grid: region chips, or one region's versions.

        Two states, one renderer, because they are the same grid — drilling in
        replaces its contents rather than opening anything, so the pane never
        changes height under the pointer.
        """
        self._clear_active_chips()
        groups = group_by_region(self._active_versions)
        self._header.set_summary(summarise(groups) if groups else "")

        # Few enough to just show. Grouping costs a click to reach any version
        # and drops the source icon and quality tier from the face, which is a
        # bad trade until the flat list is genuinely unreadable.
        if len(self._active_versions) <= GROUPING_THRESHOLD:
            self._region_expanded = None
            for v in self._active_versions:
                self._chips_layout.addWidget(self._make_active_chip(v))
            self._chips_row.updateGeometry()
            return

        if self._region_expanded is not None:
            group = next(
                (g for g in groups if g.code == self._region_expanded), None
            )
            if group is not None:
                self._chips_layout.addWidget(self._make_back_chip(group))
                for v in group.versions:
                    self._chips_layout.addWidget(self._make_active_chip(v))
                self._chips_row.updateGeometry()
                return
            # The region vanished under us (a reload with different data).
            self._region_expanded = None

        shown = groups if self._show_all_regions else groups[:VISIBLE_REGIONS]
        for group in shown:
            self._chips_layout.addWidget(self._make_region_chip(group))
        hidden = len(groups) - len(shown)
        if hidden > 0:
            self._chips_layout.addWidget(self._make_more_chip(hidden))
        self._chips_row.updateGeometry()

    def _make_region_chip(self, group) -> QPushButton:
        """One region: its code and how many versions are in it."""
        chip = QPushButton(f"{group.code}  {group.count}")
        chip.setFlat(True)
        _theme.style(chip, "DETAIL_REGION_CHIP")
        cursor_affordance.set_clickable(chip)
        # The FACE is a bare code because a grid of twelve full region names is
        # the wall this replaced. The NAME is one hover away, with the region's
        # quality tiers — which is where they belong: quality is present on
        # roughly 6% of the library, so putting it on the face would leave
        # almost every chip with a gap where a tier should be.
        name = resolve_category_name(group.code, self.config) or group.code
        lines = [f"{name} — {group.count} version{'s' if group.count != 1 else ''}"]
        if group.qualities:
            lines.append("Quality: " + ", ".join(
                quality_display(q) for q in group.qualities
            ))
        lines.append("Click to see them")
        chip.setToolTip("\n".join(lines))
        chip.clicked.connect(lambda _=False, code=group.code: self._expand_region(code))
        return chip

    def _make_more_chip(self, hidden: int) -> QPushButton:
        chip = QPushButton(f"+ {hidden} more")
        chip.setFlat(True)
        _theme.style(chip, "DETAIL_REGION_LINK")
        cursor_affordance.set_clickable(chip)
        chip.setToolTip(f"Show the remaining {hidden} region"
                        f"{'s' if hidden != 1 else ''}")
        chip.clicked.connect(self._show_every_region)
        return chip

    def _make_back_chip(self, group) -> QPushButton:
        name = resolve_category_name(group.code, self.config) or group.code
        chip = QPushButton(f"{_icons.back_icon} All regions")
        chip.setFlat(True)
        _theme.style(chip, "DETAIL_REGION_LINK")
        cursor_affordance.set_clickable(chip)
        chip.setToolTip(f"Back to every region — showing {name}")
        chip.clicked.connect(self._collapse_region)
        return chip

    def _expand_region(self, code: str) -> None:
        self._region_expanded = code
        self._render_region_grid()

    def _collapse_region(self) -> None:
        self._region_expanded = None
        self._render_region_grid()

    def _show_every_region(self) -> None:
        self._show_all_regions = True
        self._render_region_grid()

    def clear(self) -> None:
        self.load([])

    def _build_chip_subsection(self, title: str, tooltip: str, on_toggle):
        """Build one collapsible, titled row of chips.

        Extracted when the second caller arrived. The header is ~45 lines of
        button-styled-as-label plumbing, and a copy of it for "Offline sources"
        would have been two headers that look identical today and drift apart
        the first time either is touched.

        Args:
            title: Header text, shown uppercase as written.
            tooltip: Hover text, on both the arrow and the label.
            on_toggle: Called when either the arrow or the label is clicked.

        Returns:
            ``(section, toggle_btn, header_label, chips_row, chips_layout)`` —
            unpacked into the caller's own attribute names, which existing
            tests already reach for.
        """
        section = QWidget()
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(0, 4, 0, 0)
        section_layout.setSpacing(2)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 2, 0, 2)
        header_layout.setSpacing(4)

        toggle_btn = QPushButton(_icons.expand_icon)
        toggle_btn.setFixedSize(20, 20)
        _theme.style_fn(toggle_btn, lambda: f"QPushButton {{ color: {_theme.COLOR_TEXT}; font-size: {_theme.FONT_SM}; border: none; }}"
            f"QPushButton:hover {{ color: {_theme.COLOR_TEXT}; }}")
        toggle_btn.setToolTip(tooltip)
        toggle_btn.clicked.connect(on_toggle)
        header_layout.addWidget(toggle_btn)

        # Flat QPushButton styled as a label so the whole text is clickable too.
        hdr_lbl = QPushButton(title)
        hdr_lbl.setFlat(True)
        _theme.style_fn(hdr_lbl, lambda: f"QPushButton {{ color: {_theme.COLOR_TEXT}; font-size: {_theme.FONT_SM};"
            " font-weight: bold; border: none; text-align: left; padding: 0; }"
            f"QPushButton:hover {{ color: {_theme.COLOR_TEXT}; }}")
        hdr_lbl.setToolTip(tooltip)
        hdr_lbl.clicked.connect(on_toggle)
        header_layout.addWidget(hdr_lbl)
        header_layout.addStretch()
        section_layout.addWidget(header)

        chips_row = QWidget()
        chips_row.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        chips_layout = FlowLayout(chips_row, h_spacing=4, v_spacing=4)
        chips_row.hide()                      # collapsed by default
        section_layout.addWidget(chips_row)

        section.hide()                        # shown only when it has chips
        return section, toggle_btn, hdr_lbl, chips_row, chips_layout

    def _toggle_offline_section(self) -> None:
        """Expand/collapse OFFLINE SOURCES."""
        self._offline_collapsed = not self._offline_collapsed
        self._offline_chips_row.setVisible(not self._offline_collapsed)
        self._offline_toggle_btn.setText(
            _icons.expand_icon if self._offline_collapsed else _icons.collapse_icon
        )

    def _toggle_filtered_section(self) -> None:
        """Toggle the collapsed state of the FILTERED VARIANTS sub-section."""
        self._filtered_collapsed = not self._filtered_collapsed
        self._filtered_chips_row.setVisible(not self._filtered_collapsed)
        # After expanding, nudge Qt to re-query heightForWidth so the chips row
        # gets the correct height (the layout may have cached 0 while collapsed).
        if not self._filtered_collapsed:
            self._filtered_chips_row.updateGeometry()
        self._filtered_toggle_btn.setText(
            _icons.expand_icon if self._filtered_collapsed else _icons.collapse_icon
        )

    # ------------------------------------------------------------------ #
    # Chip factories                                                       #
    # ------------------------------------------------------------------ #

    def _chip_status_suffix(self, v: ChannelVersion) -> str:
        """Return the status-icon suffix appended to a chip label (preferred/queue/fav/history)."""
        status = ""
        if v.is_preferred:
            status += f" {self.config.preferred_version_icon}"
        if v.in_queue:
            status += f" {self.config.queue_icon}"
        if v.is_favorite:
            status += f" {self.config.favorite_icon}"
        if v.in_history:
            status += f" {self.config.history_icon}"
        return status

    def _chip_label(self, v: ChannelVersion) -> str:
        """Build the chip label text: [source_icon] [region/prefix] [quality].

        Source icon comes from provider_map (set at load() time).  Falls back to
        no icon when provider_map is absent or the provider has no configured icon.

        Suppressed entirely when every chip resolves to the same source (see
        ``_show_source_icons``) — it distinguishes nothing there.
        """
        parts = []
        if v.provider_id and getattr(self, "_show_source_icons", True):
            pm = getattr(self, "_provider_map", {})
            src_icon = pm.get(v.provider_id, {}).get("icon", "")
            if src_icon:
                parts.append(src_icon)
        # Region / prefix label
        prefix = v.detected_prefix or ""
        if prefix:
            full = resolve_category_name(prefix, self.config)
            parts.append(full or prefix)
        # Quality tier — viewer-facing label (RAW → "Uncompressed"); the stored
        # token stays the identity on the ChannelVersion.
        if v.detected_quality:
            parts.append(quality_display(v.detected_quality))
        # Fallback: use prefix raw if nothing else resolved
        if not parts:
            parts.append(v.detected_prefix or "?")
        return " ".join(parts)

    def _chip_tooltip(self, v: ChannelVersion, suffix: str = "") -> str:
        """Build a rich tooltip: source name + region + resolution + status badges."""
        lines = []
        pm = getattr(self, "_provider_map", {})
        src_name = v.provider_name or ""
        if v.provider_id and not src_name:
            src_name = pm.get(v.provider_id, {}).get("name", "")
        if src_name:
            lines.append(f"Source: {src_name}")
        if v.detected_region:
            lines.append(f"Region: {v.detected_region}")
        if v.detected_quality:
            lines.append(f"Quality: {quality_display(v.detected_quality)}")
        if v.is_inactive:
            lines.append("(source is inactive — right-click to reactivate & play)")
        if suffix:
            lines.append(suffix)
        return "\n".join(lines) if lines else v.name

    def _make_active_chip(self, v: ChannelVersion) -> QPushButton:
        """Build an active-source chip that shows details on left-click."""
        # Escape "&" for display — a resolved category name (e.g. "Kids & Family")
        # would otherwise render its "&" as a mnemonic underscore on the button.
        label = escape_mnemonic(self._chip_label(v) + self._chip_status_suffix(v))

        if v.is_inactive:
            # Inactive: dimmed; left-click shows details, right-click offers reactivate & play
            chip = QPushButton(label)
            _theme.style_fn(chip, lambda: f"QPushButton {{ font-size: {_theme.FONT_MD}; color: {_theme.COLOR_DISABLED};"
                f" border: 1px solid {_theme.COLOR_LINE}; border-radius: 4px; padding: 2px 8px;"
                " opacity: 0.6; }"
                f"QPushButton:hover {{ color: {_theme.COLOR_TEXT};"
                f" border-color: {_theme.COLOR_BORDER}; background: {_theme.OVERLAY_04}; }}")
            tip = self._chip_tooltip(v, suffix="Click to show this version's details")
            chip.setToolTip(tip)
            # Left-click → show this variant's details
            chip.clicked.connect(lambda _, cid=v.channel_id: self.version_selected.emit(cid))
        else:
            chip = QPushButton(label)
            _theme.style_fn(chip, lambda: f"QPushButton {{ font-size: {_theme.FONT_MD}; color: {_theme.COLOR_TEXT};"
                f" border: 1px solid {_theme.COLOR_BORDER}; border-radius: 4px; padding: 2px 8px; }}"
                f"QPushButton:hover {{ color: {_theme.COLOR_TEXT_HI};"
                f" border-color: {_theme.COLOR_BORDER}; background: {_theme.OVERLAY_05}; }}")
            tip = self._chip_tooltip(v, suffix="Click to show this version's details")
            chip.setToolTip(tip)
            # Left-click → show this variant's details
            chip.clicked.connect(lambda _, cid=v.channel_id: self.version_selected.emit(cid))

        chip.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        chip.customContextMenuRequested.connect(
            lambda pos, _v=v, _c=chip: self._show_version_chip_menu(_c.mapToGlobal(pos), _v, _c)
        )
        return chip

    def _make_greyed_chip(self, v: ChannelVersion) -> QPushButton:
        """A filtered variant: quieter than an active chip, but just as clickable.

        These are DE-EMPHASIZED, not disabled. Owner: "they're just hidden to
        reduce clutter or distraction, but they still should be clickable when
        Filtered Variants is expanded" — you deliberately expanded the section to
        reach them, so refusing the click is the wrong answer.

        Left-click switches to the variant through the SAME ``version_selected``
        signal an active chip emits, so there is one switch path for both.

        Styling had made the promise the wiring broke: ``COLOR_BORDER`` text is
        ~1.4:1 against the pane, which reads as a disabled control, and there was
        no hover state at all — the two things that tell a user not to bother
        clicking. Now it sits at the readable end of dim with a hover lift, so it
        looks like what it is: available, just not shouting.
        """
        prefix = v.detected_prefix or "?"
        is_hidden_cat = v.is_hidden_category
        extra = "text-decoration: line-through;" if is_hidden_cat else ""
        chip = QPushButton(escape_mnemonic(self._chip_label(v)))
        _theme.style_fn(
            chip,
            lambda _extra=extra: (
                f"QPushButton {{ font-size: {_theme.FONT_MD}; color: {_theme.COLOR_TEXT};"
                f" border: 1px solid {_theme.COLOR_BORDER}; background: transparent;"
                f" border-radius: 4px; padding: 2px 8px; {_extra} }}"
                f"QPushButton:hover {{ color: {_theme.COLOR_TEXT};"
                f" border-color: {_theme.COLOR_BORDER}; }}"
            ),
        )
        cursor_affordance.set_clickable(chip)
        full = resolve_category_name(prefix, self.config)
        reason = "hidden" if is_hidden_cat else "filtered"
        chip.setToolTip(
            f"{full or prefix} ({prefix}) — {reason}. Click to switch to this "
            f"version; right-click to manage."
        )
        chip.clicked.connect(lambda _, cid=v.channel_id: self.version_selected.emit(cid))
        chip.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        chip.customContextMenuRequested.connect(
            lambda pos, p=prefix, hid=is_hidden_cat, _c=chip:
                self._show_filtered_chip_menu(_c.mapToGlobal(pos), p, hid)
        )
        return chip

    # ------------------------------------------------------------------ #
    # Context menus                                                        #
    # ------------------------------------------------------------------ #

    def _show_version_chip_menu(
        self, global_pos, v: ChannelVersion, chip: QPushButton | None = None
    ) -> None:
        prefix = v.detected_prefix or "?"
        full = resolve_category_name(prefix, self.config)
        pm = getattr(self, "_provider_map", {})
        src_name = v.provider_name or pm.get(v.provider_id or "", {}).get("name", "") or ""
        header_parts = [full or prefix]
        if src_name:
            header_parts.append(f"({src_name})")
        header = " ".join(header_parts)

        # Import here to keep the module-level import surface small and to avoid
        # a circular import at load time (glyph_icon calls QPixmap which needs QApplication).
        from metatv.gui.icons import glyph_icon as _glyph_icon

        menu = QMenu(self)
        title_act = menu.addAction(header)
        title_act.setEnabled(False)
        menu.addSeparator()

        if v.is_inactive:
            # Inactive source: offer reactivate & play prominently
            reactivate_act = menu.addAction("Reactivate source & play")
            reactivate_act.setToolTip(f"Re-enable {src_name or prefix} and play this variant")
            reactivate_act.setIcon(_glyph_icon(_icons.play_icon))
            show_act = menu.addAction(f"Show details for {prefix} version")
            show_act.setToolTip(v.name)
            show_act.setIcon(_glyph_icon(_icons.info_icon))
        else:
            play_act = menu.addAction(f"Play {prefix} version")
            play_act.setToolTip(f"Play: {v.name}")
            play_act.setIcon(_glyph_icon(_icons.play_icon))
            show_act = menu.addAction(f"Show details for {prefix} version")
            show_act.setToolTip(v.name)
            show_act.setIcon(_glyph_icon(_icons.info_icon))
        menu.addSeparator()

        fav_act = menu.addAction("Remove from Favorites" if v.is_favorite else "Add to Favorites")
        fav_act.setIcon(_glyph_icon(_icons.unfavorite_icon if v.is_favorite else _icons.favorite_icon))
        queue_act = menu.addAction(
            "Remove from Watch Later" if v.in_queue else "Add to Watch Later"
        )
        queue_act.setIcon(_glyph_icon(_icons.queue_icon))
        if not v.is_inactive:
            hide_act = menu.addAction(f"Hide this {prefix} version")
            hide_act.setToolTip(f"Hides only: {v.name}")
            hide_act.setIcon(_glyph_icon(_icons.hide_icon))
        menu.addSeparator()

        # Admin/destructive rows — no icon (blank column signals a different tier)
        filter_act   = menu.addAction(f'Filter out ALL "{prefix}" content')
        filter_act.setToolTip(f"Deselects {prefix} from Content Categories — easy to undo from filter panel")
        hide_cat_act = menu.addAction(f"Hide the {prefix} category")
        hide_cat_act.setToolTip(f"Suppresses {prefix} entirely — removed from filter options")
        menu.addSeparator()

        edit_act = menu.addAction("Edit Category Name…")

        chosen = menu.exec(global_pos)
        if v.is_inactive:
            if chosen == reactivate_act:
                self.play_version_requested.emit(v.channel_id)
            elif chosen == show_act:
                self.version_selected.emit(v.channel_id)
        else:
            if chosen == play_act:
                self.play_version_requested.emit(v.channel_id)
            elif chosen == show_act:
                self.version_selected.emit(v.channel_id)
            elif chosen == hide_act:
                self.hide_requested.emit(v.channel_id)

        if chosen == fav_act:
            self.favorite_toggled.emit(v.channel_id)
        elif chosen == queue_act:
            self.queue_toggled.emit(v.channel_id)
            # Optimistic flip so the next right-click shows the correct "Add/Remove" label
            # and the chip icon reflects the new queue state immediately.
            v.in_queue = not v.in_queue
            if chip is not None:
                chip.setText(escape_mnemonic(self._chip_label(v) + self._chip_status_suffix(v)))
        elif chosen in (filter_act, hide_cat_act):
            self.prefix_block_requested.emit(prefix)
        elif chosen == edit_act:
            self._show_category_name_popup(prefix, global_pos)

    def _show_filtered_chip_menu(self, global_pos, prefix: str, is_hidden: bool) -> None:
        full = resolve_category_name(prefix, self.config)
        state = "hidden" if is_hidden else "filtered"
        header = f"{full} ({prefix}) — {state}" if full else f"{prefix} — {state}"

        menu = QMenu(self)
        title_act = menu.addAction(header)
        title_act.setEnabled(False)
        menu.addSeparator()

        restore_act = menu.addAction(
            f"Unhide {prefix} category" if is_hidden else f"Remove filter on {prefix} content"
        )
        menu.addSeparator()
        # "Global Exclusions" is the app's one name for this surface — never
        # "filters", which is what this said while emitting into a dead stub.
        manage_act = menu.addAction("Manage Global Exclusions…")

        chosen = menu.exec(global_pos)
        if chosen == restore_act:
            self.prefix_unblock_requested.emit(prefix)
        elif chosen == manage_act:
            self.manage_filters_requested.emit()

    def _show_category_name_popup(self, prefix: str, pos) -> None:
        current = resolve_category_name(prefix, self.config)
        popup = _CategoryNamePopup(prefix, current, self.config, self)
        popup.name_saved.connect(lambda p, n: self.prefix_name_saved.emit(p, n))
        popup.move(pos)
        popup.show()
