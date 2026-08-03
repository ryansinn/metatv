"""Recipe view helper widgets — facet metadata + the masonry cluster grid.

Extracted from ``recipe_view.py`` (which exceeded the 1000-line file limit) so
that file holds only the :class:`RecipeView` host.  Everything here is a leaf
presentation widget or a pure helper (facet metadata, editorial name generator,
layout clearing, the masonry facet grid) — no DB access, no async seam.
``recipe_view`` re-exports these names for backward compatibility, so existing
imports keep resolving.

Split follows the same convention as the EPG view (``epg_widgets.py`` /
``epg_*_mixin.py``): one cohesive concern per file, re-exported from the host.
The one-line recipe bar + Matching Content shelf live in
``recipe_bar_widgets.py``; the Saved-tab cards live in ``recipe_saved_widgets.py``.
"""

from __future__ import annotations

import random
import re

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QPushButton,
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
def _facet_meta() -> dict[str, tuple[str, str, str]]:
    """Facet display metadata, re-read fresh so a live theme switch applies."""
    return {
        "category":   ("Category",      _theme.COLOR_FACET_CATEGORY,   "KIND"),
        "genre":      ("Genre",         _theme.COLOR_FACET_GENRE,      "BASE"),
        "language":   ("Language",      _theme.COLOR_FACET_LANGUAGE,   "IN"),
        "subtitle":   ("Subtitle",      _theme.COLOR_FACET_SUBTITLE,   "IN"),
        "dub":        ("Dub Lang",      _theme.COLOR_FACET_DUB,        "IN"),
        "format":     ("Audio Format",  _theme.COLOR_FACET_FORMAT,     "AUDIO"),
        "region":     ("Region",        _theme.COLOR_FACET_REGION,     "FROM"),
        "platform":   ("Platform",      _theme.COLOR_FACET_PLATFORM,   "ON"),
        "decade":     ("Decade",        _theme.COLOR_FACET_DECADE,     "ERA"),
        "quality":    ("Quality",       _theme.COLOR_FACET_QUALITY,    "FINISH"),
        "collection": ("Collection",    _theme.COLOR_FACET_COLLECTION, "SET"),
    }

# Role display order in the recipe rail / bar
_ROLE_ORDER: list[str] = ["KIND", "BASE", "IN", "AUDIO", "FROM", "ON", "ERA", "FINISH", "SET"]

# The browse facets shown as masonry tiles, in display order (mockup order).
# **Format is deliberately excluded** — audio format is a filter-panel concern,
# not a browse dimension (owner decision).  This is the control-layer set the
# view hands to the generic ``get_top_tags_per_facet`` engine; the engine itself
# stays facet-agnostic (DR-0007).
BROWSE_FACETS: tuple[str, ...] = (
    "genre", "region", "language", "decade", "collection", "quality", "platform", "subtitle",
)
# Back-compat alias — the cluster mixin loads this exact set in one windowed pass.
_ALL_CLUSTER_FACETS: tuple[str, ...] = BROWSE_FACETS

# Top-N tag values requested per facet for the overview (small facets return all).
_CLUSTER_LIMIT_PER_FACET: int = 24

# Minimum tile width (px) used to compute the responsive masonry column count.
_CLUSTER_TILE_MIN_W: int = 300
# Cap the masonry at this many columns even on very wide monitors.
_CLUSTER_MAX_COLS: int = 4


def _facet_color(facet_type: str) -> str:
    """Return the theme color token for a facet type, falling back to COLOR_TEXT."""
    return _facet_meta().get(facet_type, ("", _theme.COLOR_TEXT, ""))[1]


def _facet_display(facet_type: str) -> str:
    """Return the human-readable display name for a facet type."""
    return _facet_meta().get(facet_type, (facet_type.title(), "", ""))[0]


def _facet_role(facet_type: str) -> str:
    """Return the role label (BASE/IN/FROM…) for a facet type."""
    return _facet_meta().get(facet_type, ("", "", "OTHER"))[2]


def _facet_chip_style(color: str, *, excluded: bool = False) -> str:
    """Return the stylesheet for a facet-colored ingredient / saved-recipe tag.

    Composed from theme tokens (never a literal), centralised here so the recipe
    bar and the Saved-recipe cards share ONE chip look instead of copy-pasting
    the composition.  ``excluded`` renders the omit (strike-through, warn) style.

    Args:
        color: The facet's theme color token (from :func:`_facet_color`).
        excluded: When True, render the exclude/omit variant.

    Returns:
        A Qt stylesheet string for a small pill button/label.
    """
    if excluded:
        return (
            f"font-size: {_theme.FONT_LG}; color: {_theme.COLOR_WARN};"
            f" border: 1px solid {_theme.COLOR_BORDER}; border-radius: 8px;"
            f" padding: 3px 9px; background: transparent; text-decoration: line-through;"
        )
    return (
        f"font-size: {_theme.FONT_LG}; color: {color};"
        f" border: 1px solid {_theme.COLOR_BORDER}; border-radius: 8px;"
        f" padding: 3px 9px; background: {_theme.OVERLAY_05};"
    )


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
# Default cluster grid: per-facet mini tag-clouds ("clusters"), masonry-packed
# ---------------------------------------------------------------------------


