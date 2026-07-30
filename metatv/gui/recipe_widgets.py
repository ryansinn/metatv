"""Recipe view helper widgets — cluster grid, Tonight's Recipe rail, Now Plating grid.

Extracted from ``recipe_view.py`` (which exceeded the 1000-line file limit) so
that file holds only the :class:`RecipeView` host.  Everything here is a leaf
presentation widget or a pure helper (facet metadata, editorial name generator,
layout clearing) — no DB access, no async seam.  ``recipe_view`` re-exports these
names for backward compatibility, so existing imports keep resolving.

Split follows the same convention as the EPG view (``epg_widgets.py`` /
``epg_*_mixin.py``): one cohesive concern per file, re-exported from the host.
"""

from __future__ import annotations

import random
import re

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.weighted_tag_cloud import (
    _CloudBody,
    _TagButton,
    _count_to_font_token,
)


# ---------------------------------------------------------------------------
# Facet display config: name, color token, role label for the recipe rail
# ---------------------------------------------------------------------------

# Maps facet_type → (display_name, color_token, role_label)
# "category" (live-channel kind: Sports/News/Kids…) sits immediately before
# "genre" — both are content descriptors; category is the live-channel variant.
_FACET_META: dict[str, tuple[str, str, str]] = {
    "category":   ("Category",      _theme.COLOR_FACET_CATEGORY,   "KIND"),
    "genre":      ("Genre",         _theme.COLOR_FACET_GENRE,      "BASE"),
    "language":   ("Language",      _theme.COLOR_FACET_LANGUAGE,   "IN"),
    "subtitle":   ("Subtitle Lang", _theme.COLOR_FACET_SUBTITLE,   "IN"),
    "dub":        ("Dub Lang",      _theme.COLOR_FACET_DUB,        "IN"),
    "format":     ("Audio Format",  _theme.COLOR_FACET_FORMAT,     "AUDIO"),
    "region":     ("Region",        _theme.COLOR_FACET_REGION,     "FROM"),
    "platform":   ("Platform",      _theme.COLOR_FACET_PLATFORM,   "ON"),
    "decade":     ("Decade",        _theme.COLOR_FACET_DECADE,     "ERA"),
    "quality":    ("Quality",       _theme.COLOR_FACET_QUALITY,    "FINISH"),
    "collection": ("Collection",    _theme.COLOR_FACET_COLLECTION, "SET"),
}

# Role display order in the recipe rail
_ROLE_ORDER: list[str] = ["KIND", "BASE", "IN", "AUDIO", "FROM", "ON", "ERA", "FINISH", "SET"]


def _facet_color(facet_type: str) -> str:
    """Return the theme color token for a facet type, falling back to COLOR_TEXT."""
    return _FACET_META.get(facet_type, ("", _theme.COLOR_TEXT, ""))[1]


def _facet_display(facet_type: str) -> str:
    """Return the human-readable display name for a facet type."""
    return _FACET_META.get(facet_type, (facet_type.title(), "", ""))[0]


def _facet_role(facet_type: str) -> str:
    """Return the role label (BASE/IN/FROM…) for a facet type."""
    return _FACET_META.get(facet_type, ("", "", "OTHER"))[2]


# ---------------------------------------------------------------------------
# Editorial recipe name generator
# ---------------------------------------------------------------------------

_ADJECTIVES = [
    "Late-Night", "Slow-Burn", "Cult", "Vintage", "Arthouse", "Binge-worthy",
    "Noir", "Golden-Era", "Hidden-Gem", "Comfort", "Discovery", "Weekend",
]
_NOUNS = [
    "Selection", "Collection", "Offering", "Mix", "Lineup", "Playlist",
    "Showcase", "Blend", "Curation", "Feature",
]


