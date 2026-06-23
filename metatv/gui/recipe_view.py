"""RecipeView — tag-cloud "Recipe" builder (task #56, slice 3).

Three-column view reached via the ✦ Recipe nav chip:

    LEFT  (~212 px) — "THE PANTRY" facet sidebar: one row per facet from
                      get_facet_summary(); a stub "SAVED RECIPES" section below.
    CENTER           — WeightedTagCloud for the selected facet + "Now plating"
                      live results strip (poster titles matching the recipe).
    RIGHT (~328 px)  — "TONIGHT'S RECIPE" rail with role-grouped ingredient
                      chips, OMIT section, YIELDS count, Save (stub) + Clear.

Slice 4 TODO: saved-recipe persistence, pinned/excluded individual titles.

Data wiring (all DB reads off the main thread via the owner's _run_query seam):
  - Pantry  ← TagRepository.get_facet_summary(excluded_provider_ids)
  - Cloud   ← TagRepository.get_tag_counts_for_facet(facet, excluded_provider_ids)
  - Results ← TagRepository.get_channel_ids_by_tag_facets(includes, excludes,
                base_channel_ids=<active scoped set>)
              then ChannelRepository.get_all(ids) for card titles/logos.

Scoping follows DR-0007: the engine is agnostic; we pass
ProviderRepository.get_hidden_provider_ids() everywhere.
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
_FACET_META: dict[str, tuple[str, str, str]] = {
    "genre":      ("Genre",      _theme.COLOR_FACET_GENRE,      "BASE"),
    "language":   ("Language",   _theme.COLOR_FACET_LANGUAGE,   "IN"),
    "region":     ("Region",     _theme.COLOR_FACET_REGION,     "FROM"),
    "platform":   ("Platform",   _theme.COLOR_FACET_PLATFORM,   "ON"),
    "decade":     ("Decade",     _theme.COLOR_FACET_DECADE,     "ERA"),
    "quality":    ("Quality",    _theme.COLOR_FACET_QUALITY,    "FINISH"),
    "collection": ("Collection", _theme.COLOR_FACET_COLLECTION, "SET"),
}

# Role display order in the recipe rail
_ROLE_ORDER: list[str] = ["BASE", "IN", "FROM", "ON", "ERA", "FINISH", "SET"]


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
        match_count: int,
    ) -> None:
        """Re-render the recipe rail with the current recipe state.

        Args:
            includes: facet_type → set of included values.
            excludes: facet_type → set of excluded values.
            match_count: Number of matching channels for the YIELDS display.
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
# Now Plating results strip
# ---------------------------------------------------------------------------

