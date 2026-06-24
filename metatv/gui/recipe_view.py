"""RecipeView — tag-cloud "Recipe" builder (task #56, slice 3).

Three-column view reached via the ✦ Recipe nav chip:

    LEFT  (~212 px) — "THE PANTRY" facet sidebar: one row per facet from
                      get_facet_summary(); a stub "SAVED RECIPES" section below.
    CENTER           — WeightedTagCloud for the selected facet + "Now Plating"
                      results shelf (real, clickable poster cards reusing the
                      Discover _ContentCard surface).
    RIGHT (~328 px)  — "TONIGHT'S RECIPE" rail with role-grouped ingredient
                      chips, OMIT section, YIELDS count, Save (stub) + Clear.

Slice 4 TODO: saved-recipe persistence, pinned/excluded individual titles.

Data wiring (all DB reads off the main thread via the owner's _run_query seam):
  - Pantry  ← TagRepository.get_facet_summary(...)
  - Cloud   ← TagRepository.get_tag_counts_for_facet(facet, ...)
  - YIELDS  ← TagRepository.count_channels_by_tag_facets(...)        (SQL COUNT)
  - Results ← TagRepository.sample_channels_by_tag_facets(...)       (bounded
                LIMIT → session-free ContentCards; never materialises the set).

Scoping follows DR-0007: the engine is agnostic; the view (control layer) passes
ProviderRepository.get_hidden_provider_ids() AND the user's Global Exclusions
(_global_exclusion_sets(), resolved from Config) into every faceted read, so the
pantry, cloud, YIELDS, and results all agree.

Selection/playback are host-delegated like DiscoverView: result cards emit
channelSelected / playRequested (channel_id), wired by MainWindow to
show_channel_details_by_id / play_channel_by_id (provider_id threading reused).
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from loguru import logger
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.weighted_tag_cloud import WeightedTagCloud

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database
    from metatv.core.repositories.dtos import FacetSummaryDTO, TagCountDTO


# ---------------------------------------------------------------------------
# Facet display config: name, color token, role label for the recipe rail
# ---------------------------------------------------------------------------

# Maps facet_type → (display_name, color_token, role_label)
# "category" (live-channel kind: Sports/News/Kids…) sits immediately before
# "genre" — both are content descriptors; category is the live-channel variant.
_FACET_META: dict[str, tuple[str, str, str]] = {
    "category":   ("Category",   _theme.COLOR_FACET_CATEGORY,   "KIND"),
    "genre":      ("Genre",      _theme.COLOR_FACET_GENRE,      "BASE"),
    "language":   ("Language",   _theme.COLOR_FACET_LANGUAGE,   "IN"),
    "region":     ("Region",     _theme.COLOR_FACET_REGION,     "FROM"),
    "platform":   ("Platform",   _theme.COLOR_FACET_PLATFORM,   "ON"),
    "decade":     ("Decade",     _theme.COLOR_FACET_DECADE,     "ERA"),
    "quality":    ("Quality",    _theme.COLOR_FACET_QUALITY,    "FINISH"),
    "collection": ("Collection", _theme.COLOR_FACET_COLLECTION, "SET"),
}

# Role display order in the recipe rail
_ROLE_ORDER: list[str] = ["KIND", "BASE", "IN", "FROM", "ON", "ERA", "FINISH", "SET"]


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
# Pantry sidebar
# ---------------------------------------------------------------------------

class _FacetRowButton(QPushButton):
    """One facet row in the Pantry sidebar.

    Shows a small colored bar on the left edge, the facet display name,
    and the distinct-value count on the right.  Selected state is applied
    via stylesheet swap.
    """

    def __init__(
        self,
        facet_type: str,
        display_name: str,
        distinct_values: int,
        color: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.facet_type = facet_type
        self._color = color
        self._selected = False

        # Build label: "■ Genre    512"
        self.setText(f"■ {display_name}   {distinct_values:,}")
        self.setToolTip(
            f"{display_name} — {distinct_values:,} distinct values in your library"
        )
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_style()

    # ── public ────────────────────────────────────────────────────────────

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._apply_style()

    def is_selected(self) -> bool:
        return self._selected

    # ── private ───────────────────────────────────────────────────────────

    def _apply_style(self) -> None:
        color = self._color
        if self._selected:
            style = (
                f"QPushButton {{ border: none; background: {_theme.OVERLAY_RECIPE_SELECTED};"
                f" color: {color}; font-size: {_theme.FONT_MD};"
                f" text-align: left; padding: 5px 8px; border-radius: 4px;"
                f" border-left: 2px solid {color}; }}"
            )
        else:
            style = (
                f"QPushButton {{ border: none; background: transparent;"
                f" color: {_theme.COLOR_RECIPE_TEXT}; font-size: {_theme.FONT_MD};"
                f" text-align: left; padding: 5px 8px; border-radius: 4px; }}"
                f"QPushButton:hover {{ background: {_theme.OVERLAY_05}; }}"
            )
        self.setStyleSheet(style)


class _PantrySidebar(QWidget):
    """Left sidebar listing all available facets + stub Saved Recipes section.

    Emits ``facet_selected(facet_type)`` when the user clicks a facet row.
    """

    facet_selected = pyqtSignal(str)   # facet_type string

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(212)
        self.setStyleSheet(_theme.RECIPE_PANTRY_BG)
        self._facet_buttons: list[_FacetRowButton] = []
        self._selected_facet: str | None = None

        self._build_ui()

    # ── public ────────────────────────────────────────────────────────────

    def load_facets(self, summaries: list[FacetSummaryDTO]) -> None:
        """Populate the pantry with facet summary rows.

        Args:
            summaries: Ordered list of FacetSummaryDTO from
                TagRepository.get_facet_summary().
        """
        # Clear existing buttons (but not the layout structure)
        for btn in self._facet_buttons:
            btn.deleteLater()
        self._facet_buttons.clear()

        for dto in summaries:
            meta = _FACET_META.get(dto.facet_type)
            display = meta[0] if meta else dto.facet_type.title()
            color = meta[1] if meta else _theme.COLOR_TEXT
            btn = _FacetRowButton(dto.facet_type, display, dto.distinct_values, color)
            btn.clicked.connect(self._make_selector(dto.facet_type))
            self._facets_layout.addWidget(btn)
            self._facet_buttons.append(btn)

        # Auto-select first facet if none is selected yet
        if self._facet_buttons and self._selected_facet is None:
            self._select_facet(self._facet_buttons[0].facet_type)

    def selected_facet(self) -> str | None:
        return self._selected_facet

    # ── private ───────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 12, 8, 8)
        outer.setSpacing(0)

        # "THE PANTRY" header
        pantry_hdr = QLabel("THE PANTRY")
        pantry_hdr.setStyleSheet(_theme.RECIPE_PANTRY_HDR)
        outer.addWidget(pantry_hdr)

        # Facet rows (populated dynamically via load_facets)
        self._facets_layout = QVBoxLayout()
        self._facets_layout.setContentsMargins(0, 4, 0, 0)
        self._facets_layout.setSpacing(2)
        outer.addLayout(self._facets_layout)

        # Divider
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(_theme.SEPARATOR_H)
        outer.addWidget(line)

        # "SAVED RECIPES" stub header
        saved_hdr = QLabel("SAVED RECIPES")
        saved_hdr.setStyleSheet(_theme.RECIPE_PANTRY_HDR)
        outer.addWidget(saved_hdr)

        # Stub placeholder — slice 4 will populate this
        saved_stub = QLabel("No saved recipes yet")
        saved_stub.setStyleSheet(
            f"color: {_theme.COLOR_RECIPE_MUTED_2}; font-size: {_theme.FONT_MD};"
            " padding: 4px 8px;"
        )
        saved_stub.setToolTip("Saving recipes will be available in a future update")
        outer.addWidget(saved_stub)  # slice 4 TODO

        outer.addStretch()

    def _make_selector(self, facet_type: str):
        """Closure factory so each button captures its own facet_type."""
        def _select() -> None:
            self._select_facet(facet_type)
        return _select

    def _select_facet(self, facet_type: str) -> None:
        self._selected_facet = facet_type
        for btn in self._facet_buttons:
            btn.set_selected(btn.facet_type == facet_type)
        self.facet_selected.emit(facet_type)


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
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
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

    cardClicked       = pyqtSignal(str)   # channel_id
    cardDoubleClicked = pyqtSignal(str)   # channel_id
    showAllRequested  = pyqtSignal()      # "Show all →" → full-results browse page

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
        self._show_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
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


# ---------------------------------------------------------------------------
# Main RecipeView
# ---------------------------------------------------------------------------

class RecipeView(QWidget):
    """Three-column Recipe builder view.

    Registered as a chip-nav destination by MainWindow.  Follows the same
    on_activate / on_deactivate lifecycle as DiscoverView and EpgView.

    The view is stateless about DB reads: all reads go through the owner's
    ``_run_query`` seam (passed as ``run_query_fn`` in the constructor) which
    runs them off the main thread and delivers results via signal on the main
    thread.

    Selection/playback are host-delegated like DiscoverView/EpgView: the
    "Now Plating" result cards emit ``channelSelected`` / ``playRequested``
    (channel_id), which MainWindow connects to ``show_channel_details_by_id`` /
    ``play_channel_by_id`` — so provider_id threading and the canonical play
    path are reused, never hand-rolled here.

    Attributes:
        _recipe_includes: Current include recipe state.  Maps
            ``facet_type → set[value]``.
        _recipe_excludes: Current exclude recipe state.  Maps
            ``facet_type → set[value]``.
        _selected_facet: The currently selected facet in the Pantry.
        _tag_counts:     Most recently loaded TagCountDTOs for the current facet.
        _active:         True while the view is visible (between on_activate /
            on_deactivate).
    """

    channelSelected = pyqtSignal(str)   # channel_id — select → details pane
    playRequested   = pyqtSignal(str)   # channel_id — play (host-delegated)

    def __init__(
        self,
        db: Database,
        config: Config,
        run_query_fn,
        image_cache,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._db = db
        self._config = config
        self._run_query = run_query_fn
        self._image_cache = image_cache

        # Recipe state
        self._recipe_includes: dict[str, set[str]] = {}
        self._recipe_excludes: dict[str, set[str]] = {}
        self._selected_facet: str | None = None
        self._tag_counts: list[TagCountDTO] = []
        self._active: bool = False

        # Tokens for stale-drop on rapid switches
        self._pantry_token: list[int] = [0]
        self._cloud_token: list[int] = [0]
        self._results_token: list[int] = [0]
        self._see_all_token: list[int] = [0]

        # "Show all" lazy-pagination state: how many cards we've already shown
        # (the page-1 seed reuses the teaser's cards), the known full match
        # total, and a guard so we never fire overlapping page loads.
        self._see_all_offset: int = 0
        self._see_all_total: int = 0
        self._see_all_loading: bool = False

        # Debounce timer — coalesces rapid tag clicks into a single DB query.
        # Each mutation renders the rail/cloud instantly and restarts this timer;
        # the timer fires _load_results() once after the idle window expires.
        self._results_debounce = QTimer(self)
        self._results_debounce.setSingleShot(True)
        self._results_debounce.setInterval(self._DEBOUNCE_MS)
        self._results_debounce.timeout.connect(self._load_results)

        self._build_ui()

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def on_activate(self) -> None:
        """Called by MainWindow when this view becomes visible."""
        self._active = True
        # Re-entering via the Recipe chip is the user's 1-click "back to
        # building" path — always land on the constructor, never a stale browse
        # page from a previous visit.
        self._stack.setCurrentIndex(0)
        logger.debug("RecipeView: activated")
        self._load_pantry()

    def on_deactivate(self) -> None:
        """Called by MainWindow when another view is selected."""
        self._active = False
        self._results_debounce.stop()
        # Cancel any in-flight see-all load so a late result can't repopulate the
        # browse grid after we've navigated away (matches the _results_token bump).
        self._see_all_token[0] += 1
        logger.debug("RecipeView: deactivated")

    def reload(self) -> None:
        """Re-issue all data loads against the *current* config.

        Called by the host (MainWindow) after the user changes Global
        Exclusions, so the pantry / cloud / results re-resolve
        :meth:`_global_exclusion_sets` and drop now-excluded values.  Mirrors
        the loads ``on_activate`` triggers:

        - re-load the pantry (which cascades to the cloud via the currently
          selected facet in ``_on_pantry_loaded``), and
        - re-load the results shelf + YIELDS when a recipe is in progress, so
          the count and cards reflect the new exclusions immediately.

        Safe to call whether the view is visible or not, and a no-op before the
        view has ever been activated (nothing has been loaded yet, so there is
        no stale state to refresh).  The ``_run_query`` token guards drop any
        in-flight result superseded by this reload.
        """
        if not self._active:
            return
        logger.debug("RecipeView: reload (config changed)")
        self._load_pantry()
        # Re-run the teaser results when a recipe is in progress OR the browse
        # drill-down is showing (it may have no ingredients yet still needs to
        # re-resolve the new exclusions).  _on_results_loaded re-seeds the browse
        # page from the fresh teaser once the new total + cards land, so the full
        # grid honors the new exclusions — not just the teaser.
        if self._recipe_includes or self._recipe_excludes or self._stack.currentIndex() == 1:
            self._load_results()

    # ── Public helpers ────────────────────────────────────────────────────

    def clear_recipe(self) -> None:
        """Remove all ingredients and refresh the view."""
        self._recipe_includes.clear()
        self._recipe_excludes.clear()
        self._rail.update_recipe(self._recipe_includes, self._recipe_excludes, 0)
        self._now_plating.load_results([], 0)
        # Rebuild cloud with no states
        self._rebuild_cloud()

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # The view's outer layout holds only a QStackedWidget:
        #   page 0 — the 3-column constructor (Pantry | Now Plating | Recipe rail)
        #   page 1 — the full-results browse grid (reuses Discover's _BrowseView)
        # "Show all →" swaps to page 1; the Recipe chip / browse Back returns to 0.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._stack = QStackedWidget()
        outer.addWidget(self._stack)

        # --- Page 0: the 3-column constructor ---
        constructor = QWidget()
        root = QHBoxLayout(constructor)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # LEFT — pantry sidebar
        self._pantry = _PantrySidebar()
        self._pantry.facet_selected.connect(self._on_facet_selected)
        root.addWidget(self._pantry)

        # Thin separator
        sep_left = QFrame()
        sep_left.setFrameShape(QFrame.Shape.VLine)
        sep_left.setStyleSheet(f"color: {_theme.COLOR_BORDER}; max-width: 1px;")
        root.addWidget(sep_left)

        # CENTER — cloud + now-plating strip
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(16, 12, 16, 0)
        center_layout.setSpacing(0)

        # Stage header (facet name label)
        self._stage_hdr = QLabel("Select a facet from The Pantry")
        self._stage_hdr.setStyleSheet(_theme.RECIPE_STAGE_HDR)
        center_layout.addWidget(self._stage_hdr)

        # WeightedTagCloud — reuse existing widget.  Pin to the top and let it
        # size to its own content (Maximum vertical policy): a facet with few
        # tags no longer leaves a tall dead gap below the cloud — the freed
        # space goes to the Now-Plating grid instead.
        self._cloud = WeightedTagCloud()
        self._cloud.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self._cloud.tag_clicked.connect(self._on_tag_clicked)
        center_layout.addWidget(self._cloud)

        # Now Plating grid — real result cards (reuses Discover card surface +
        # flow layout).  Takes the remaining vertical space below the cloud.
        self._now_plating = _NowPlatingStrip(self._image_cache, self._config)
        self._now_plating.cardClicked.connect(self.channelSelected)
        self._now_plating.cardDoubleClicked.connect(self.playRequested)
        self._now_plating.showAllRequested.connect(self._on_show_all)
        center_layout.addWidget(self._now_plating, stretch=1)

        root.addWidget(center, stretch=1)

        # Thin separator
        sep_right = QFrame()
        sep_right.setFrameShape(QFrame.Shape.VLine)
        sep_right.setStyleSheet(f"color: {_theme.COLOR_BORDER}; max-width: 1px;")
        root.addWidget(sep_right)

        # RIGHT — recipe rail
        self._rail = _RecipeRail()
        self._rail.clear_btn.clicked.connect(self.clear_recipe)
        self._rail.ingredient_remove_requested.connect(self._on_ingredient_remove)
        root.addWidget(self._rail)

        # Constructor is page 0.
        self._stack.addWidget(constructor)

        # --- Page 1: the full-results browse grid (reuses Discover _BrowseView) ---
        from metatv.gui.discover_browse import _BrowseView

        self._browse = _BrowseView(self._image_cache, self._config)
        self._browse.backRequested.connect(self._on_browse_back)
        self._browse.cardClicked.connect(self.channelSelected)
        self._browse.cardDoubleClicked.connect(self.playRequested)
        # Lazy DB pagination: each near-bottom scroll asks for the next page.
        self._browse.loadMoreRequested.connect(self._load_more_see_all)
        # Filter-change: wire into the DB-level filter so every lazy page also
        # respects the filter (Bug D — previously only already-loaded cards were
        # filtered, and new pages appended unfiltered content below them).
        self._browse.filterChanged.connect(self._on_see_all_filter_changed)
        # cardContextMenu intentionally left unconnected — the Now Plating strip
        # has no context-menu wiring, so the browse drill-down matches it (no-op).
        self._stack.addWidget(self._browse)

    # ── Data loading ──────────────────────────────────────────────────────

    def _global_exclusion_sets(self) -> tuple[set[str], set[str]]:
        """Resolve the user's Global Exclusions for the faceted queries.

        The control layer (DR-0007): we read ``Config`` here on the main thread
        and hand plain sets to the engine, which never touches Config itself.

        This delegates to the **same** ``filter_utils`` resolvers the main
        channel list uses (``main_window_channels.py`` ``_query_channels_page``)
        — a single chokepoint, so the recipe view never re-derives the union
        from raw config lists:

        - **excluded_prefixes** = ``get_active_category_filter(config)`` (the
          category blacklist, resolved to leaf prefix codes) ∪
          ``get_excluded_prefixes(config)`` (the explicit "Block [PREFIX]" set).
          ``get_active_category_filter`` is the one place the category-group
          selection is expanded into the leaf codes that match ``detected_prefix``
          / ``detected_region``; hand-rolling ``set(config.…_excluded_categories)``
          here bypassed that expansion, so checked groups never excluded anything.
        - **excluded_categories** = ``global_filter_excluded_user_categories``,
          matched against ``user_category``.

        Both ``filter_utils`` helpers are paused-aware: when
        ``global_filter_paused`` is True they yield no exclusions, so BOTH sets
        come back empty (everything reappears) — same as the main list.

        Returns:
            ``(excluded_prefixes, excluded_categories)`` — two ``set[str]``,
            both empty when global filtering is paused.
        """
        from metatv.core.filter_utils import (
            get_active_category_filter,
            get_excluded_prefixes,
        )

        cfg = self._config
        if getattr(cfg, "global_filter_paused", False):
            return set(), set()
        _cat_excluded, _ = get_active_category_filter(cfg)
        excluded_prefixes: set[str] = set(_cat_excluded or []) | get_excluded_prefixes(cfg)
        excluded_categories: set[str] = set(
            getattr(cfg, "global_filter_excluded_user_categories", []) or []
        )
        return excluded_prefixes, excluded_categories

    def _load_pantry(self) -> None:
        """Load facet summaries from the DB (off-thread)."""
        excl_prefixes, excl_categories = self._global_exclusion_sets()
        self._run_query(
            lambda repos: repos.tags.get_facet_summary(
                excluded_provider_ids=repos.providers.get_hidden_provider_ids(),
                excluded_prefixes=excl_prefixes,
                excluded_categories=excl_categories,
            ),
            self._on_pantry_loaded,
            token_ref=self._pantry_token,
            on_error=self._on_pantry_error,
        )

    def _on_pantry_loaded(self, summaries: list) -> None:
        """Main-thread slot: populate the pantry sidebar."""
        if not self._active:
            return
        self._pantry.load_facets(summaries)
        # If a facet was already selected before reload, keep it
        if self._pantry.selected_facet():
            self._on_facet_selected(self._pantry.selected_facet())

    def _on_pantry_error(self, exc: Exception) -> None:
        logger.error("RecipeView: pantry load failed: {}", exc)
        self._stage_hdr.setText("Couldn't load facets")

    def _load_cloud(self, facet_type: str) -> None:
        """Load tag counts for the selected facet (off-thread)."""
        excl_prefixes, excl_categories = self._global_exclusion_sets()
        self._run_query(
            lambda repos: repos.tags.get_tag_counts_for_facet(
                facet_type,
                excluded_provider_ids=repos.providers.get_hidden_provider_ids(),
                excluded_prefixes=excl_prefixes,
                excluded_categories=excl_categories,
            ),
            self._on_cloud_loaded,
            token_ref=self._cloud_token,
            on_error=self._on_cloud_error,
        )

    def _on_cloud_loaded(self, counts: list) -> None:
        """Main-thread slot: repopulate the WeightedTagCloud."""
        if not self._active:
            return
        self._tag_counts = counts
        self._rebuild_cloud()

    def _on_cloud_error(self, exc: Exception) -> None:
        logger.error("RecipeView: cloud load failed: {}", exc)
        self._stage_hdr.setText("Couldn't load tags")

    def _rebuild_cloud(self) -> None:
        """Re-render the WeightedTagCloud with current tag counts + recipe state."""
        facet = self._selected_facet
        if facet is None:
            return

        meta = _FACET_META.get(facet)
        color = meta[1] if meta else _theme.COLOR_TEXT
        display = meta[0] if meta else facet.title()

        includes = self._recipe_includes.get(facet, set())
        excludes = self._recipe_excludes.get(facet, set())

        # Build items: (value, count, state) — state is "include", "exclude", or "none"
        items: list[tuple[str, int, str]] = []
        for dto in self._tag_counts:
            if dto.value in includes:
                state = "include"
            elif dto.value in excludes:
                state = "exclude"
            else:
                state = "none"
            items.append((dto.value, dto.channel_count, state))

        self._cloud.set_tags(items, facet_color=color, facet_name=display)

    # Result-grid card cap — a gridful of cards.  The bounded preview never
    # materialises the full set: a broad facet costs one SQL COUNT for YIELDS
    # plus a LIMIT slice of <= this many session-free ContentCards.
    _RESULTS_CARD_CAP: int = 60

    # Debounce window for _load_results: rapid successive tag clicks
    # coalesce into one DB round-trip while the rail/cloud update instantly.
    _DEBOUNCE_MS: int = 300

    # "Show all →" lazy-pagination page size — how many cards each near-bottom
    # scroll fetches+appends from the DB.  There is NO hard cap: paging continues
    # until offset >= total, so the browse grid can reach the full match set.
    _SEE_ALL_PAGE: int = 60

    def _load_results(self) -> None:
        """Load the YIELDS count + a bounded set of result cards (off-thread)."""
        # Snapshot recipe state for the lambda (closed over)
        includes = {k: set(v) for k, v in self._recipe_includes.items() if v}
        excludes = {k: set(v) for k, v in self._recipe_excludes.items() if v}
        excl_prefixes, excl_categories = self._global_exclusion_sets()
        cap = self._RESULTS_CARD_CAP

        def _query(repos):
            # Count stays entirely in SQL — a broad facet (e.g. language:English
            # ≈ 170k channels) costs one COUNT, never a 170k-id Python set.  The
            # card sample is a bounded LIMIT slice mapped to session-free
            # ContentCards.  Both are scoped to visible channels on active
            # sources via excluded_provider_ids AND to the user's Global
            # Exclusions, so the shelf agrees with YIELDS and never leaks
            # disabled-source or globally-banished channels.
            hidden = repos.providers.get_hidden_provider_ids()
            total = repos.tags.count_channels_by_tag_facets(
                includes=includes,
                excludes=excludes,
                excluded_provider_ids=hidden,
                excluded_prefixes=excl_prefixes,
                excluded_categories=excl_categories,
                collapse_variants=True,
            )
            if total == 0:
                return ([], 0)
            cards = repos.tags.sample_channels_by_tag_facets(
                includes=includes,
                excludes=excludes,
                excluded_provider_ids=hidden,
                excluded_prefixes=excl_prefixes,
                excluded_categories=excl_categories,
                limit=cap,
                collapse_variants=True,
            )
            return (cards, total)

        self._run_query(
            _query,
            self._on_results_loaded,
            token_ref=self._results_token,
            on_error=self._on_results_error,
        )

    def _on_results_loaded(self, payload: tuple) -> None:
        """Main-thread slot: update 'Now Plating' shelf and recipe rail YIELDS."""
        if not self._active:
            return
        cards, total = payload
        self._now_plating.load_results(cards, total)
        # Update rail with current recipe + count
        self._rail.update_recipe(self._recipe_includes, self._recipe_excludes, total)
        # If the "Show all" browse page is showing, the recipe (or Global
        # Exclusions) just changed underneath it — re-seed it from this fresh
        # teaser so the full-page pagination reflects the new recipe.  Doing this
        # here (rather than in reload()) means the browse re-seeds AFTER the new
        # teaser cards + total have actually landed, never from stale state.
        if self._stack.currentIndex() == 1:
            self._reseed_see_all()

    def _on_results_error(self, exc: Exception) -> None:
        logger.error("RecipeView: results load failed: {}", exc)

    # ── "Show all →" full-results browse drill-down ──────────────────────

    def _browse_title(self) -> str:
        """Build the browse-page title from the recipe name + match count.

        Uses the rail's editorial recipe name when the recipe has ingredients
        (else a neutral "Tonight's Recipe"), suffixed with the live match count
        — e.g. "Late-Night Drama Selection · 366,085 matches".
        """
        total = self._now_plating._total_count
        if self._recipe_includes or self._recipe_excludes:
            name = _generate_recipe_name(self._recipe_includes, self._recipe_excludes)
        else:
            name = "Tonight's Recipe"
        suffix = f"  ·  {total:,} match{'es' if total != 1 else ''}"
        return f"{name}{suffix}"

    def _on_show_all(self) -> None:
        """Swap the bounded teaser for the full-results browse grid.

        Page 1 does ZERO new DB/image work: it seeds the browse grid with the
        cards the teaser already fetched+rendered (≤ :data:`_RESULTS_CARD_CAP`),
        sets the pagination offset to that seed count and the known total to the
        teaser's match total, and flags ``set_has_more`` so the next near-bottom
        scroll pages from the DB via :meth:`_load_more_see_all`.  No big up-front
        fetch.  The shared deterministic ordering of
        ``sample_channels_by_tag_facets`` makes the seeded teaser cards align
        with the DB pages that follow.
        """
        self._stack.setCurrentIndex(1)
        self._reseed_see_all()

    def _reseed_see_all(self) -> None:
        """Reset the browse page to a fresh page-1 seed from the current teaser.

        Loads the browse grid with the cards the teaser already fetched+rendered
        (≤ :data:`_RESULTS_CARD_CAP`) — ZERO new DB/image work — then resets the
        pagination offset to that seed count, the total to the teaser's match
        count, and arms ``set_has_more`` if any matches remain.  Bumps the
        ``_see_all_token`` so any in-flight page from a prior recipe is dropped.
        Shared by :meth:`_on_show_all` (first open) and :meth:`_on_results_loaded`
        (recipe / exclusions changed while browsing).
        """
        # Drop any page request still in flight against the previous recipe.
        self._see_all_token[0] += 1
        # Page 1 = the cards the strip already rendered (zero-latency feedback).
        cached_cards = [w._card for w in self._now_plating._card_widgets]
        self._browse.load(self._browse_title(), cached_cards)
        self._see_all_offset = len(cached_cards)
        self._see_all_total = self._now_plating._total_count
        self._see_all_loading = False
        self._browse.set_has_more(self._see_all_offset < self._see_all_total)

    def _on_browse_back(self) -> None:
        """Browse 'Back' → return to the constructor (page 0)."""
        self._stack.setCurrentIndex(0)

    def _on_see_all_filter_changed(self, text: str) -> None:
        """Filter text changed in the browse view — trigger a SQL-filtered fresh fetch.

        Bug D fix: the previous ``_apply_filter`` in ``_BrowseView`` only
        filtered already-loaded cards.  Lazy-loaded subsequent pages ignored the
        filter and appended everything, making results below the visible viewport
        appear unfiltered.  By re-seeding the browse pagination here — bumping
        the token, resetting offset to 0, and loading the first filtered page
        from the DB — every page (including all subsequent lazy loads) passes
        ``name_filter`` to ``sample_channels_by_tag_facets`` at the SQL level.

        The ``_BrowseView._apply_filter`` still rebuilds the in-memory subset
        immediately (fast feedback while the DB fetch is in flight), but that
        subset is limited to already-loaded cards.  The DB fetch replaces the
        view with the correct full-corpus filtered result once it arrives.

        Clearing the filter (``text == ""``) behaves the same way: a fresh
        unfiltered fetch re-seeds from offset=0.
        """
        # Bump token so any in-flight un-filtered page is dropped.
        self._see_all_token[0] += 1
        self._see_all_loading = False
        self._see_all_offset = 0
        # Total is unknown until the new filtered fetch arrives; assume non-zero
        # so _load_more_see_all can fire.  It will be capped correctly once the
        # first filtered page lands (offset advances; set_has_more compares to total).
        # If the filter yields fewer than one page the offset will meet total and stop.
        # We keep the existing total as an upper bound — it will only over-arm the
        # guard, which is safe (next scroll fires a query that returns 0 cards and
        # stops).
        name_filter = text.strip() or None

        includes = {k: set(v) for k, v in self._recipe_includes.items() if v}
        excludes = {k: set(v) for k, v in self._recipe_excludes.items() if v}
        excl_prefixes, excl_categories = self._global_exclusion_sets()
        limit = self._SEE_ALL_PAGE

        def _query(repos):
            hidden = repos.providers.get_hidden_provider_ids()
            return repos.tags.sample_channels_by_tag_facets(
                includes=includes,
                excludes=excludes,
                excluded_provider_ids=hidden,
                excluded_prefixes=excl_prefixes,
                excluded_categories=excl_categories,
                limit=limit,
                offset=0,
                name_filter=name_filter,
                collapse_variants=True,
            )

        self._run_query(
            _query,
            self._on_see_all_filter_loaded,
            token_ref=self._see_all_token,
            on_error=self._on_see_all_error,
        )

    def _on_see_all_filter_loaded(self, cards: list) -> None:
        """Main-thread slot: replace the browse grid with the first filtered page.

        Called when the DB-side filtered fetch started by
        :meth:`_on_see_all_filter_changed` delivers its first page.  Replaces
        (not appends) the browse view so the user sees only results matching the
        filter string.  Arms ``set_has_more`` so further scrolling lazy-loads
        additional filtered pages.

        ``preserve_filter=True`` is critical here: without it ``load()`` would
        clear the search box, making ``current_filter()`` return ``""`` so the
        next lazy page (``_load_more_see_all``) would fetch unfiltered results
        and append them below the filtered ones (QA bug 10bc0a7 Fix B).
        """
        if not self._active:
            return
        # Replace (not append): load() resets has_more + pending so the
        # pagination state starts clean for the filtered set.
        # preserve_filter=True keeps the search-box text so subsequent lazy
        # pages (via _load_more_see_all → current_filter()) stay filtered.
        self._browse.load(self._browse_title(), cards, preserve_filter=True)
        self._see_all_offset = len(cards)
        self._see_all_loading = False
        self._browse.set_has_more(self._see_all_offset < self._see_all_total)

    def _load_more_see_all(self) -> None:
        """Fetch+append the next browse page from the DB (off-thread).

        Fired by ``_browse.loadMoreRequested`` on a near-bottom scroll.  Pages
        ``_SEE_ALL_PAGE`` cards at a time from ``_see_all_offset``, reusing the
        EXACT scoping as :meth:`_load_results` (Global Exclusions +
        ``get_hidden_provider_ids()``) and the SAME deterministic ordering so the
        page is disjoint from what's already shown.  Guarded by
        ``_see_all_loading`` (no overlapping loads) and ``_see_all_token`` (drop a
        stale page after a recipe change / deactivate).  When a filter is active
        (``_browse.current_filter()`` is non-empty), it is threaded into the
        query so every page respects it at the SQL level.
        """
        if self._see_all_loading or self._see_all_offset >= self._see_all_total:
            return
        self._see_all_loading = True

        includes = {k: set(v) for k, v in self._recipe_includes.items() if v}
        excludes = {k: set(v) for k, v in self._recipe_excludes.items() if v}
        excl_prefixes, excl_categories = self._global_exclusion_sets()
        limit = self._SEE_ALL_PAGE
        offset = self._see_all_offset
        # Thread the current filter text (if any) into the DB query so lazy pages
        # also respect it (Bug D fix — previously new pages ignored the filter).
        name_filter = self._browse.current_filter().strip() or None

        def _query(repos):
            hidden = repos.providers.get_hidden_provider_ids()
            return repos.tags.sample_channels_by_tag_facets(
                includes=includes,
                excludes=excludes,
                excluded_provider_ids=hidden,
                excluded_prefixes=excl_prefixes,
                excluded_categories=excl_categories,
                limit=limit,
                offset=offset,
                name_filter=name_filter,
                collapse_variants=True,
            )

        self._run_query(
            _query,
            self._on_see_all_loaded,
            token_ref=self._see_all_token,
            on_error=self._on_see_all_error,
        )

    def _on_see_all_loaded(self, cards: list) -> None:
        """Main-thread slot: append the fetched page to the browse grid."""
        if not self._active:
            return
        self._browse.append(cards)
        self._see_all_offset += len(cards)
        self._see_all_loading = False
        # Re-arm "has more" (also re-arms the browse debounce) only while pages
        # remain — once offset >= total, no further query can fire.
        self._browse.set_has_more(self._see_all_offset < self._see_all_total)

    def _on_see_all_error(self, exc: Exception) -> None:
        logger.error("RecipeView: see-all load failed: {}", exc)
        self._see_all_loading = False

    # ── Event handlers ────────────────────────────────────────────────────

    def _on_facet_selected(self, facet_type: str) -> None:
        """User clicked a facet row in the Pantry."""
        self._selected_facet = facet_type
        meta = _FACET_META.get(facet_type)
        display = meta[0] if meta else facet_type.title()
        self._stage_hdr.setText(display)
        self._tag_counts = []
        self._load_cloud(facet_type)

    def _on_tag_clicked(self, value: str) -> None:
        """Cycle a tag through none → include → exclude → none.

        Called when the user clicks a tag in the WeightedTagCloud.
        """
        facet = self._selected_facet
        if facet is None:
            return

        inc = self._recipe_includes.setdefault(facet, set())
        exc = self._recipe_excludes.setdefault(facet, set())

        if value in inc:
            # include → exclude
            inc.discard(value)
            exc.add(value)
            logger.debug("RecipeView: {} {} → exclude", facet, value)
        elif value in exc:
            # exclude → none
            exc.discard(value)
            logger.debug("RecipeView: {} {} → none", facet, value)
        else:
            # none → include
            inc.add(value)
            logger.debug("RecipeView: {} {} → include", facet, value)

        # Prune empty sets
        if not inc:
            self._recipe_includes.pop(facet, None)
        if not exc:
            self._recipe_excludes.pop(facet, None)

        # Re-render rail + cloud immediately (pure in-memory — no DB wait),
        # then fire the debounced results load so rapid clicks coalesce.
        self._rail.update_recipe(self._recipe_includes, self._recipe_excludes, None)
        self._rebuild_cloud()
        self._results_debounce.start()

    def _on_ingredient_remove(self, facet_type: str, value: str) -> None:
        """Remove an ingredient chip from the recipe rail (cycles state → none)."""
        self._recipe_includes.get(facet_type, set()).discard(value)
        self._recipe_excludes.get(facet_type, set()).discard(value)

        # Prune empty sets
        if not self._recipe_includes.get(facet_type):
            self._recipe_includes.pop(facet_type, None)
        if not self._recipe_excludes.get(facet_type):
            self._recipe_excludes.pop(facet_type, None)

        # Render rail + cloud immediately; debounce the expensive DB count.
        self._rail.update_recipe(self._recipe_includes, self._recipe_excludes, None)
        self._rebuild_cloud()
        self._results_debounce.start()

    # ── Accessors (for tests) ─────────────────────────────────────────────

    @property
    def recipe_includes(self) -> dict[str, set[str]]:
        """Current include recipe state (read-only view for tests)."""
        return self._recipe_includes

    @property
    def recipe_excludes(self) -> dict[str, set[str]]:
        """Current exclude recipe state (read-only view for tests)."""
        return self._recipe_excludes

    @property
    def selected_facet(self) -> str | None:
        """Currently selected facet type (read-only for tests)."""
        return self._selected_facet