def _generate_recipe_name(
    includes: dict[str, set[str]],
    excludes: dict[str, set[str]],
) -> str:
    """Auto-generate an editorial recipe name from current ingredients.

    Uses the genre (if any) as the anchor noun; pads with an adjective when the
    recipe has ingredients, or returns a placeholder when empty.  The adjective/
    noun choice is seeded by the recipe's contents, so the name is *stable* for a
    given set of ingredients — it only changes when the ingredients change, never
    on an unrelated re-render.

    Args:
        includes: Mapping of facet_type → set of included values.
        excludes: Mapping of facet_type → set of excluded values.

    Returns:
        A short editorial string, e.g. "Late-Night Drama Selection".
    """
    # Collect all included values across facets
    all_includes = [v for vals in includes.values() for v in vals]
    all_excludes = [v for vals in excludes.values() for v in vals]
    if not all_includes and not all_excludes:
        return "Your recipe is empty"

    # Seed a local RNG by the recipe contents so the name is deterministic.
    rng = random.Random(repr((sorted(all_includes), sorted(all_excludes))))

    genres = sorted(includes.get("genre", set()))
    decades = sorted(includes.get("decade", set()))

    parts: list[str] = []
    if decades:
        parts.append(decades[0])
    if genres:
        parts.append(genres[0])
    else:
        parts.append(rng.choice(_ADJECTIVES))

    parts.append(rng.choice(_NOUNS))
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Default cluster grid: per-facet mini tag-clouds ("clusters")
# ---------------------------------------------------------------------------

# The Recipe builder's DEFAULT overview shows a mini weighted tag-cloud for each
# facet at once (a "cluster"), replacing the old one-facet-at-a-time pantry list.
#   MAIN tiles  — the roomy, high-coverage browse facets (always shown).
#   MORE tiles  — the low-cardinality tail, tucked in a collapsible "More facets"
#                 section (mirror-not-cage: reachable, not hidden).  Any facet in
#                 neither list is still reachable via the cross-facet search box.
_CLUSTER_FACETS: tuple[str, ...] = ("genre", "region", "language", "collection", "decade")
_MORE_FACETS: tuple[str, ...] = ("quality", "platform", "format", "subtitle")
_ALL_CLUSTER_FACETS: tuple[str, ...] = _CLUSTER_FACETS + _MORE_FACETS

# Top-N tag values requested per facet for the overview (small facets return all).
_CLUSTER_LIMIT_PER_FACET: int = 24

# Minimum tile width (px) used to compute the responsive column count.
_CLUSTER_TILE_MIN_W: int = 300


def _decade_sort_key(value: str) -> int:
    """Chronological sort key for a decade tag value (``"1990s"`` → ``1990``).

    Decade tiles order their chips by era, not by catalogue weight — the single
    special-case in decision 2; a non-numeric value sorts last.
    """
    m = re.match(r"\s*(\d{3,4})", value or "")
    return int(m.group(1)) if m else 9999


class _TagSearchBar(QWidget):
    """Cross-facet tag search box shown above the cluster grid.

    Replaces the retired Pantry search row.  Emits ``search_changed(text)`` —
    empty immediately (so clearing restores the grid without an idle wait),
    non-empty debounced so fast typing coalesces into one DB round-trip.
    """

    search_changed = pyqtSignal(str)   # debounced search text (stripped)

    _SEARCH_DEBOUNCE_MS: int = 220

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(self._SEARCH_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._emit)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self._box = QLineEdit()
        self._box.setPlaceholderText("Search tags across all facets…")
        self._box.setToolTip("Search tag values across every facet at once")
        self._box.setClearButtonEnabled(True)
        self._box.setFixedWidth(240)
        self._box.textChanged.connect(self._on_text)
        row.addWidget(self._box)

    # ── public ────────────────────────────────────────────────────────────

    def text(self) -> str:
        return self._box.text()

    def clear(self) -> None:
        """Clear the search box (restores the cluster grid)."""
        self._box.clear()

    # ── private ───────────────────────────────────────────────────────────

    def _on_text(self, text: str) -> None:
        if not text.strip():
            self._debounce.stop()
            self.search_changed.emit("")
        else:
            self._debounce.start()

    def _emit(self) -> None:
        self.search_changed.emit(self._box.text().strip())


