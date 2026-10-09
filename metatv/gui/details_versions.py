"""Version chips and category-name types for the details pane."""
import re as _re
from dataclasses import dataclass

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QFrame, QPushButton, QLabel,
    QMenu, QLineEdit,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCursor


from metatv.core.channel_name_utils import (
    normalize_region_code, REGION_FULL_NAMES, AUDIO_LANG_WORD_MAP, quality_display,
)
from metatv.gui import cursor_affordance
from metatv.gui import deferred_config_save as _cfgsave
from metatv.gui import icon_utils as _icon_utils
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.detail_chips import (
    add_quality_badge, display_code, make_chip, make_flow, make_key, make_label_grid,
)
from metatv.gui.details_version_groups import (
    DEFAULT_VISIBLE_REGIONS as VISIBLE_REGIONS,
    GROUPING_THRESHOLD,
    group_by_region,
    summarise,
)
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
    # How THIS source files this copy — tag_decomposer's "collection" facet off
    # the provider category, falling back to the raw category string (DETAILS-3c).
    # Used only for the merge-menu entry text and the filing tooltip; never on
    # the chip's face (that stays display_code(prefix) + quality, see
    # _VersionSection._chip_label).
    collection: str | None = None


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
        save_btn = _icon_utils.icon_button("watched", "Save category name")
        save_btn.setFixedSize(28, 28)
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

