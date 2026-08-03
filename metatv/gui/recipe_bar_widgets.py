"""Recipe view — the sub-tab bar, one-line recipe "sentence" bar, and the
Discover-style "Matching Content" horizontal shelf.

These are the leaf presentation widgets introduced by the masonry redesign
(porting the locked HTML mockup).  They own no DB access and no async seam — the
:class:`~metatv.gui.recipe_view.RecipeView` host wires their signals to its
``_run_query`` reads.  Split out of ``recipe_widgets.py`` to keep every recipe
file well under the 1000-line limit and one concern per file.

  * :class:`_RecipeTabBar`   — the "Recipe" | "Saved" pill toggle.
  * :class:`_RecipeBar`      — the slim one-line recipe sentence + Save/Clear.
  * :class:`_MatchingShelf`  — a horizontal scroll shelf of result cards + Show all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.recipe_widgets import (
    _ROLE_ORDER,
    _facet_chip_style,
    _facet_color,
    _facet_role,
)
from metatv.gui.weighted_tag_cloud import _FlowLayout

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.image_cache import ImageCache


# ---------------------------------------------------------------------------
# Sub-tab bar: "Recipe" | "Saved"
# ---------------------------------------------------------------------------

class _RecipeTabBar(QWidget):
    """A two-pill toggle switching the Recipe view between builder and Saved.

    Emits ``tab_changed(index)`` — 0 = Recipe (builder), 1 = Saved.  The active
    pill is the non-color cue (border + filled background), so state never rides
    on color alone.
    """

    tab_changed = pyqtSignal(int)   # 0 = Recipe, 1 = Saved

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(_theme.RECIPE_TABBAR_BG)
        self._index = 0

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 12, 6)
        row.setSpacing(4)

        self._recipe_btn = QPushButton(f"{_icons.recipe_icon} Recipe")
        self._recipe_btn.setToolTip("Build a recipe from facet tags")
        self._recipe_btn.clicked.connect(lambda: self.set_index(0, emit=True))
        row.addWidget(self._recipe_btn)

        self._saved_btn = QPushButton("Saved")
        self._saved_btn.setToolTip("Your saved recipes")
        self._saved_btn.clicked.connect(lambda: self.set_index(1, emit=True))
        row.addWidget(self._saved_btn)

        row.addStretch()

        self._hint = QLabel("Click a tag to add it · click a facet name to drill in")
        self._hint.setStyleSheet(_theme.RECIPE_TABBAR_HINT)
        row.addWidget(self._hint)

        self._apply()

    # ── public ────────────────────────────────────────────────────────────

    def index(self) -> int:
        return self._index

    def set_index(self, index: int, *, emit: bool = False) -> None:
        """Select a tab (0 = Recipe, 1 = Saved); optionally emit ``tab_changed``."""
        index = 1 if index else 0
        changed = index != self._index
        self._index = index
        self._apply()
        if emit and changed:
            self.tab_changed.emit(index)

    # ── private ───────────────────────────────────────────────────────────

    def _apply(self) -> None:
        for i, btn in ((0, self._recipe_btn), (1, self._saved_btn)):
            active = i == self._index
            btn.setStyleSheet(_theme.RECIPE_TAB_ACTIVE if active else _theme.RECIPE_TAB)

    def refresh_theme(self) -> None:
        """Re-apply the active palette to this bar's own chrome (background,
        hint label) and the pill buttons, reusing :meth:`_apply` — the same
        active/inactive styling logic ``set_index`` already drives — so the
        pill-state semantics are never duplicated.
        """
        self.setStyleSheet(_theme.RECIPE_TABBAR_BG)
        self._hint.setStyleSheet(_theme.RECIPE_TABBAR_HINT)
        self._apply()


# ---------------------------------------------------------------------------
# One-line recipe "sentence" bar
# ---------------------------------------------------------------------------

class _IngredientFlow(QWidget):
    """Wrapping row of ingredient pills for the recipe bar.

    Reuses the shared ``_FlowLayout`` primitive so chips wrap to a second line
    only when the bar overflows.  Each pill is facet-colored (composed from theme
    tokens via :func:`_facet_chip_style`); clicking a pill removes that
    ingredient (``remove_clicked(facet_type, value)``).
    """

    remove_clicked = pyqtSignal(str, str)   # (facet_type, value)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._flow = _FlowLayout(self, h_spacing=7, v_spacing=6)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def set_ingredients(self, ingredients: list[tuple[str, str, bool]]) -> None:
        """Render *(facet_type, value, excluded)* pills, wiping any previous ones."""
        self._flow.clear()
        for facet_type, value, excluded in ingredients:
            icon = _icons.tag_exclude_icon if excluded else ""
            label = f"{icon} {value}  {_icons.close_icon}".strip()
            chip = QPushButton(label)
            chip.setStyleSheet(_facet_chip_style(_facet_color(facet_type), excluded=excluded))
            chip.setToolTip(f"Click to remove '{value}' from the recipe")
            chip.clicked.connect(self._make_handler(facet_type, value))
            self._flow.add(chip)
            chip.show()
        self.refresh_layout()

    def refresh_layout(self) -> int:
        h = self._flow.relayout(max(1, self.width()))
        self.setFixedHeight(max(1, h))
        return h

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self.refresh_layout()

    def _make_handler(self, facet_type: str, value: str):
        def _h() -> None:
            self.remove_clicked.emit(facet_type, value)
        return _h


class _RecipeBar(QWidget):
    """The slim one-line recipe "sentence": Recipe: <chips> → N titles [Save][Clear].

    Replaces the tall Tonight's-Recipe column.  Ingredient pills wrap to a second
    line only when overloaded.  Region ingredients show CODES (ES/US), never
    expanded country names — the pill text is the stored tag value verbatim.

    Emits ``ingredient_remove_requested(facet, value)``, ``save_requested()`` and
    ``clear_requested()``.  ``update_recipe`` drives the whole render.
    """

    ingredient_remove_requested = pyqtSignal(str, str)   # (facet_type, value)
    save_requested              = pyqtSignal()
    clear_requested             = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("recipeBar")
        self.setStyleSheet(_theme.RECIPE_BAR_BG)
        self._build_ui()

    # ── public ────────────────────────────────────────────────────────────

    def update_recipe(
        self,
        includes: dict[str, set[str]],
        excludes: dict[str, set[str]],
        match_count: int | None,
    ) -> None:
        """Re-render the ingredient sentence + yield + action enablement.

        Args:
            includes: facet_type → set of included values.
            excludes: facet_type → set of excluded values.
            match_count: Number of matching titles for the yield display, or
                ``None`` when the count is still pending (shows "…").
        """
        # Build the ordered ingredient list: includes by role order, then excludes.
        ings: list[tuple[str, str, bool]] = []
        for role in _ROLE_ORDER:
            for ftype, vals in includes.items():
                if vals and _facet_role(ftype) == role:
                    for v in sorted(vals):
                        ings.append((ftype, v, False))
        for ftype, vals in excludes.items():
            for v in sorted(vals or ()):
                ings.append((ftype, v, True))

        has = bool(ings)
        self._empty_lbl.setVisible(not has)
        self._ings.setVisible(has)
        self._ings.set_ingredients(ings)

        if match_count is None:
            self._yield_lbl.setText("→ …")
        else:
            self._yield_lbl.setText(
                f'→ <b style="color:{_theme.COLOR_GOLD};">{match_count:,}</b> '
                f'title{"" if match_count == 1 else "s"}'
            )
        self.save_btn.setEnabled(has)
        self.clear_btn.setEnabled(has)

    # ── private ───────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        row = QHBoxLayout(self)
        row.setContentsMargins(20, 9, 20, 9)
        row.setSpacing(12)

        self._recipe_label = QLabel("RECIPE")
        self._recipe_label.setStyleSheet(_theme.RECIPE_BAR_LABEL)
        self._recipe_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._recipe_label)

        self._ings = _IngredientFlow()
        self._ings.remove_clicked.connect(self.ingredient_remove_requested)
        row.addWidget(self._ings, stretch=1)

        self._empty_lbl = QLabel("Your recipe is empty — click any tag above to add it")
        self._empty_lbl.setStyleSheet(_theme.RECIPE_BAR_EMPTY)
        row.addWidget(self._empty_lbl, stretch=1)

        self._yield_lbl = QLabel("→ 0 titles")
        self._yield_lbl.setStyleSheet(_theme.RECIPE_BAR_YIELD)
        self._yield_lbl.setTextFormat(Qt.TextFormat.RichText)
        row.addWidget(self._yield_lbl)

        self.save_btn = QPushButton(f"{_icons.recipe_icon} Save")
        self.save_btn.setStyleSheet(_theme.RECIPE_BAR_SAVE_BTN)
        self.save_btn.setToolTip("Save this recipe to the Saved tab")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self.save_requested)
        row.addWidget(self.save_btn)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setStyleSheet(_theme.RECIPE_BAR_CLEAR_BTN)
        self.clear_btn.setToolTip("Remove all ingredients from the recipe")
        self.clear_btn.setEnabled(False)
        self.clear_btn.clicked.connect(self.clear_requested)
        row.addWidget(self.clear_btn)

        # Empty by default: hide the ingredient flow, show the empty hint.
        self._ings.setVisible(False)

    def refresh_theme(self) -> None:
        """Re-apply the active palette to this bar's own persistent chrome —
        background, "RECIPE" label, empty hint, yield label, and the Save/Clear
        buttons — all styled once at construction. Ingredient pills are rebuilt
        fresh from current tokens on every ``update_recipe()`` call, so they
        need no sweep entry here.
        """
        self.setStyleSheet(_theme.RECIPE_BAR_BG)
        self._recipe_label.setStyleSheet(_theme.RECIPE_BAR_LABEL)
        self._empty_lbl.setStyleSheet(_theme.RECIPE_BAR_EMPTY)
        self._yield_lbl.setStyleSheet(_theme.RECIPE_BAR_YIELD)
        self.save_btn.setStyleSheet(_theme.RECIPE_BAR_SAVE_BTN)
        self.clear_btn.setStyleSheet(_theme.RECIPE_BAR_CLEAR_BTN)


# ---------------------------------------------------------------------------
# Matching Content — a Discover-style horizontal shelf
# ---------------------------------------------------------------------------

class _MatchingShelf(QWidget):
    """Horizontal scroll shelf of clickable result cards + a "Show all →" button.

    The Discover-style preview of what the current recipe matches (renamed from
    the old "Now Plating" — the cooking metaphor is dropped everywhere except the
    word "Recipe").  Reuses the Discover ``_ContentCard`` surface + ``card_metrics``
    so a match is browsable and actionable, and lazy-loads posters for cards in
    the current horizontal viewport (same pattern as ``discover_shelf._Shelf``):

    - single-click  → ``cardClicked(channel_id)``       (select → details pane)
    - double-click  → ``cardDoubleClicked(channel_id)``  (play, host-delegated)
    - "Show all →"  → ``showAllRequested()``             (full-results takeover)
    """

    cardClicked       = pyqtSignal(str)             # channel_id
    cardDoubleClicked = pyqtSignal(str)             # channel_id
    cardMiddleClicked = pyqtSignal(str)             # channel_id — configured middle-click play
    cardContextMenu   = pyqtSignal(str, int, int)   # channel_id, gx, gy
    showAllRequested  = pyqtSignal()                # "Show all →" → full-results browse page

    def __init__(self, image_cache: "ImageCache", config: "Config",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image_cache = image_cache
        self._config = config
        self._card_widgets: list = []        # list[_ContentCard]
        self._scroll: QScrollArea | None = None
        self._inner: QWidget | None = None
        self._inner_layout: QHBoxLayout | None = None
        self._total_count: int = 0
        self._build_ui()

    # ── public ────────────────────────────────────────────────────────────

    def load_results(self, cards: list, total_count: int) -> None:
        """Populate the shelf with real content cards.

        Args:
            cards:       ``ContentCard`` value objects from
                         ``TagRepository.sample_channels_by_tag_facets``.
            total_count: Total number of matching titles (for the header + the
                         "Show all" enablement).
        """
        from metatv.gui.discover_card import _ContentCard, card_metrics

        self._total_count = total_count
        self._sub.setText(f"preview · {total_count:,} total")
        self._show_all_btn.setVisible(total_count > 0)

        # Tear down previous cards.
        for w in self._card_widgets:
            self._inner_layout.removeWidget(w)
            w.deleteLater()
        self._card_widgets = []
        # Drop the trailing stretch / placeholder so we can rebuild cleanly.
        while self._inner_layout.count():
            item = self._inner_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        if not cards:
            placeholder = QLabel("No titles match this recipe yet")
            placeholder.setStyleSheet(_theme.RECIPE_EMPTY_HINT)
            self._inner_layout.addWidget(placeholder)
            placeholder.show()
            self._inner_layout.addStretch()
            return

        for card in cards:
            w = _ContentCard(card, self._image_cache, self._config, self._inner)
            w.clicked.connect(self.cardClicked)
            w.doubleClicked.connect(self.cardDoubleClicked)
            w.middleClicked.connect(self.cardMiddleClicked)
            w.contextMenuRequested.connect(self.cardContextMenu)
            self._inner_layout.addWidget(w)
            w.show()
            self._card_widgets.append(w)
        self._inner_layout.addStretch()

        # Keep the scroll-area height in sync with the (zoomed) card height.
        m = card_metrics(self._config.discover_zoom)
        if self._scroll is not None:
            self._scroll.setFixedHeight(m.card_h + 18)
        QTimer.singleShot(120, self._load_visible)

    # ── private ───────────────────────────────────────────────────────────

    def _load_visible(self) -> None:
        """Request poster images for cards in the current horizontal viewport."""
        if self._scroll is None:
            return
        vp_w = self._scroll.viewport().width()
        if vp_w == 0:
            QTimer.singleShot(80, self._load_visible)
            return
        scroll_x = self._scroll.horizontalScrollBar().value()
        for card in self._card_widgets:
            left = card.x()
            if left + card.width() >= scroll_x and left <= scroll_x + vp_w:
                card.request_image()

    def _build_ui(self) -> None:
        from metatv.gui.discover_card import card_metrics

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 6, 0, 8)
        outer.setSpacing(6)

        # Header: "MATCHING CONTENT" + "preview · N total" + "Show all →".
        hdr_row = QHBoxLayout()
        hdr_row.setContentsMargins(20, 0, 20, 0)
        hdr_row.setSpacing(10)

        self._hdr_lbl = QLabel("MATCHING CONTENT")
        self._hdr_lbl.setStyleSheet(_theme.RECIPE_MATCH_HDR)
        hdr_row.addWidget(self._hdr_lbl)

        self._sub = QLabel("preview · 0 total")
        self._sub.setStyleSheet(_theme.RECIPE_MATCH_SUB)
        hdr_row.addWidget(self._sub)
        hdr_row.addStretch()

        self._show_all_btn = QPushButton(f"Show all {_icons.see_all_arrow_icon}")
        self._show_all_btn.setFlat(True)
        self._show_all_btn.setStyleSheet(_theme.RECIPE_SHOW_ALL_BTN)
        self._show_all_btn.setToolTip("Browse all matching titles in the full grid")
        self._show_all_btn.setVisible(False)
        self._show_all_btn.clicked.connect(self.showAllRequested)
        hdr_row.addWidget(self._show_all_btn)
        outer.addLayout(hdr_row)

        # Horizontal scroll row of cards.
        m = card_metrics(self._config.discover_zoom)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(m.card_h + 18)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; } QScrollBar:horizontal { height: 10px; }")
        self._scroll = scroll

        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        inner_hl = QHBoxLayout(inner)
        inner_hl.setContentsMargins(20, 0, 20, 0)
        inner_hl.setSpacing(8)
        inner_hl.addStretch()
        self._inner = inner
        self._inner_layout = inner_hl

        scroll.setWidget(inner)
        scroll.horizontalScrollBar().valueChanged.connect(self._load_visible)
        outer.addWidget(scroll)

    def refresh_theme(self) -> None:
        """Re-apply the active palette to this shelf's own persistent chrome —
        the "MATCHING CONTENT" header, the "preview · N total" sub-label, and
        the "Show all" button — all styled once at construction. Result cards
        are rebuilt fresh from current tokens on every ``load_results()``
        call, so they need no sweep entry here.
        """
        self._hdr_lbl.setStyleSheet(_theme.RECIPE_MATCH_HDR)
        self._sub.setStyleSheet(_theme.RECIPE_MATCH_SUB)
        self._show_all_btn.setStyleSheet(_theme.RECIPE_SHOW_ALL_BTN)
