"""Recipe view helper widgets — Pantry, Tonight's Recipe rail, Now Plating grid.

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
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from metatv.core.recipe_state import rating_range_is_full
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.rating_range_slider import RatingRangeSlider, format_rating_range

if TYPE_CHECKING:
    from metatv.core.repositories.dtos import FacetSummaryDTO


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
        self._display_name = display_name
        self._distinct_values = distinct_values
        self._match_count = 0   # cross-facet search match count (0 → no badge)

        # Build label: "■ Genre    512"
        self._refresh_label()
        self._apply_style()

    # ── public ────────────────────────────────────────────────────────────

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._apply_style()

    def is_selected(self) -> bool:
        return self._selected

    def set_match_count(self, n: int) -> None:
        """Set the cross-facet search match badge ("·N"); 0 hides it."""
        self._match_count = max(0, int(n))
        self._refresh_label()

    # ── private ───────────────────────────────────────────────────────────

    def _refresh_label(self) -> None:
        """Rebuild the row label, appending a subtle "·N" badge when matches exist."""
        text = f"■ {self._display_name}   {self._distinct_values:,}"
        tip = f"{self._display_name} — {self._distinct_values:,} distinct values in your library"
        if self._match_count:
            text += f"   ·{self._match_count}"
            tip = (
                f"{self._display_name} — {self._match_count} value"
                f"{'s' if self._match_count != 1 else ''} match your search"
            )
        self.setText(text)
        self.setToolTip(tip)

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

    Emits ``facet_selected(facet_type)`` when the user clicks a facet row, and
    ``search_changed(text)`` (debounced) when the search box text settles — the
    owner runs the cross-facet tag search off-thread and fills the center cloud.
    """

    facet_selected = pyqtSignal(str)          # facet_type string
    search_changed = pyqtSignal(str)          # debounced search text (stripped)
    rating_range_changed = pyqtSignal(float, float)  # (min, max) from the slider
    saved_recipe_selected = pyqtSignal(str)   # saved-recipe name → load into builder
    saved_recipe_deleted = pyqtSignal(str)    # saved-recipe name → remove

    # Debounce window for the search box: rapid keystrokes coalesce into one
    # cross-facet DB query while the box stays responsive.
    _SEARCH_DEBOUNCE_MS: int = 220

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(212)
        self.setStyleSheet(_theme.RECIPE_PANTRY_BG)
        self._facet_buttons: list[_FacetRowButton] = []
        self._selected_facet: str | None = None
        self._saved_rows: list[QWidget] = []

        # Restartable single-shot timer — coalesces keystrokes into one emit.
        self._search_debounce = QTimer(self)
        self._search_debounce.setSingleShot(True)
        self._search_debounce.setInterval(self._SEARCH_DEBOUNCE_MS)
        self._search_debounce.timeout.connect(self._emit_search)

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

    def preselect_facet(self, facet_type: str) -> None:
        """Mark *facet_type* as selected without emitting ``facet_selected``.

        Used when the view is seeded externally (the details-pane tag right-click
        → Discover path) before the pantry rows have loaded: setting the selection
        here means a subsequent async ``load_facets`` keeps it (it only
        auto-selects the first facet when nothing is selected yet), and any rows
        that already exist get their selected style applied.
        """
        self._selected_facet = facet_type
        for btn in self._facet_buttons:
            btn.set_selected(btn.facet_type == facet_type)

    # ── private ───────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 12, 8, 8)
        outer.setSpacing(0)

        # "THE PANTRY" header
        pantry_hdr = QLabel("THE PANTRY")
        pantry_hdr.setStyleSheet(_theme.RECIPE_PANTRY_HDR)
        outer.addWidget(pantry_hdr)

        # Filter row: search box + × clear button
        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(0, 4, 0, 2)
        filter_row.setSpacing(4)

        self._filter_box = QLineEdit()
        self._filter_box.setPlaceholderText("Search tags…")
        self._filter_box.setToolTip("Search tags across all facets")
        self._filter_box.setClearButtonEnabled(True)
        self._filter_box.textChanged.connect(self._on_search_text)
        filter_row.addWidget(self._filter_box)

        outer.addLayout(filter_row)

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

        # ── RATING ingredient (the first non-tag ingredient) ──
        rating_hdr_row = QHBoxLayout()
        rating_hdr_row.setContentsMargins(0, 0, 0, 0)
        rating_hdr_row.setSpacing(4)
        rating_hdr = QLabel("RATING")
        rating_hdr.setStyleSheet(_theme.RECIPE_RATING_HDR)
        rating_hdr_row.addWidget(rating_hdr)
        rating_hdr_row.addStretch()
        self._rating_readout = QLabel(format_rating_range(
            RatingRangeSlider.MIN, RatingRangeSlider.MAX))
        self._rating_readout.setStyleSheet(_theme.RECIPE_RATING_READOUT)
        self._rating_readout.setToolTip(
            "Rating band for results (0–10). A minimum of 0 includes unrated content."
        )
        rating_hdr_row.addWidget(self._rating_readout)
        outer.addLayout(rating_hdr_row)

        self._rating_slider = RatingRangeSlider()
        self._rating_slider.rangeChanged.connect(self._on_rating_slider_changed)
        outer.addWidget(self._rating_slider)

        # Divider
        line2 = QFrame()
        line2.setFrameShape(QFrame.Shape.HLine)
        line2.setStyleSheet(_theme.SEPARATOR_H)
        outer.addWidget(line2)

        # "SAVED RECIPES" header + dynamic list (populated via load_saved_recipes)
        saved_hdr = QLabel("SAVED RECIPES")
        saved_hdr.setStyleSheet(_theme.RECIPE_PANTRY_HDR)
        outer.addWidget(saved_hdr)

        self._saved_empty = QLabel("No saved recipes yet")
        self._saved_empty.setStyleSheet(_theme.RECIPE_SAVED_EMPTY)
        self._saved_empty.setToolTip("Build a recipe, then use Save Recipe to keep it here")
        outer.addWidget(self._saved_empty)

        self._saved_layout = QVBoxLayout()
        self._saved_layout.setContentsMargins(0, 0, 0, 0)
        self._saved_layout.setSpacing(1)
        outer.addLayout(self._saved_layout)

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

    def _on_search_text(self, text: str) -> None:
        """Debounce the search box; emit empty immediately so clearing is instant.

        Cross-facet search (non-empty) is debounced so fast typing coalesces into
        one DB round-trip.  Clearing the box restores today's selected-facet cloud,
        so we emit ``""`` synchronously (no idle wait) and stop any pending timer.
        """
        if not text.strip():
            self._search_debounce.stop()
            self.search_changed.emit("")
        else:
            self._search_debounce.start()

    def _emit_search(self) -> None:
        """Debounce timeout: emit the current (stripped) search text."""
        self.search_changed.emit(self._filter_box.text().strip())

    def set_match_counts(self, counts: dict[str, int]) -> None:
        """Show a "·N" badge on each facet row (N = matching values in that facet)."""
        for btn in self._facet_buttons:
            btn.set_match_count(counts.get(btn.facet_type, 0))

    def clear_match_counts(self) -> None:
        """Remove all per-facet match badges (empty search)."""
        for btn in self._facet_buttons:
            btn.set_match_count(0)

    def clear_filter(self) -> None:
        """Clear the pantry search box (restores the selected-facet cloud)."""
        self._filter_box.clear()

    # ── Rating ingredient ─────────────────────────────────────────────────

    def set_rating_range(self, lo: float, hi: float) -> None:
        """Restore the rating slider + readout to ``(lo, hi)`` WITHOUT emitting.

        Used for silent state restoration (loading a saved recipe / clearing the
        recipe), so setting the slider never re-fires the query.
        """
        self._rating_slider.set_values(lo, hi, emit=False)
        self._rating_readout.setText(format_rating_range(lo, hi))

    def _on_rating_slider_changed(self, lo: float, hi: float) -> None:
        """Slider moved → refresh the readout and forward the change to the host."""
        self._rating_readout.setText(format_rating_range(lo, hi))
        self.rating_range_changed.emit(lo, hi)

    # ── Saved recipes ─────────────────────────────────────────────────────

    def load_saved_recipes(self, recipes: list[dict]) -> None:
        """Populate the SAVED RECIPES list from persisted recipe dicts.

        Each row loads the recipe on click (``saved_recipe_selected``) and
        carries a compact "×" to remove it (``saved_recipe_deleted``).  The
        empty-state line shows only when there are no saved recipes.

        Args:
            recipes: The stored recipe dicts (each with a ``name`` key) from
                ``Config.recipe_saved``.
        """
        _clear_layout(self._saved_layout)
        self._saved_rows = []
        self._saved_empty.setVisible(not recipes)
        for rec in recipes:
            name = str(rec.get("name") or "Untitled recipe")
            row = _SavedRecipeRow(name)
            row.load_requested.connect(self.saved_recipe_selected)
            row.delete_requested.connect(self.saved_recipe_deleted)
            self._saved_layout.addWidget(row)
            self._saved_rows.append(row)