class _VersionSection(QWidget):
    """"Available in" — every copy of the current title, the one you're on first.

    Not collapsible (DETAILS-3c): it is a ``detail_chips.make_label_grid()``
    row, key "Available in" in column 0, chips in column 1 — the same grid
    shape as a Facts/Cast row, not a fifth hand-rolled collapsible section.
    The FIRST chip is always the copy ``load()`` was told is currently shown
    (``current``), drawn selected; the rest are every other PLAYABLE copy —
    a source the user has turned off never reaches this widget at all, the
    absolute gate enforced at the loader (``main_window_metadata.py``).

    Over :data:`GROUPING_THRESHOLD` the active copies still group by region
    (``details_version_groups.py``) exactly as before. Below it, and inside
    every opened "Filtered"/"Offline" bucket, copies whose labels are
    otherwise identical collapse into one "label ×N" chip — left-click opens
    a small menu naming each by its collection so the user still picks the
    right one. "Filtered"/"Offline" start closed behind a dashed "+N …" chip
    that ends the Available row; opening one adds its own labelled grid row
    below, remembered per-bucket in ``config.details_pane_open_copy_buckets``.
    """

    version_selected         = pyqtSignal(str)        # channel_id — show details
    play_version_requested   = pyqtSignal(str)        # channel_id — play that variant
    download_requested       = pyqtSignal(str)        # channel_id — save that variant to the library
    favorite_toggled         = pyqtSignal(str)        # channel_id
    queue_toggled            = pyqtSignal(str)        # channel_id
    hide_requested           = pyqtSignal(str)        # channel_id
    prefix_block_requested   = pyqtSignal(str)        # prefix
    prefix_unblock_requested = pyqtSignal(str)        # prefix
    prefix_name_saved        = pyqtSignal(str, str)   # prefix, name
    manage_filters_requested = pyqtSignal()

    #: The two buckets that can be opened/closed and remembered, matching
    #: ``Config.details_pane_open_copy_buckets``.
    _BUCKETS = ("filtered", "offline")

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._current: ChannelVersion | None = None
        self._active_versions: list = []
        self._filtered_versions: list = []
        self._offline_versions: list = []
        self._region_expanded: str | None = None
        self._show_all_regions: bool = False
        self._provider_map: dict = {}
        self._show_source_icons: bool = False
        self._open_buckets: set[str] = set()
        # Every version load() was handed, current + sibling, by channel_id —
        # rebuilt fresh on every load() — so a chip's click/context-menu slot
        # can resolve "which ChannelVersion is this" from a Qt property on
        # the SENDER rather than from a per-chip lambda closure over self
        # (widget-owns-closure-owns-self is a reference cycle the Qt
        # top-level-widget leak guard catches; see _on_chip_clicked).
        self._versions_by_id: dict = {}
        self._preferred_channel_id: str | None = None
        self._setup()

    def _setup(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Preferred version nudge banner (green) — unchanged by DETAILS-3c.
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
        # Connected ONCE, here — never per-load() — and reads the preferred
        # channel id back off self rather than a lambda baked at connect time,
        # so there is one bound-method connection for the button's whole
        # lifetime instead of a fresh closure (over self) on every load().
        self._pref_nudge_switch_btn.clicked.connect(self._on_pref_nudge_clicked)
        nudge_row.addWidget(self._pref_nudge_lbl, 1)
        nudge_row.addWidget(self._pref_nudge_switch_btn)
        self._pref_nudge.hide()
        layout.addWidget(self._pref_nudge)

        # The "Available in" grid (+ any opened bucket rows below it) is
        # rebuilt wholesale on every load()/drill/toggle — see _render(). This
        # body wrapper is what load() hides entirely when there is nothing at
        # all to show (no current copy, no siblings).
        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(4)
        self._body.hide()
        layout.addWidget(self._body)

    # ------------------------------------------------------------------ #
    # Loading                                                              #
    # ------------------------------------------------------------------ #

    def load(
        self,
        versions: list[ChannelVersion],
        provider_map: dict | None = None,
        current: "ChannelVersion | None" = None,
    ) -> None:
        """Rebuild "Available in" from a fresh version list.

        Args:
            versions: Every OTHER playable copy of the current title. A copy
                on a source the user has turned off must never reach here —
                that is enforced at the loader, not here.
            provider_map: Optional ``{provider_id: {"icon", "name", "enabled"}}``
                map from ``DetailsPaneWidget._provider_map``.
            current: The copy already shown in the details pane — drawn as
                the first, selected chip. ``None`` only for a bare clear().
        """
        self._provider_map = provider_map or {}
        self._current = current
        self._pref_nudge.hide()
        self._body.hide()

        offline  = [v for v in versions if v.is_inactive and not v.is_hidden]
        active   = [v for v in versions
                    if not v.is_filtered and not v.is_hidden and not v.is_inactive]
        filtered = [v for v in versions
                    if v.is_filtered and not v.is_hidden and not v.is_inactive]

        self._versions_by_id = {
            v.channel_id: v
            for v in ([current] if current else []) + active + filtered + offline
        }

        # A source glyph is only information when more than one ENABLED
        # source is in play — with one it repeats the same symbol on every
        # chip and crowds out the thing that actually varies (region/quality).
        # provider_map's "enabled" flag is set once, centrally, in
        # MainWindow._refresh_details_provider_map; a provider missing from
        # the map (a stale test double) defaults to enabled so it still counts.
        provider_ids = {
            v.provider_id for v in ([current] if current else []) + active + filtered + offline
            if v.provider_id
        }
        self._show_source_icons = sum(
            1 for pid in provider_ids
            if self._provider_map.get(pid, {}).get("enabled", True)
        ) > 1

        self._active_versions = active
        self._filtered_versions = filtered
        self._offline_versions = offline
        self._region_expanded = None
        self._show_all_regions = False

        stored_open = set(getattr(self.config, "details_pane_open_copy_buckets", None) or [])
        self._open_buckets = stored_open & set(self._BUCKETS)

        preferred = next((v for v in versions if v.is_preferred), None)
        self._preferred_channel_id = preferred.channel_id if preferred else None
        if preferred:
            self._pref_nudge_lbl.setText(
                f"{self.config.preferred_version_icon} Preferred: {preferred.name}"
            )
            self._pref_nudge.show()

        if current is None and not active and not filtered and not offline:
            self._clear_body()
            return

        self._render()
        self._body.show()

    def clear(self) -> None:
        self.load([])

    def _on_pref_nudge_clicked(self) -> None:
        if self._preferred_channel_id:
            self.version_selected.emit(self._preferred_channel_id)

    # ------------------------------------------------------------------ #
    # Rendering — rebuilt wholesale on every load()/drill/bucket toggle    #
    # ------------------------------------------------------------------ #

    def _clear_body(self) -> None:
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _render(self) -> None:
        self._clear_body()

        grouped = len(self._active_versions) > GROUPING_THRESHOLD
        active_chips = self._build_region_chips() if grouped else self._build_flat_chips(
            self._active_versions, dashed=False, colour_token="COLOR_TEXT",
            tooltip_fn=self._chip_tooltip, menu="version",
        )

        row0 = []
        current_chip = self._build_current_chip()
        if current_chip is not None:
            row0.append(current_chip)
        row0.extend(active_chips)
        for word, bucket in (("filtered", self._filtered_versions), ("offline", self._offline_versions)):
            if bucket and word not in self._open_buckets:
                row0.append(self._make_bucket_summary_chip(word, len(bucket)))

        grid_widget, grid = make_label_grid()
        key = make_key("Available in")
        if grouped:
            key.setToolTip(summarise(group_by_region(self._active_versions)))
        grid.addWidget(key, 0, 0, Qt.AlignmentFlag.AlignTop)
        grid.addWidget(make_flow(row0), 0, 1)

        row_index = 1
        for word, bucket in (("filtered", self._filtered_versions), ("offline", self._offline_versions)):
            if not bucket or word not in self._open_buckets:
                continue
            tooltip_fn = self._filtered_why_tooltip if word == "filtered" else self._offline_why_tooltip
            chips = self._build_flat_chips(
                bucket, dashed=True, colour_token="COLOR_MUTED", tooltip_fn=tooltip_fn,
                menu="filtered" if word == "filtered" else "version",
            )
            grid.addWidget(self._make_bucket_key(word, len(bucket)), row_index, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(make_flow(chips), row_index, 1)
            row_index += 1

        self._body_layout.addWidget(grid_widget)

    def _build_current_chip(self) -> "QPushButton | None":
        if self._current is None:
            return None
        chip = make_chip(self._chip_label(self._current), "COLOR_TEXT_HI", selected=True, bold=True)
        add_quality_badge(chip, "COLOR_TEXT_HI", bold=True)
        chip.setToolTip(self._chip_tooltip(self._current, "The copy shown above"))
        return chip

    # ------------------------------------------------------------------ #
    # Region grid (active copies, over GROUPING_THRESHOLD)                 #
    # ------------------------------------------------------------------ #

    def _build_region_chips(self) -> list:
        """Region-group chips, or one drilled-in region's own copies.

        Two states, one renderer — drilling in replaces row 0's active
        chips rather than opening anything, so the pane never changes height
        under the pointer. No version is ever dropped (details_version_groups).
        """
        groups = group_by_region(self._active_versions)

        if self._region_expanded is not None:
            group = next((g for g in groups if g.code == self._region_expanded), None)
            if group is not None:
                return [self._make_back_chip(group)] + self._build_flat_chips(
                    list(group.versions), dashed=False, colour_token="COLOR_TEXT",
                    tooltip_fn=self._chip_tooltip, menu="version",
                )
            # The region vanished under us (a reload with different data).
            self._region_expanded = None

        shown = groups if self._show_all_regions else groups[:VISIBLE_REGIONS]
        chips = [self._make_region_chip(group) for group in shown]
        hidden = len(groups) - len(shown)
        if hidden > 0:
            chips.append(self._make_more_chip(hidden))
        return chips

    def _make_region_chip(self, group) -> QPushButton:
        """One region: its full name, code, and how many versions are in it."""
        chip = QPushButton(escape_mnemonic(f"{display_code(group.code, self.config)} · {group.count}"))
        chip.setFlat(True)
        _theme.style(chip, "DETAIL_REGION_CHIP")
        cursor_affordance.set_clickable(chip)
        name = resolve_category_name(group.code, self.config) or group.code
        lines = [f"{name} — {group.count} version{'s' if group.count != 1 else ''}"]
        if group.qualities:
            lines.append("Quality: " + ", ".join(
                quality_display(q) for q in group.qualities
            ))
        lines.append("Click to see them")
        chip.setToolTip("\n".join(lines))
        # The region code lives on the chip (a Qt property), read back by ONE
        # shared bound slot via self.sender() — not a per-chip lambda closing
        # over self, which is a widget<->closure reference cycle the Qt
        # top-level-widget leak guard catches.
        chip.setProperty("cv_region_code", group.code)
        chip.clicked.connect(self._on_region_chip_clicked)
        return chip

    def _make_more_chip(self, hidden: int) -> QPushButton:
        chip = make_chip(f"+{hidden} more regions", "COLOR_TEXT", dashed=True)
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

    def _on_region_chip_clicked(self) -> None:
        chip = self.sender()
        code = chip.property("cv_region_code") if chip is not None else None
        if code:
            self._expand_region(code)

    def _expand_region(self, code: str) -> None:
        self._region_expanded = code
        self._render()

    def _collapse_region(self) -> None:
        self._region_expanded = None
        self._render()

    def _show_every_region(self) -> None:
        self._show_all_regions = True
        self._render()

    # ------------------------------------------------------------------ #
    # Bucket open/close (Filtered / Offline) — persisted per bucket        #
    # ------------------------------------------------------------------ #

    def _make_bucket_summary_chip(self, word: str, n: int) -> QPushButton:
        chip = make_chip(f"+{n} {word}", "COLOR_TEXT", dashed=True)
        chip.setToolTip(f"Show the {n} {word} copies")
        chip.setProperty("cv_bucket", word)
        chip.clicked.connect(self._on_bucket_toggle_clicked)
        return chip

    def _make_bucket_key(self, word: str, n: int) -> QPushButton:
        """The "Filtered"/"Offline" row key — clicking it folds the row back
        into its "+N …" chip. Looks like ``make_key``'s plain label (same
        DETAIL_SECTION_SUMMARY colour/size, transparent, no border) with a
        hover state added, since this one — unlike every other key in the
        pane — is itself a button.
        """
        key = QPushButton(word.title())
        key.setFlat(True)
        key.setFixedHeight(make_chip("x").sizeHint().height())
        _theme.style_fn(key, _bucket_key_sheet)
        cursor_affordance.set_clickable(key)
        key.setToolTip(f"Collapse the {n} {word} copies")
        key.setProperty("cv_bucket", word)
        key.setProperty("cv_bucket_action", "close")
        key.clicked.connect(self._on_bucket_toggle_clicked)
        return key

    def _on_bucket_toggle_clicked(self) -> None:
        chip = self.sender()
        if chip is None:
            return
        word = chip.property("cv_bucket")
        if not word:
            return
        if chip.property("cv_bucket_action") == "close":
            self._close_bucket(word)
        else:
            self._open_bucket(word)

    def _open_bucket(self, word: str) -> None:
        self._open_buckets.add(word)
        self._save_open_buckets()
        self._render()

    def _close_bucket(self, word: str) -> None:
        self._open_buckets.discard(word)
        self._save_open_buckets()
        self._render()

    def _save_open_buckets(self) -> None:
        self.config.details_pane_open_copy_buckets = sorted(self._open_buckets)
        _cfgsave.save_soon(self)

    # ------------------------------------------------------------------ #
    # Chip label, tooltips, merge                                         #
    # ------------------------------------------------------------------ #

    def _chip_label(self, v: ChannelVersion) -> str:
        """The chip's FACE text: ``display_code(prefix) + quality token``.

        No collection, no status glyphs — those used to tell two same-prefix
        chips apart; the new design merges genuinely-identical labels into
        one "×N" chip instead (see :meth:`_build_flat_chips`) and leaves
        disambiguation to that chip's picker menu. The source icon prefixes
        the label only when more than one source is ENABLED
        (``_show_source_icons``, set once in :meth:`load`).
        """
        prefix = v.detected_prefix or ""
        name = display_code(prefix, self.config) if prefix else "?"
        if v.detected_quality:
            name = f"{name} {v.detected_quality}"
        icon = ""
        if v.provider_id and self._show_source_icons:
            icon = self._provider_map.get(v.provider_id, {}).get("icon", "")
        return f"{icon} {name}" if icon else name

    def _filing_parts(self, v: ChannelVersion) -> list[str]:
        prov = v.provider_name or self._provider_map.get(v.provider_id or "", {}).get("name", "") or ""
        return [p for p in (v.collection, prov) if p]

    def _chip_tooltip(self, v: ChannelVersion, action: str = "Click to show this copy") -> str:
        """"<collection or category> · <provider>" + the click hint."""
        filing = " · ".join(self._filing_parts(v))
        return f"{filing}\n{action}" if filing else action

    def _menu_entry_text(self, v: ChannelVersion) -> str:
        parts = self._filing_parts(v)
        return escape_mnemonic(" · ".join(parts)) if parts else escape_mnemonic(v.name)

    def _merge_tooltip(self, n: int) -> str:
        return f"{n} copies — click to choose one (each listed by its collection)"

    def _filtered_why_tooltip(self, v: ChannelVersion) -> str:
        prefix = v.detected_prefix or ""
        reason = display_code(prefix, self.config) if prefix else "this content"
        return f"Hidden by your filters — {reason}"

    def _offline_why_tooltip(self, v: ChannelVersion) -> str:
        prov = v.provider_name or self._provider_map.get(v.provider_id or "", {}).get("name", "") or "This source"
        return f"{prov} has expired"

    def _build_flat_chips(
        self, versions: list, *, dashed: bool, colour_token: str, tooltip_fn, menu: str,
    ) -> list:
        """One chip per DISTINCT label; identical labels merge into "×N".

        ``menu`` selects the right-click behaviour: ``"version"`` wires the
        full channel context menu (play/favorite/queue/hide/reactivate —
        ``_show_version_chip_menu``); ``"filtered"`` wires the lighter
        category-level menu (``_show_filtered_chip_menu``). A merged chip's
        right-click acts on its FIRST member — every member already shares
        one label, which for a region/quality pair means one prefix, so the
        prefix-level admin actions are the same action for any of them.

        Every chip's click/context-menu data (which channel(s), which menu
        kind) lives on the chip itself as a Qt property, read back by the
        TWO shared bound slots below via ``self.sender()`` — never a
        per-chip lambda closing over ``self``, which is a widget<->closure
        reference cycle the Qt top-level-widget leak guard catches.
        """
        groups: dict[str, list] = {}
        order: list[str] = []
        for v in versions:
            label = self._chip_label(v)
            if label not in groups:
                groups[label] = []
                order.append(label)
            groups[label].append(v)

        chips = []
        for label in order:
            members = groups[label]
            anchor = members[0]
            text = f"{label} ×{len(members)}" if len(members) > 1 else label
            chip = make_chip(text, colour_token, dashed=dashed)
            add_quality_badge(chip, colour_token)
            chip.setProperty("cv_cid", anchor.channel_id)
            chip.setProperty("cv_menu_kind", menu)
            if len(members) > 1:
                chip.setToolTip(self._merge_tooltip(len(members)))
                chip.setProperty("cv_merge_cids", ",".join(m.channel_id for m in members))
            else:
                chip.setToolTip(tooltip_fn(anchor))
            chip.clicked.connect(self._on_chip_clicked)
            chip.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            chip.customContextMenuRequested.connect(self._on_chip_context_menu)
            chips.append(chip)
        return chips

    def _on_chip_clicked(self) -> None:
        """Shared left-click slot for every Available/Filtered/Offline chip.

        A merged "×N" chip opens the picker menu; anything else shows that
        one copy's details — decided from the Qt properties
        :meth:`_build_flat_chips` set on the SENDER, never from per-chip
        bound data (see that method's docstring).
        """
        chip = self.sender()
        if chip is None:
            return
        merge_cids = chip.property("cv_merge_cids")
        if merge_cids:
            members = [
                self._versions_by_id[cid] for cid in merge_cids.split(",")
                if cid in self._versions_by_id
            ]
            if members:
                self._show_merge_menu(members)
            return
        cid = chip.property("cv_cid")
        if cid:
            self.version_selected.emit(cid)

    def _on_chip_context_menu(self, pos) -> None:
        """Shared right-click slot — resolves the chip's ANCHOR version and
        dispatches to the version- or filtered-level menu per ``cv_menu_kind``."""
        chip = self.sender()
        if chip is None:
            return
        cid = chip.property("cv_cid")
        v = self._versions_by_id.get(cid) if cid else None
        if v is None:
            return
        if chip.property("cv_menu_kind") == "filtered":
            self._show_filtered_chip_menu(
                chip.mapToGlobal(pos), v.detected_prefix or "?", v.is_hidden_category
            )
        else:
            self._show_version_chip_menu(chip.mapToGlobal(pos), v, chip)

    def _show_merge_menu(self, members: list) -> None:
        """Left-click on a "label ×N" chip: pick which copy to show."""
        menu = QMenu(self)
        actions = {}
        for v in members:
            act = menu.addAction(self._menu_entry_text(v))
            actions[act] = v.channel_id
        chosen = menu.exec(QCursor.pos())
        menu.deleteLater()
        if chosen is not None and chosen in actions:
            self.version_selected.emit(actions[chosen])

    # ------------------------------------------------------------------ #
    # Context menus                                                        #
    # ------------------------------------------------------------------ #

    def _show_version_chip_menu(
        self, global_pos, v: ChannelVersion, chip: QPushButton | None = None
    ) -> None:
        """Right-click a version chip: play/details/favorite/queue via the
        registry ("versions" surface), plus prefix/category-level admin rows
        (hide this version, filter/hide the whole category, rename it) that
        stay hand-appended — a normalization-code axis, not a single channel,
        same rationale as ``_show_filtered_chip_menu`` below.
        """
        from metatv.gui.channel_menu import ChannelMenuContext, build_channel_menu

        prefix = v.detected_prefix or "?"
        full = resolve_category_name(prefix, self.config)
        pm = getattr(self, "_provider_map", {})
        src_name = v.provider_name or pm.get(v.provider_id or "", {}).get("name", "") or ""
        header_parts = [full or prefix]
        if src_name:
            header_parts.append(f"({src_name})")
        header = " ".join(header_parts)

        def _toggle_queue() -> None:
            self.queue_toggled.emit(v.channel_id)
            # Optimistic flip so the next right-click shows the correct "Add/Remove"
            # label.
            v.in_queue = not v.in_queue

        ctx = ChannelMenuContext(
            channel_ids=[v.channel_id],
            surface="versions",
            header=header,
            version_prefix=prefix,
            source_inactive=v.is_inactive,
            is_favorite=v.is_favorite,
            in_queue=v.in_queue,
            channel_name=v.name,
            media_type=v.media_type,
            channel_found=True,
        )
        handlers = {
            "play": lambda: self.play_version_requested.emit(v.channel_id),
            "download": lambda: self.download_requested.emit(v.channel_id),
            "reactivate_play": lambda: self.play_version_requested.emit(v.channel_id),
            "show_details": lambda: self.version_selected.emit(v.channel_id),
            "favorite": lambda: self.favorite_toggled.emit(v.channel_id),
            "queue": _toggle_queue,
        }
        menu = build_channel_menu(ctx, handlers, parent=self)

        hide_act = None
        if not v.is_inactive:
            menu.addSeparator()
            hide_act = menu.addAction(f"Hide this {prefix} version")
            hide_act.setToolTip(f"Hides only: {v.name}")
            hide_act.setIcon(_icons.glyph_icon(_icons.hide_icon))
        menu.addSeparator()

        # Admin/destructive rows — no icon (blank column signals a different tier)
        filter_act   = menu.addAction(f'Filter out ALL "{prefix}" content')
        filter_act.setToolTip(f"Deselects {prefix} from Content Categories — easy to undo from filter panel")
        hide_cat_act = menu.addAction(f"Hide the {prefix} category")
        hide_cat_act.setToolTip(f"Suppresses {prefix} entirely — removed from filter options")
        menu.addSeparator()

        edit_act = menu.addAction("Edit Category Name…")

        chosen = menu.exec(global_pos)
        menu.deleteLater()
        if chosen == hide_act:
            self.hide_requested.emit(v.channel_id)
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
        menu.deleteLater()
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


def _bucket_key_sheet() -> str:
    """The "Filtered"/"Offline" fold-back key's stylesheet: DETAIL_SECTION_SUMMARY's
    own colour/size/background — the role every other key in the pane uses —
    plus a hover state, since this key (alone among them) is a button.
    """
    return (
        f"QPushButton {{ color: {_theme.COLOR_TEXT}; font-size: {_theme.FONT_SM};"
        f" background: transparent; border: none; padding: 0; text-align: left; }}"
        f"QPushButton:hover {{ color: {_theme.COLOR_ACCENT}; }}"
    )