class _NowPlatingStrip(QWidget):
    """Horizontal scroll strip showing channel title cards for the recipe match.

    Shows compact title chips rather than full poster cards (poster cards
    require ImageCache + async loading that would couple this widget to the
    parent window lifecycle — the strip is intentionally simple for slice 3).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    # ── public ────────────────────────────────────────────────────────────

    def load_results(self, names: list[str], total_count: int) -> None:
        """Populate the strip with channel name chips.

        Args:
            names:       Sample channel display names (up to ~20).
            total_count: Total number of matching channels (for the header).
        """
        self._hdr.setText(
            f"NOW PLATING  ·  {total_count:,} match{'es' if total_count != 1 else ''}"
        )
        _clear_layout(self._chips_layout)

        if not names:
            placeholder = QLabel("No channels match this recipe yet")
            placeholder.setStyleSheet(
                f"color: {_theme.COLOR_RECIPE_MUTED_2}; font-size: {_theme.FONT_MD};"
            )
            self._chips_layout.addWidget(placeholder)
        else:
            for name in names[:20]:
                chip = QLabel(name)
                chip.setStyleSheet(
                    f"color: {_theme.COLOR_RECIPE_TEXT}; font-size: {_theme.FONT_MD};"
                    f" background: {_theme.OVERLAY_05}; border: 1px solid {_theme.COLOR_BORDER};"
                    f" border-radius: 4px; padding: 3px 8px;"
                )
                self._chips_layout.addWidget(chip)

            if total_count > 20:
                more = QLabel(f"+ {total_count - 20:,} more…")
                more.setStyleSheet(
                    f"color: {_theme.COLOR_RECIPE_MUTED}; font-size: {_theme.FONT_MD};"
                )
                self._chips_layout.addWidget(more)

        self._chips_layout.addStretch()

    # ── private ───────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(4)

        # Divider
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(_theme.SEPARATOR_H)
        outer.addWidget(line)

        self._hdr = QLabel("NOW PLATING  ·  0 matches")
        self._hdr.setStyleSheet(_theme.RECIPE_NOW_PLATING_HDR)
        outer.addWidget(self._hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFixedHeight(50)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        chips_widget = QWidget()
        chips_widget.setStyleSheet("background: transparent;")
        self._chips_layout = QHBoxLayout(chips_widget)
        self._chips_layout.setContentsMargins(0, 0, 0, 0)
        self._chips_layout.setSpacing(6)
        self._chips_layout.addStretch()

        scroll.setWidget(chips_widget)
        outer.addWidget(scroll)


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

    def __init__(
        self,
        db: Database,
        config: Config,
        run_query_fn,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._db = db
        self._config = config
        self._run_query = run_query_fn

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

        self._build_ui()

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def on_activate(self) -> None:
        """Called by MainWindow when this view becomes visible."""
        self._active = True
        logger.debug("RecipeView: activated")
        self._load_pantry()

    def on_deactivate(self) -> None:
        """Called by MainWindow when another view is selected."""
        self._active = False
        logger.debug("RecipeView: deactivated")

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
        root = QHBoxLayout(self)
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

        # WeightedTagCloud — reuse existing widget
        self._cloud = WeightedTagCloud()
        self._cloud.tag_clicked.connect(self._on_tag_clicked)
        center_layout.addWidget(self._cloud, stretch=1)

        # Now Plating strip
        self._now_plating = _NowPlatingStrip()
        center_layout.addWidget(self._now_plating)

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

    # ── Data loading ──────────────────────────────────────────────────────

    def _global_exclusion_sets(self) -> tuple[set[str], set[str]]:
        """Resolve the user's Global Exclusions for the faceted queries.

        The control layer (DR-0007): we read ``Config`` here on the main thread
        and hand plain sets to the engine, which never touches Config itself.
        The semantics replicate the main channel list exactly
        (``main_window_channels.py``):

        - **excluded_prefixes** = the union of ``global_filter_excluded_categories``
          (the category blacklist) and ``global_filter_excluded_prefixes`` (the
          explicit "Block [PREFIX]" set).  Matched against ``detected_prefix``
          AND ``detected_region`` downstream.
        - **excluded_categories** = ``global_filter_excluded_user_categories``,
          matched against ``user_category``.

        When ``global_filter_paused`` is True the user has temporarily disabled
        all global filtering, so BOTH sets are empty (everything reappears) —
        same as the main list.

        Returns:
            ``(excluded_prefixes, excluded_categories)`` — two ``set[str]``,
            both empty when global filtering is paused.
        """
        cfg = self._config
        if getattr(cfg, "global_filter_paused", False):
            return set(), set()
        excluded_prefixes: set[str] = (
            set(getattr(cfg, "global_filter_excluded_categories", []) or [])
            | set(getattr(cfg, "global_filter_excluded_prefixes", []) or [])
        )
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

    def _load_results(self) -> None:
        """Load channel IDs matching current recipe (off-thread), then fetch names."""
        # Snapshot recipe state for the lambda (closed over)
        includes = {k: set(v) for k, v in self._recipe_includes.items() if v}
        excludes = {k: set(v) for k, v in self._recipe_excludes.items() if v}
        excl_prefixes, excl_categories = self._global_exclusion_sets()

        def _query(repos):
            # Count + preview stay entirely in SQL — a broad facet (e.g.
            # language:English ≈ 170k channels) costs one COUNT and a LIMIT 20,
            # never a 170k-id Python set.  Both are scoped to visible channels on
            # active sources via excluded_provider_ids AND to the user's Global
            # Exclusions, so YIELDS agrees with the pantry/cloud counts and never
            # leaks disabled-source or globally-banished channels.
            hidden = repos.providers.get_hidden_provider_ids()
            total = repos.tags.count_channels_by_tag_facets(
                includes=includes,
                excludes=excludes,
                excluded_provider_ids=hidden,
                excluded_prefixes=excl_prefixes,
                excluded_categories=excl_categories,
            )
            if total == 0:
                return ([], 0)
            names = repos.tags.sample_channel_names_by_tag_facets(
                includes=includes,
                excludes=excludes,
                excluded_provider_ids=hidden,
                excluded_prefixes=excl_prefixes,
                excluded_categories=excl_categories,
                limit=20,
            )
            return (names, total)

        self._run_query(
            _query,
            self._on_results_loaded,
            token_ref=self._results_token,
            on_error=self._on_results_error,
        )

    def _on_results_loaded(self, payload: tuple) -> None:
        """Main-thread slot: update 'Now plating' strip and recipe rail YIELDS."""
        if not self._active:
            return
        names, total = payload
        self._now_plating.load_results(names, total)
        # Update rail with current recipe + count
        self._rail.update_recipe(self._recipe_includes, self._recipe_excludes, total)

    def _on_results_error(self, exc: Exception) -> None:
        logger.error("RecipeView: results load failed: {}", exc)

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

        # Re-render cloud to reflect new state, then reload results
        self._rebuild_cloud()
        self._load_results()

    def _on_ingredient_remove(self, facet_type: str, value: str) -> None:
        """Remove an ingredient chip from the recipe rail (cycles state → none)."""
        self._recipe_includes.get(facet_type, set()).discard(value)
        self._recipe_excludes.get(facet_type, set()).discard(value)

        # Prune empty sets
        if not self._recipe_includes.get(facet_type):
            self._recipe_includes.pop(facet_type, None)
        if not self._recipe_excludes.get(facet_type):
            self._recipe_excludes.pop(facet_type, None)

        self._rebuild_cloud()
        self._load_results()

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