def _decade_sort_key(value: str) -> int:
    """Chronological sort key for a decade tag value (``"1990s"`` → ``1990``).

    Decade tiles order their chips by era, not by catalogue weight; a non-numeric
    value sorts last.
    """
    m = re.match(r"\s*(\d{3,4})", value or "")
    return int(m.group(1)) if m else 9999


class _TagSearchBar(QWidget):
    """Cross-facet tag search box shown beside the "Browse by facet" header.

    Emits ``search_changed(text)`` — empty immediately (so clearing restores the
    grid without an idle wait), non-empty debounced so fast typing coalesces into
    one DB round-trip.
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
        self._box.setFixedWidth(300)
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


class _ClusterTile(QFrame):
    """One facet's mini weighted tag-cloud, sized to its own content.

    Header = the facet name (clickable → drill into that facet's full cloud; the
    labelled header is the non-color a11y cue) + a "N tags" count + a "see all ›"
    hint.  Body = the facet's top-N values as weighted tag buttons, font-size
    normalized WITHIN this tile (its own min/max) so a small facet isn't erased by
    a global scale.  Clicking a tag adds it to the recipe without leaving the
    overview.  **The decade tile is special**: uniform (un-weighted) chips ordered
    chronologically oldest→newest — a chip strip, not a weighted cloud.

    Reuses the shared cloud primitives (``_TagButton`` / ``_count_to_font_token``
    / ``_CloudBody``) so a cluster renders identically to the full cloud and the
    cross-facet search cloud — one renderer, never a parallel one.  The tile sizes
    itself to header + body height (no filler gap between title and tags).
    """

    facet_clicked = pyqtSignal(str)         # facet_type — drill into the full cloud
    tag_clicked   = pyqtSignal(str, str)    # (facet_type, value) — add an ingredient

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("clusterTile")
        _theme.style(self, "RECIPE_CLUSTER_TILE")
        # Size to content vertically so the masonry packs tiles by true height.
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self._facet: str = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 12)
        outer.setSpacing(8)
        self._outer = outer

        hdr_row = QHBoxLayout()
        hdr_row.setContentsMargins(0, 0, 0, 0)
        hdr_row.setSpacing(6)
        self._hdr_btn = QPushButton("")
        self._hdr_btn.setFlat(True)
        self._hdr_btn.clicked.connect(self._emit_facet)
        hdr_row.addWidget(self._hdr_btn)
        self._sub_lbl = QLabel("")
        _theme.style(self._sub_lbl, "RECIPE_CLUSTER_SUBTITLE")
        hdr_row.addWidget(self._sub_lbl)
        hdr_row.addStretch()
        self._see_all_lbl = QLabel(f"see all {_icons.nav_next_icon}")
        _theme.style(self._see_all_lbl, "RECIPE_CLUSTER_SUBTITLE")
        hdr_row.addWidget(self._see_all_lbl)
        self._hdr_row = hdr_row
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
            f" font-size: {_theme.FONT_LG}; font-weight: bold; letter-spacing: 1px;"
            f" text-align: left; padding: 0; }}"
            f"QPushButton:hover {{ text-decoration: underline; }}"
        )
        self._hdr_btn.setToolTip(f"Browse all {display} tags")
        self._sub_lbl.setText(f"· {len(items)} tags")

        is_decade = facet == "decade"
        # Decade orders chronologically; every other facet keeps the engine's
        # count-DESC order.
        ordered = (
            sorted(items, key=lambda d: _decade_sort_key(d.value))
            if is_decade
            else list(items)
        )
        # Decade is a chip strip (see all one line), never truncated to a "see all".
        self._see_all_lbl.setVisible(not is_decade)

        # content_type slugs render friendly labels; identity stays the slug.
        display_map: dict[str, str] = {}
        if facet == "content_type":
            from metatv.core.channel_name_utils import content_type_display
            display_map = {d.value: content_type_display(d.value) for d in ordered}

        # Normalize font size WITHIN this tile (its own min/max).  Decade chips are
        # uniform (a strip, not a weighted cloud).
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
            token = _theme.FONT_CLOUD_3 if is_decade else _count_to_font_token(dto.channel_count, mn, mx)
            btn = _TagButton(
                dto.value, dto.channel_count, state, token, color,
                facet_type=facet, display=display_map.get(dto.value),
            )
            btn.clicked.connect(self._make_handler(dto.value))
            self._body.flow().add(btn)
        self._body.refresh_layout()

    def height_for_width(self, width: int) -> int:
        """Estimate the tile's laid-out height at *width* (for masonry balancing).

        Deterministic (no show/paint dependency): relayouts the body flow at the
        tile's inner width and adds the header row + margins.  Used only to pick
        the shortest column; Qt sets the real geometry once the tile is placed.
        """
        m = self._outer.contentsMargins()
        inner = max(1, width - m.left() - m.right())
        body_h = self._body.flow().relayout(inner)
        hdr_h = self._hdr_btn.sizeHint().height()
        return m.top() + hdr_h + self._outer.spacing() + body_h + m.bottom()

    # ── private ───────────────────────────────────────────────────────────

    def _emit_facet(self) -> None:
        self.facet_clicked.emit(self._facet)

    def _make_handler(self, value: str):
        def _h() -> None:
            self.tag_clicked.emit(self._facet, value)
        return _h


class _ClusterGrid(QWidget):
    """Masonry-packed grid of per-facet cluster tiles — the dominant browse area.

    All browse facets (see :data:`BROWSE_FACETS`) render as tiles at once; there
    is NO "More facets" collapse.  Tiles are packed by a column-balancing flow
    (each tile joins the currently-shortest column), so short tiles don't leave a
    dead gap under a tall neighbour the way a fixed grid does.  The column count
    tracks the available width (landscape-first; fewer columns on a narrow window
    is the "compact" — never a collapse).

    Emits ``facet_selected`` (drill into a facet's full cloud) and ``tag_clicked``
    (add an ingredient without leaving the overview).
    """

    facet_selected = pyqtSignal(str)        # facet_type — drill into the full cloud
    tag_clicked    = pyqtSignal(str, str)   # (facet_type, value)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data: dict[str, list] = {}
        self._includes: dict[str, set] = {}
        self._excludes: dict[str, set] = {}
        self._tiles: list[_ClusterTile] = []
        self._col_layouts: list[QVBoxLayout] = []
        self._last_cols: int = 0
        self._build_ui()

    # ── public ────────────────────────────────────────────────────────────

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
        """All rendered tiles — for tests/introspection."""
        return list(self._tiles)

    def refresh_theme(self) -> None:
        """Re-apply the active palette to this grid's own persistent chrome —
        the "Loading facets…"/"No facets to show yet" placeholder, styled once
        at construction. ``_ClusterTile`` instances are rebuilt fresh from
        current tokens on every ``set_clusters()`` call, so they need no sweep
        entry here. Called from ``RecipeView.refresh_theme()``.
        """
        _theme.style(self._placeholder, "RECIPE_EMPTY_HINT")

    # ── private ───────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 8, 12, 8)
        outer.setSpacing(8)

        # Empty / loading placeholder (shown until the async cluster load lands).
        self._placeholder = QLabel("Loading facets…")
        _theme.style(self._placeholder, "RECIPE_EMPTY_HINT")
        outer.addWidget(self._placeholder)

        # Masonry host — a horizontal row of column layouts, rebuilt on column-count
        # changes.  Tiles pack into the shortest column (see _relayout).
        self._cols_host = QWidget()
        self._cols_row = QHBoxLayout(self._cols_host)
        self._cols_row.setContentsMargins(0, 0, 0, 0)
        self._cols_row.setSpacing(14)
        outer.addWidget(self._cols_host)
        outer.addStretch()

    def _rebuild(self) -> None:
        for t in self._tiles:
            t.setParent(None)
            t.deleteLater()
        self._tiles = []

        for facet in BROWSE_FACETS:
            items = self._data.get(facet)
            if items:
                self._tiles.append(self._make_tile(facet, items))

        has_any = bool(self._tiles)
        self._placeholder.setVisible(not has_any)
        self._placeholder.setText("No facets to show yet" if self._data else "Loading facets…")

        self._last_cols = 0   # force a fresh distribution
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
            w = 1000
        return max(1, min(_CLUSTER_MAX_COLS, w // _CLUSTER_TILE_MIN_W))

    def _clear_columns(self) -> None:
        """Detach tiles and tear down the current column layouts."""
        for tile in self._tiles:
            tile.setParent(self._cols_host)  # keep alive across the reflow
        while self._cols_row.count():
            item = self._cols_row.takeAt(0)
            sub = item.layout()
            if sub is not None:
                while sub.count():
                    sub.takeAt(0)
                sub.deleteLater()
        self._col_layouts = []

    def _relayout(self) -> None:
        cols = self._cols()
        if cols == self._last_cols and self._col_layouts:
            return   # equal-width columns reflow tile widths for free
        self._last_cols = cols
        self._clear_columns()

        # Fresh column layouts inside the host row (equal stretch → equal width).
        for _ in range(cols):
            col = QVBoxLayout()
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(14)
            self._cols_row.addLayout(col, 1)
            self._col_layouts.append(col)

        total_gap = self._cols_row.spacing() * max(0, cols - 1)
        host_w = self._cols_host.width() or self.width() or 1000
        col_w = max(_CLUSTER_TILE_MIN_W, (host_w - total_gap) // max(1, cols))

        heights = [0] * cols
        for tile in self._tiles:
            idx = heights.index(min(heights))   # shortest column so far
            self._col_layouts[idx].addWidget(tile)
            tile.show()
            heights[idx] += tile.height_for_width(col_w) + self._cols_row.spacing()

        for col in self._col_layouts:
            col.addStretch()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._relayout()


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