# ---------------------------------------------------------------------------
# Saved-recipe row
# ---------------------------------------------------------------------------

class _SavedRecipeRow(QWidget):
    """One saved-recipe row: a click-to-load name button + a "×" delete button.

    Both children are ``QPushButton``s, so the pointing-hand affordance is
    automatic (per the app-wide cursor rule — buttons qualify for free).
    """

    load_requested = pyqtSignal(str)     # recipe name
    delete_requested = pyqtSignal(str)   # recipe name

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._name = name
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._load_btn = QPushButton(f"{_icons.recipe_icon} {name}")
        self._load_btn.setStyleSheet(_theme.RECIPE_SAVED_ROW)
        self._load_btn.setToolTip(f"Load “{name}” into the recipe builder")
        self._load_btn.clicked.connect(lambda: self.load_requested.emit(self._name))
        layout.addWidget(self._load_btn, stretch=1)

        self._delete_btn = QPushButton(_icons.recipe_clear_icon)
        self._delete_btn.setStyleSheet(_theme.RECIPE_SAVED_DELETE)
        self._delete_btn.setToolTip(f"Delete “{name}”")
        self._delete_btn.clicked.connect(lambda: self.delete_requested.emit(self._name))
        layout.addWidget(self._delete_btn)


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
        # Slimmer than the pre-redesign 328: with "× Clear" moved into the title
        # row and Save alone at content width, the button row no longer drives
        # the card's minimum width, so column 1 can be narrower (Deliverable A).
        self.setFixedWidth(272)
        self.setStyleSheet(_theme.RECIPE_RAIL_BG)
        self._build_ui()

    # ── public ────────────────────────────────────────────────────────────

    def update_recipe(
        self,
        includes: dict[str, set[str]],
        excludes: dict[str, set[str]],
        match_count: int | None,
        rating_range: tuple[float, float] | None = None,
    ) -> None:
        """Re-render the recipe rail with the current recipe state.

        Args:
            includes: facet_type → set of included values.
            excludes: facet_type → set of excluded values.
            match_count: Number of matching channels for the YIELDS display, or
                ``None`` when the count is still pending (shows "counting…").
            rating_range: Active ``(min, max)`` rating band, or ``None`` when no
                rating filter is set.  A bounded band renders a "RATING" menu
                line among the ingredient roles (e.g. "≥ 7.0" / "6.0 – 8.0").
        """
        # Update editorial name.  A rating-only recipe (no tags) would otherwise
        # read "Your recipe is empty" beside a live RATING line — name it for the
        # band instead so the card stays coherent.
        name = _generate_recipe_name(includes, excludes)
        if (
            not includes
            and not excludes
            and rating_range is not None
            and not rating_range_is_full(rating_range)
        ):
            name = f"Rated {format_rating_range(rating_range[0], rating_range[1])}"
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

        # RATING menu line — the first non-tag ingredient.  Shown only when a
        # bound bites (a full 0–10 span is "no filter" and stays hidden).
        if rating_range is not None and not rating_range_is_full(rating_range):
            has_ingredients = True
            rating_lbl = QLabel("RATING")
            rating_lbl.setStyleSheet(_theme.RECIPE_ROLE_LABEL)
            self._ingredients_layout.addWidget(rating_lbl)
            value_lbl = QLabel(
                f"{_icons.rating_star_icon} "
                f"{format_rating_range(rating_range[0], rating_range[1])}"
            )
            value_lbl.setStyleSheet(_theme.RECIPE_RATING_LINE)
            self._ingredients_layout.addWidget(value_lbl)

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

        # Title row: "TONIGHT'S RECIPE" header + a compact, right-aligned
        # "× Clear" (Deliverable A — moved out of the footer so the button row
        # no longer drives the card's minimum width).
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(4)
        rail_hdr = QLabel("TONIGHT'S RECIPE")
        rail_hdr.setStyleSheet(_theme.RECIPE_RAIL_HDR)
        title_row.addWidget(rail_hdr)
        title_row.addStretch()

        self.clear_btn = QPushButton(f"{_icons.recipe_clear_icon} Clear")
        self.clear_btn.setStyleSheet(_theme.RECIPE_CARD_CLEAR)
        self.clear_btn.setToolTip("Remove all ingredients from the recipe")
        title_row.addWidget(self.clear_btn)
        outer.addLayout(title_row)

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

        # Footer: Save Recipe stands ALONE at content width (Deliverable A) — a
        # trailing stretch keeps it left-aligned and unstretched, so the footer's
        # minimum width is just this one button's, not a two-button row's.
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.save_btn = QPushButton(f"{_icons.recipe_save_icon} Save Recipe")
        self.save_btn.setEnabled(False)   # enabled by the host once a recipe has ingredients
        self.save_btn.setStyleSheet(_theme.RECIPE_SAVE_BTN)
        self.save_btn.setToolTip("Save this recipe for quick access")
        btn_row.addWidget(self.save_btn)
        btn_row.addStretch()

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

