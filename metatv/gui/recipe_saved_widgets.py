"""Recipe view — the Saved tab: a responsive grid of saved-recipe cards.

Each card shows an editable name, a live match count, and the recipe's ingredient
tags.  Clicking a card loads it back into the builder; the trash button deletes
it.  Leaf presentation only — the :class:`~metatv.gui.recipe_view.RecipeView`
host persists to Config and runs the per-card count query off the ``_run_query``
seam.  Split out of ``recipe_widgets.py`` to keep every recipe file under 1000
lines.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from metatv.gui import cursor_affordance
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.recipe_widgets import _facet_chip_style, _facet_color

# Minimum card width (px) used to compute the responsive column count.
_SAVED_CARD_MIN_W: int = 290
_SAVED_MAX_COLS: int = 4


class _SavedRecipeCard(QFrame):
    """One saved recipe: editable name · match count · ingredient tags · delete.

    Signals carry the card's index in the saved-recipes list so the host mutates
    the right entry.  Clicking the card body (not the name field or trash button)
    loads it back into the builder.
    """

    loadRequested   = pyqtSignal(int)        # index → reload into builder
    deleteRequested = pyqtSignal(int)        # index → remove
    renameRequested = pyqtSignal(int, str)   # (index, new_name)

    def __init__(self, index: int, recipe: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._index = index
        self.setObjectName("savedRecipeCard")
        _theme.style(self, "RECIPE_SAVED_CARD")
        cursor_affordance.set_clickable(self, True)
        self._build_ui(recipe)

    # ── public ────────────────────────────────────────────────────────────

    def set_count(self, count: int) -> None:
        """Update the live match-count line once the count query lands."""
        self._count_lbl.setText(f"{count:,} title{'' if count == 1 else 's'}")

    # ── private ───────────────────────────────────────────────────────────

    def _build_ui(self, recipe: dict) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(15, 13, 14, 13)
        outer.setSpacing(7)

        # Title row: editable name (left) + trash (right).
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)
        self._name_edit = QLineEdit(str(recipe.get("name") or "Untitled recipe"))
        _theme.style(self._name_edit, "RECIPE_SAVED_NAME_EDIT")
        self._name_edit.setToolTip("Rename this recipe")
        self._name_edit.setClearButtonEnabled(True)
        self._name_edit.editingFinished.connect(self._on_rename)
        title_row.addWidget(self._name_edit, stretch=1)

        del_btn = QPushButton(_icons.delete_icon)
        _theme.style(del_btn, "RECIPE_SAVED_ICON_BTN")
        del_btn.setToolTip("Delete this saved recipe")
        cursor_affordance.set_clickable(del_btn, True)
        del_btn.clicked.connect(lambda: self.deleteRequested.emit(self._index))
        title_row.addWidget(del_btn, alignment=Qt.AlignmentFlag.AlignTop)
        outer.addLayout(title_row)

        # Live match count.
        self._count_lbl = QLabel("counting…")
        _theme.style(self._count_lbl, "RECIPE_SAVED_COUNT")
        outer.addWidget(self._count_lbl)

        # Ingredient tags (facet-colored), includes then excludes.
        tags_row = QHBoxLayout()
        tags_row.setContentsMargins(0, 2, 0, 0)
        tags_row.setSpacing(5)
        includes = recipe.get("includes") or {}
        excludes = recipe.get("excludes") or {}
        added = 0
        for facet, values in includes.items():
            for v in values:
                tags_row.addWidget(self._tag(facet, str(v), excluded=False))
                added += 1
        for facet, values in excludes.items():
            for v in values:
                tags_row.addWidget(self._tag(facet, str(v), excluded=True))
                added += 1
        if not added:
            empty = QLabel("no ingredients")
            _theme.style(empty, "RECIPE_SAVED_COUNT")
            tags_row.addWidget(empty)
        tags_row.addStretch()
        outer.addLayout(tags_row)

    def _tag(self, facet: str, value: str, *, excluded: bool) -> QLabel:
        lbl = QLabel(f"{_icons.tag_exclude_icon} {value}" if excluded else value)
        lbl.setStyleSheet(_facet_chip_style(_facet_color(facet), excluded=excluded))
        return lbl

    def _on_rename(self) -> None:
        self.renameRequested.emit(self._index, self._name_edit.text().strip())

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        # A click on empty card area (not a child control) reloads the recipe.
        if event.button() == Qt.MouseButton.LeftButton:
            self.loadRequested.emit(self._index)
        super().mousePressEvent(event)


class _SavedRecipesPanel(QWidget):
    """The "Saved" tab body — a responsive grid of :class:`_SavedRecipeCard`.

    Re-exposes each card's ``loadRequested`` / ``deleteRequested`` /
    ``renameRequested`` up to the host, keyed by list index.
    """

    loadRequested   = pyqtSignal(int)
    deleteRequested = pyqtSignal(int)
    renameRequested = pyqtSignal(int, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cards: list[_SavedRecipeCard] = []
        self._build_ui()

    # ── public ────────────────────────────────────────────────────────────

    def set_recipes(self, recipes: list[dict]) -> None:
        """Rebuild the card grid from *recipes* (list of saved-recipe dicts)."""
        for c in self._cards:
            c.setParent(None)
            c.deleteLater()
        self._cards = []
        while self._grid.count():
            self._grid.takeAt(0)

        self._empty_lbl.setVisible(not recipes)
        for i, recipe in enumerate(recipes):
            card = _SavedRecipeCard(i, recipe)
            card.loadRequested.connect(self.loadRequested)
            card.deleteRequested.connect(self.deleteRequested)
            card.renameRequested.connect(self.renameRequested)
            self._cards.append(card)
        self._relayout()

    def card(self, index: int) -> "_SavedRecipeCard | None":
        """Return the card at *index* (for count updates), or None."""
        return self._cards[index] if 0 <= index < len(self._cards) else None

    def cards(self) -> list:
        """All rendered cards — for tests/introspection."""
        return list(self._cards)

    # ── private ───────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(4)

        self._title_lbl = QLabel("SAVED RECIPES")
        _theme.style(self._title_lbl, "RECIPE_BROWSE_HDR")
        outer.addWidget(self._title_lbl)

        self._sub_lbl = QLabel(
            "Your personal categories — each keeps filling with new matches as sources refresh."
        )
        _theme.style(self._sub_lbl, "RECIPE_SAVED_SUB")
        self._sub_lbl.setWordWrap(True)
        outer.addWidget(self._sub_lbl)

        self._empty_lbl = QLabel("No saved recipes yet — build a recipe and click ✦ Save.")
        _theme.style(self._empty_lbl, "RECIPE_EMPTY_HINT")
        outer.addWidget(self._empty_lbl)

        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 8, 0, 0)
        self._grid.setSpacing(14)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        outer.addWidget(self._grid_host)
        outer.addStretch()

    def _cols(self) -> int:
        w = self.width() or (self.parentWidget().width() if self.parentWidget() else 0) or 1000
        return max(1, min(_SAVED_MAX_COLS, w // _SAVED_CARD_MIN_W))

    def _relayout(self) -> None:
        while self._grid.count():
            self._grid.takeAt(0)
        cols = self._cols()
        for i, card in enumerate(self._cards):
            self._grid.addWidget(card, i // cols, i % cols)
            card.show()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._relayout()

    def refresh_theme(self) -> None:
        """Re-apply the active palette to this panel's own persistent chrome
        (title, subtitle, empty-state hint) — all styled once at construction.
        ``_SavedRecipeCard`` instances are rebuilt fresh from current tokens
        on every ``set_recipes()`` call, so they need no sweep entry here.
        Called from ``RecipeView.refresh_theme()``.
        """
        _theme.style(self._title_lbl, "RECIPE_BROWSE_HDR")
        _theme.style(self._sub_lbl, "RECIPE_SAVED_SUB")
        _theme.style(self._empty_lbl, "RECIPE_EMPTY_HINT")