class _SavedRecipesPanel(QWidget):
    """The "SAVED RECIPES" section (stub) — column 1, under Tonight's Recipe.

    Extracted from the retired Pantry sidebar so column 1 keeps only the recipe
    rail + saved recipes after the cluster-grid redesign (decision 3).  Slice 4
    populates this with real saved recipes.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(_theme.RECIPE_PANTRY_BG)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 10, 8, 8)
        outer.setSpacing(0)

        hdr = QLabel("SAVED RECIPES")
        hdr.setStyleSheet(_theme.RECIPE_PANTRY_HDR)
        outer.addWidget(hdr)

        stub = QLabel("No saved recipes yet")
        stub.setStyleSheet(
            f"color: {_theme.COLOR_RECIPE_MUTED_2}; font-size: {_theme.FONT_MD};"
            " padding: 4px 8px;"
        )
        stub.setToolTip("Saving recipes will be available in a future update")
        outer.addWidget(stub)
        outer.addStretch()


class _ClusterTile(QFrame):
    """One facet's mini weighted tag-cloud in the default overview grid.

    Header = the facet name (clickable → drill into that facet's full cloud; the
    labelled header is the non-color a11y cue per decision 5).  Body = the
    facet's top-N values as weighted tag buttons, font-size normalized WITHIN
    this tile (its own min/max) so a small facet isn't erased by a global scale.
    Clicking a tag adds it to the recipe without leaving the overview.  The decade
    tile orders its chips chronologically (decision 2), every other tile by weight.

    Reuses the shared cloud primitives (``_TagButton`` / ``_count_to_font_token``
    / ``_CloudBody``) so a cluster renders identically to the full cloud and the
    Pantry search cloud — one renderer, never a parallel one.
    """

    facet_clicked = pyqtSignal(str)         # facet_type — drill into the full cloud
    tag_clicked   = pyqtSignal(str, str)    # (facet_type, value) — add an ingredient

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("clusterTile")
        self.setStyleSheet(_theme.RECIPE_CLUSTER_TILE)
        self._facet: str = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 10)
        outer.setSpacing(4)

        hdr_row = QHBoxLayout()
        hdr_row.setContentsMargins(0, 0, 0, 0)
        hdr_row.setSpacing(6)
        self._hdr_btn = QPushButton("")
        self._hdr_btn.setFlat(True)
        self._hdr_btn.clicked.connect(self._emit_facet)
        hdr_row.addWidget(self._hdr_btn)
        self._sub_lbl = QLabel("")
        self._sub_lbl.setStyleSheet(_theme.RECIPE_CLUSTER_SUBTITLE)
        hdr_row.addWidget(self._sub_lbl)
        hdr_row.addStretch()
        outer.addLayout(hdr_row)

        self._body = _CloudBody()
        outer.addWidget(self._body)

    # ── public ────────────────────────────────────────────────────────────

    def facet_type(self) -> str:
        return self._facet

    def set_data(
        self,
        facet: str,
        items: list,
        includes: set,
        excludes: set,
    ) -> None:
        """Render *facet*'s top-N ``TagCountDTO`` list with current recipe marks."""
        self._facet = facet
        color = _facet_color(facet)
        display = _facet_display(facet)

        # Labelled, facet-colored header (word = the non-color cue; color = accent).
        self._hdr_btn.setText(display)
        self._hdr_btn.setStyleSheet(
            f"QPushButton {{ border: none; background: transparent; color: {color};"
            f" font-size: {_theme.FONT_LG}; font-weight: bold; text-align: left;"
            f" padding: 2px 0; }}"
            f"QPushButton:hover {{ text-decoration: underline; }}"
        )
        self._hdr_btn.setToolTip(f"Browse all {display} tags")
        self._sub_lbl.setText(f"· {len(items)}")

        # Decade orders chronologically; every other facet keeps the engine's
        # count-DESC order.
        ordered = (
            sorted(items, key=lambda d: _decade_sort_key(d.value))
            if facet == "decade"
            else list(items)
        )

        # content_type slugs render friendly labels; identity stays the slug.
        display_map: dict[str, str] = {}
        if facet == "content_type":
            from metatv.core.channel_name_utils import content_type_display
            display_map = {d.value: content_type_display(d.value) for d in ordered}

        # Normalize font size WITHIN this tile (its own min/max), per decision 5.
        counts = [d.channel_count for d in ordered] or [1]
        mn, mx = min(counts), max(counts)

        self._body.flow().clear()
        for dto in ordered:
            if dto.value in includes:
                state = "include"
            elif dto.value in excludes:
                state = "exclude"
            else:
                state = "none"
            token = _count_to_font_token(dto.channel_count, mn, mx)
            btn = _TagButton(
                dto.value, dto.channel_count, state, token, color,
                facet_type=facet, display=display_map.get(dto.value),
            )
            btn.clicked.connect(self._make_handler(dto.value))
            self._body.flow().add(btn)
        self._body.refresh_layout()

    # ── private ───────────────────────────────────────────────────────────

    def _emit_facet(self) -> None:
        self.facet_clicked.emit(self._facet)

    def _make_handler(self, value: str):
        def _h() -> None:
            self.tag_clicked.emit(self._facet, value)
        return _h


class _ClusterGrid(QWidget):
    """Responsive grid of per-facet cluster tiles + a collapsible "More facets".

    The Recipe builder's default overview.  Main (roomy) facets fill a responsive
    grid whose column count tracks the available width (landscape-first); the
    low-cardinality tail lives under a collapsible "▸ More facets" header whose
    expand state persists to Config.

    Emits ``facet_selected`` (drill into a facet's full cloud), ``tag_clicked``
    (add an ingredient without leaving the overview), and ``more_facets_toggled``
    (so the host can persist the collapse state).
    """

    facet_selected      = pyqtSignal(str)        # facet_type — drill into the full cloud
    tag_clicked         = pyqtSignal(str, str)   # (facet_type, value)
    more_facets_toggled = pyqtSignal(bool)       # persist "More facets" expand state

    def __init__(self, more_expanded: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._more_expanded = bool(more_expanded)
        self._data: dict[str, list] = {}
        self._includes: dict[str, set] = {}
        self._excludes: dict[str, set] = {}
        self._main_tiles: list[_ClusterTile] = []
        self._more_tiles: list[_ClusterTile] = []
        self._build_ui()

    # ── public ────────────────────────────────────────────────────────────

    def set_more_expanded(self, expanded: bool) -> None:
        """Restore the persisted "More facets" expand state (no signal)."""
        self._more_expanded = bool(expanded)
        self._apply_more_visibility()

    def set_clusters(
        self,
        data: dict[str, list],
        includes: dict[str, set],
        excludes: dict[str, set],
    ) -> None:
        """Render the per-facet tiles from ``{facet: [TagCountDTO, …]}`` + recipe marks."""
        self._data = data or {}
        self._includes = includes or {}
        self._excludes = excludes or {}
        self._rebuild()

    def tiles(self) -> list:
        """All rendered tiles (main + more) — for tests/introspection."""
        return list(self._main_tiles) + list(self._more_tiles)

    # ── private ───────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 8, 12, 8)
        outer.setSpacing(8)

        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(10)
        outer.addWidget(self._grid_host)

        # Empty / loading placeholder (shown until the async cluster load lands).
        self._placeholder = QLabel("Loading facets…")
        self._placeholder.setStyleSheet(
            f"color: {_theme.COLOR_RECIPE_MUTED_2}; font-size: {_theme.FONT_MD};"
            " padding: 8px 2px;"
        )
        outer.addWidget(self._placeholder)

        # Collapsible "▸ More facets" section (icons.expand_icon/collapse_icon).
        self._more_btn = QPushButton("")
        self._more_btn.setStyleSheet(_theme.RECIPE_MORE_FACETS_BTN)
        self._more_btn.clicked.connect(self._toggle_more)
        outer.addWidget(self._more_btn)

        self._more_host = QWidget()
        self._more_grid = QGridLayout(self._more_host)
        self._more_grid.setContentsMargins(0, 0, 0, 0)
        self._more_grid.setSpacing(10)
        outer.addWidget(self._more_host)

        outer.addStretch()

        self._more_btn.hide()
        self._more_host.hide()

    def _rebuild(self) -> None:
        for t in self._main_tiles + self._more_tiles:
            t.deleteLater()
        self._main_tiles = []
        self._more_tiles = []

        for facet in _CLUSTER_FACETS:
            items = self._data.get(facet)
            if items:
                self._main_tiles.append(self._make_tile(facet, items))
        for facet in _MORE_FACETS:
            items = self._data.get(facet)
            if items:
                self._more_tiles.append(self._make_tile(facet, items))

        has_any = bool(self._main_tiles or self._more_tiles)
        self._placeholder.setVisible(not has_any)
        self._placeholder.setText("No facets to show yet" if self._data else "Loading facets…")

        self._more_btn.setVisible(bool(self._more_tiles))
        self._apply_more_visibility()
        self._relayout()

    def _make_tile(self, facet: str, items: list) -> "_ClusterTile":
        tile = _ClusterTile()
        tile.set_data(
            facet, items,
            self._includes.get(facet, set()),
            self._excludes.get(facet, set()),
        )
        tile.facet_clicked.connect(self.facet_selected)
        tile.tag_clicked.connect(self.tag_clicked)
        return tile

    def _cols(self) -> int:
        w = self.width()
        if w <= 0 and self.parentWidget() is not None:
            w = self.parentWidget().width()
        if w <= 0:
            w = 900
        return max(1, min(3, w // _CLUSTER_TILE_MIN_W))

    def _relayout(self) -> None:
        cols = self._cols()
        self._place(self._grid, self._main_tiles, cols)
        self._place(self._more_grid, self._more_tiles, cols)

    @staticmethod
    def _place(grid: QGridLayout, tiles: list, cols: int) -> None:
        while grid.count():
            item = grid.takeAt(0)
            w = item.widget()
            if w is not None:
                grid.removeWidget(w)
        for i, tile in enumerate(tiles):
            grid.addWidget(tile, i // cols, i % cols)
            tile.show()

    def _apply_more_visibility(self) -> None:
        n = len(self._more_tiles)
        chevron = _icons.collapse_icon if self._more_expanded else _icons.expand_icon
        self._more_btn.setText(f"{chevron} More facets ({n})")
        self._more_btn.setToolTip(
            "Hide the low-cardinality facets"
            if self._more_expanded
            else "Show more facets (quality, platform, audio format, subtitles)"
        )
        self._more_host.setVisible(self._more_expanded and n > 0)

    def _toggle_more(self) -> None:
        self._more_expanded = not self._more_expanded
        self._apply_more_visibility()
        self.more_facets_toggled.emit(self._more_expanded)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._relayout()


# ---------------------------------------------------------------------------
# Recipe rail (right column)
# ---------------------------------------------------------------------------

class _RecipeRail(QWidget):
    """Right-column rail showing ingredient chips grouped by role.

    Emits ``ingredient_remove_requested(facet_type, value, state)`` when an
    ingredient chip is clicked (cycles back through the include→exclude→none
    cycle by signalling the parent to remove it).
    """

    ingredient_remove_requested = pyqtSignal(str, str)  # (facet_type, value)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(328)
        self.setStyleSheet(_theme.RECIPE_RAIL_BG)
        self._build_ui()

    # ── public ────────────────────────────────────────────────────────────

    def update_recipe(
        self,
        includes: dict[str, set[str]],
        excludes: dict[str, set[str]],
        match_count: int | None,
    ) -> None:
        """Re-render the recipe rail with the current recipe state.

        Args:
            includes: facet_type → set of included values.
            excludes: facet_type → set of excluded values.
            match_count: Number of matching channels for the YIELDS display, or
                ``None`` when the count is still pending (shows "counting…").
        """
        # Update editorial name
        name = _generate_recipe_name(includes, excludes)
        self._name_lbl.setText(name)

        # Clear ingredient area
        _clear_layout(self._ingredients_layout)

        has_ingredients = False

        # Render include groups by role order
        for role in _ROLE_ORDER:
            # Find the facet(s) that map to this role
            for ftype, vals in includes.items():
                if not vals:
                    continue
                role_label = _facet_role(ftype)
                if role_label != role:
                    continue
                has_ingredients = True
                # Role label
                rl = QLabel(role)
                rl.setStyleSheet(_theme.RECIPE_ROLE_LABEL)
                self._ingredients_layout.addWidget(rl)
                # Chips row
                row = _ChipRow(ftype, list(vals), "include", self)
                row.remove_clicked.connect(self._on_remove)
                self._ingredients_layout.addWidget(row)

        # Render excludes under OMIT
        exclude_vals: list[tuple[str, str]] = [
            (ftype, v)
            for ftype, vals in excludes.items()
            for v in vals
            if vals
        ]
        if exclude_vals:
            has_ingredients = True
            omit_lbl = QLabel("OMIT")
            omit_lbl.setStyleSheet(
                f"font-size: {_theme.FONT_SM}; font-weight: bold;"
                f" color: {_theme.COLOR_WARN}; letter-spacing: 1px;"
            )
            self._ingredients_layout.addWidget(omit_lbl)
            for ftype, v in exclude_vals:
                row = _ChipRow(ftype, [v], "exclude", self)
                row.remove_clicked.connect(self._on_remove)
                self._ingredients_layout.addWidget(row)

        if not has_ingredients:
            empty = QLabel("No ingredients yet — click tags to add them")
            empty.setStyleSheet(
                f"color: {_theme.COLOR_RECIPE_MUTED_2}; font-size: {_theme.FONT_MD};"
            )
            empty.setWordWrap(True)
            self._ingredients_layout.addWidget(empty)

        self._ingredients_layout.addStretch()

        # YIELDS
        if match_count is None:
            self._yields_lbl.setText("YIELDS counting…")
        else:
            self._yields_lbl.setText(f"YIELDS {match_count:,} channel{'s' if match_count != 1 else ''}")

    # ── private ───────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        outer = QVBoxLayout(inner)
        outer.setContentsMargins(12, 12, 12, 8)
        outer.setSpacing(6)

        # "TONIGHT'S RECIPE" header
        rail_hdr = QLabel("TONIGHT'S RECIPE")
        rail_hdr.setStyleSheet(_theme.RECIPE_RAIL_HDR)
        outer.addWidget(rail_hdr)

        # Editorial recipe name
        self._name_lbl = QLabel("Your recipe is empty")
        self._name_lbl.setStyleSheet(_theme.RECIPE_EDITORIAL_NAME)
        self._name_lbl.setWordWrap(True)
        outer.addWidget(self._name_lbl)

        # Divider
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(_theme.SEPARATOR_H)
        outer.addWidget(line)

        # Ingredient chips area (populated dynamically via update_recipe)
        self._ingredients_layout = QVBoxLayout()
        self._ingredients_layout.setSpacing(4)
        self._ingredients_layout.setContentsMargins(0, 0, 0, 0)
        outer.addLayout(self._ingredients_layout)

        # Initial empty state
        empty = QLabel("No ingredients yet — click tags to add them")
        empty.setStyleSheet(
            f"color: {_theme.COLOR_RECIPE_MUTED_2}; font-size: {_theme.FONT_MD};"
        )
        empty.setWordWrap(True)
        self._ingredients_layout.addWidget(empty)
        self._ingredients_layout.addStretch()

        # Divider above footer
        line2 = QFrame()
        line2.setFrameShape(QFrame.Shape.HLine)
        line2.setStyleSheet(_theme.SEPARATOR_H)
        outer.addWidget(line2)

        # YIELDS count
        self._yields_lbl = QLabel("YIELDS 0 channels")
        self._yields_lbl.setStyleSheet(_theme.RECIPE_YIELDS)
        outer.addWidget(self._yields_lbl)

        scroll.setWidget(inner)

        # Action buttons (Save stub + Clear)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.save_btn = QPushButton(f"{_icons.recipe_save_icon} Save Recipe")
        self.save_btn.setEnabled(False)   # slice 4 TODO
        self.save_btn.setStyleSheet(_theme.RECIPE_SAVE_BTN)
        self.save_btn.setToolTip("Save this recipe for quick access — coming in a future update")
        btn_row.addWidget(self.save_btn)

        self.clear_btn = QPushButton(f"{_icons.recipe_clear_icon} Clear")
        self.clear_btn.setStyleSheet(_theme.RECIPE_CLEAR_BTN)
        self.clear_btn.setToolTip("Remove all ingredients from the recipe")
        btn_row.addWidget(self.clear_btn)

        wrapper = QVBoxLayout(self)
        wrapper.setContentsMargins(0, 0, 0, 0)
        wrapper.setSpacing(0)
        wrapper.addWidget(scroll)

        footer = QWidget()
        footer.setStyleSheet("background: transparent;")
        footer.setLayout(btn_row)
        footer.layout().setContentsMargins(12, 8, 12, 12)  # type: ignore[union-attr]
        wrapper.addWidget(footer)

    def _on_remove(self, facet_type: str, value: str) -> None:
        self.ingredient_remove_requested.emit(facet_type, value)


class _ChipRow(QWidget):
    """A horizontal row of ingredient chips for one facet + state.

    Args:
        facet_type: The facet namespace (e.g. "genre").
        values: The ingredient values for this role group.
        state: "include" or "exclude".
        parent: Parent widget.
    """

    remove_clicked = pyqtSignal(str, str)   # (facet_type, value)

    def __init__(
        self,
        facet_type: str,
        values: list[str],
        state: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        style = _theme.RECIPE_OMIT_CHIP if state == "exclude" else _theme.RECIPE_INGREDIENT_CHIP
        icon = _icons.tag_exclude_icon if state == "exclude" else _icons.tag_include_icon
        color = _facet_color(facet_type)

        for v in sorted(values):
            chip = QPushButton(f"{icon} {v}")
            chip.setStyleSheet(style)
            chip.setToolTip(f"Click to remove '{v}' from the recipe")
            # color override for include chips — use facet color
            if state == "include":
                chip.setStyleSheet(
                    f"QPushButton {{ font-size: {_theme.FONT_MD}; color: {color};"
                    f" border: 1px solid {_theme.COLOR_BORDER}; border-radius: 4px;"
                    f" padding: 2px 8px; background: {_theme.OVERLAY_05}; }}"
                    f"QPushButton:hover {{ background: {_theme.OVERLAY_10}; }}"
                )
            chip.clicked.connect(self._make_handler(facet_type, v))
            layout.addWidget(chip)

        layout.addStretch()

    def _make_handler(self, facet_type: str, value: str):
        def _handler() -> None:
            self.remove_clicked.emit(facet_type, value)
        return _handler


# ---------------------------------------------------------------------------
# Helper: clear a QLayout without destroying it
# ---------------------------------------------------------------------------

def _clear_layout(layout) -> None:
    """Remove all widgets/items from *layout*, deleting their widgets."""
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


# ---------------------------------------------------------------------------
# Now Plating results grid
# ---------------------------------------------------------------------------

class _GridContainer(QWidget):
    """Flow-layout body for the Now-Plating grid.

    Holds the Discover ``_FlowLayout`` and reflows (wraps) its cards on every
    resize, growing its own fixed height to the wrapped content height so the
    enclosing vertical ``QScrollArea`` scrolls.  Mirrors ``_BrowseContainer`` in
    ``discover_browse.py`` — the same vertically-scrollable wrapping-grid
    primitive, kept local so the recipe view doesn't couple to the See-All
    browse drill-down.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._flow = None  # _FlowLayout | None

    def set_flow(self, flow) -> None:
        self._flow = flow

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        if self._flow is not None:
            h = self._flow.relayout(self.width())
            self.setFixedHeight(max(h + 16, 1))
        if event is not None:
            super().resizeEvent(event)


class _NowPlatingStrip(QWidget):
    """Wrapping, vertically-scrollable grid of clickable result cards.

    Reuses the Discover ``_ContentCard`` surface (poster + async ``ImageCache``
    loading + title) and the Discover ``_FlowLayout`` so a recipe match is
    browsable and actionable — the cards wrap into rows and the area fills the
    space below the cloud rather than clipping a single horizontal row:

    - single-click  → ``cardClicked(channel_id)``       (select → details pane)
    - double-click  → ``cardDoubleClicked(channel_id)``  (play, host-delegated)

    Poster loading is lazy (same pattern as ``discover_browse._BrowseView``):
    only cards inside the current vertical viewport request an image, fired on
    scroll and once after each rebuild has settled — so toggling a tag (which
    rebuilds the grid) only ever decodes the visible posters.  QPixmap is built
    on the main thread inside each card's own ``image_loaded`` slot.
    """

    cardClicked       = pyqtSignal(str)        # channel_id
    cardDoubleClicked = pyqtSignal(str)        # channel_id
    cardMiddleClicked = pyqtSignal(str)        # channel_id — configured middle-click play
    cardContextMenu   = pyqtSignal(str, int, int)  # channel_id, gx, gy
    showAllRequested  = pyqtSignal()           # "Show all →" → full-results browse page

    def __init__(self, image_cache, config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image_cache = image_cache
        self._config = config
        self._card_widgets: list = []          # list[_ContentCard]
        self._scroll: QScrollArea | None = None
        self._flow = None                      # _FlowLayout | None
        self._total_count: int = 0             # latest match total (drives "Show all")
        self._build_ui()

    # ── public ────────────────────────────────────────────────────────────

    def load_results(self, cards: list, total_count: int) -> None:
        """Populate the grid with real content cards.

        Args:
            cards:       ``ContentCard`` value objects (≤ the grid cap) from
                         ``TagRepository.sample_channels_by_tag_facets``.
            total_count: Total number of matching channels (for the header +
                         the "+N more…" remainder indicator).
        """
        from metatv.gui.discover_card import _ContentCard, _FlowLayout

        self._total_count = total_count
        self._hdr.setText(
            f"NOW PLATING  ·  {total_count:,} match{'es' if total_count != 1 else ''}"
        )
        # "Show all" only makes sense when there is at least one match.
        self._show_all_btn.setVisible(total_count > 0)

        # Tear down the previous flow + cards, then start a fresh flow.  (A new
        # _FlowLayout each rebuild matches discover_browse — clear() deletes the
        # old card widgets.)
        if self._flow is not None:
            self._flow.clear()
        self._card_widgets = []
        self._flow = _FlowLayout(self._grid_container, spacing=8)
        self._grid_container.set_flow(self._flow)

        if not cards:
            placeholder = QLabel("No channels match this recipe yet")
            placeholder.setStyleSheet(
                f"color: {_theme.COLOR_RECIPE_MUTED_2}; font-size: {_theme.FONT_MD};"
            )
            self._flow.add(placeholder)
            placeholder.show()
            self._grid_container.resizeEvent(None)
            return

        for card in cards:
            w = _ContentCard(card, self._image_cache, self._config, self._grid_container)
            w.clicked.connect(self.cardClicked)
            w.doubleClicked.connect(self.cardDoubleClicked)
            w.middleClicked.connect(self.cardMiddleClicked)
            w.contextMenuRequested.connect(self.cardContextMenu)
            self._flow.add(w)
            w.show()
            self._card_widgets.append(w)

        if total_count > len(cards):
            more = QLabel(f"+ {total_count - len(cards):,} more…  ·  showing {len(cards)} of {total_count:,}")
            more.setStyleSheet(
                f"color: {_theme.COLOR_RECIPE_MUTED}; font-size: {_theme.FONT_MD};"
            )
            self._flow.add(more)
            more.show()

        # Wrap into rows now that all cards exist, then load posters for the
        # cards in the viewport once geometry has settled.
        self._grid_container.resizeEvent(None)
        QTimer.singleShot(120, self._load_visible)

    # ── private ───────────────────────────────────────────────────────────

    def _load_visible(self) -> None:
        """Request poster images for cards currently in the vertical viewport."""
        if self._scroll is None:
            return
        vp_h = self._scroll.viewport().height()
        if vp_h == 0:
            QTimer.singleShot(80, self._load_visible)
            return
        scroll_y = self._scroll.verticalScrollBar().value()
        for card in self._card_widgets:
            top = card.y()
            if top + card.height() >= scroll_y and top <= scroll_y + vp_h:
                card.request_image()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(4)

        # Divider
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(_theme.SEPARATOR_H)
        outer.addWidget(line)

        # Header row: "NOW PLATING · N matches" label + "Show all →" affordance.
        hdr_row = QHBoxLayout()
        hdr_row.setContentsMargins(0, 0, 0, 0)
        hdr_row.setSpacing(8)

        self._hdr = QLabel("NOW PLATING  ·  0 matches")
        self._hdr.setStyleSheet(_theme.RECIPE_NOW_PLATING_HDR)
        hdr_row.addWidget(self._hdr)
        hdr_row.addStretch()

        # "Show all →" — flat link styled like Discover's "See all →", swaps the
        # bounded teaser for the full-results browse grid.  Hidden until there is
        # at least one match (toggled in load_results).
        self._show_all_btn = QPushButton(f"Show all {_icons.see_all_arrow_icon}")
        self._show_all_btn.setFlat(True)
        self._show_all_btn.setStyleSheet(
            f"QPushButton {{ color: {_theme.COLOR_ACCENT_BLUE}; border: none;"
            f" font-size: {_theme.FONT_MD}; padding: 2px 4px; }}"
            f"QPushButton:hover {{ color: {_theme.COLOR_ACCENT_HOVER}; }}"
        )
        self._show_all_btn.setToolTip("Browse all matching channels")
        self._show_all_btn.setVisible(False)
        self._show_all_btn.clicked.connect(self.showAllRequested)
        hdr_row.addWidget(self._show_all_btn)

        outer.addLayout(hdr_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self._scroll = scroll
        scroll.verticalScrollBar().valueChanged.connect(self._load_visible)

        self._grid_container = _GridContainer()
        self._grid_container.setStyleSheet("background: transparent;")
        scroll.setWidget(self._grid_container)
        # The grid takes the remaining vertical space in the center column.
        outer.addWidget(scroll, stretch=1)

