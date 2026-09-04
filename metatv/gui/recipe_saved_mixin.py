"""_RecipeSavedMixin — the Recipe view's Saved-recipes round-trip.

One cohesive concern mixed into :class:`~metatv.gui.recipe_view.RecipeView`:
persisting the current recipe to the ``saved_recipes`` Config field, rendering the
Saved tab from it, loading a saved recipe back into the builder, renaming, and
deleting — plus the per-card live match count off the ``_run_query`` seam.

A saved recipe is the plain, JSON/YAML-friendly shape stored in Config::

    {"name": str,
     "includes": {facet_type: [values]},
     "excludes": {facet_type: [values]},
     "show_in_discover": bool}   # #587 — Discover-shelf master switch, default True

Also owns the ``recipe:<name>`` Discover-shelf identity round-trip (#587): a
new save seeds the shelf into Discover's pinned zone, a rename migrates
whichever zone list held the old key, and a delete drops it — all through
the single :meth:`_sync_recipe_shelf_key` chokepoint, and every mutation
emits :attr:`RecipeView.savedRecipesChanged` so the host refreshes Discover.

The runtime recipe state uses ``set`` values; this mixin is the single boundary
that converts between the two forms, so no other code re-derives it.

DEFERRED (spec-note only — a later slice): the full custom-categories layer
(pinned / excluded specific titles + in-category 👍/👎 voting).  This slice ships
only the basic save → persist → list → reload → delete round-trip.
"""

from __future__ import annotations

from loguru import logger

from metatv.gui.recipe_widgets import _generate_recipe_name
from metatv.gui import deferred_config_save as _cfgsave


class _RecipeSavedMixin:
    """Saved-recipes persistence + Saved-tab wiring (see module docstring)."""

    # ── Config <-> runtime conversion ─────────────────────────────────────

    @staticmethod
    def _recipe_to_config(includes: dict, excludes: dict, name: str) -> dict:
        """Freeze the runtime recipe (set values) into the stored dict shape."""
        return {
            "name": name,
            "includes": {f: sorted(v) for f, v in includes.items() if v},
            "excludes": {f: sorted(v) for f, v in excludes.items() if v},
            "show_in_discover": True,
        }

    @staticmethod
    def _config_to_recipe(entry: dict) -> tuple[dict, dict]:
        """Thaw a stored recipe dict into runtime ``(includes, excludes)`` sets."""
        inc = {f: set(v) for f, v in (entry.get("includes") or {}).items() if v}
        exc = {f: set(v) for f, v in (entry.get("excludes") or {}).items() if v}
        return inc, exc

    def _saved_recipes(self) -> list:
        """Return the persisted saved-recipes list (a live reference into Config)."""
        recipes = getattr(self._config, "saved_recipes", None)
        if not isinstance(recipes, list):
            recipes = []
            self._config.saved_recipes = recipes
        return recipes

    def _persist_saved_recipes(self, recipes: list) -> None:
        """Write *recipes* to Config and save to disk (UI-state-persistence rule)."""
        self._config.saved_recipes = recipes
        try:
            _cfgsave.save_soon(self)
        except Exception as e:  # never let a config write crash the UI
            logger.warning("RecipeView: could not persist saved recipes: {}", e)

    def _sync_recipe_shelf_key(self, old_name: str | None, new_name: str | None) -> None:
        """Keep Discover's zone-list membership in sync with a recipe's identity.

        The shelf key is ``recipe:<name>`` (discover_workers._RECIPE_PREFIX), so
        save/rename/delete all change or remove that key — this is the single
        chokepoint all three route through instead of three copies of the same
        list-surgery:

        - Save (``old_name=None``): the locked design defaults a NEW recipe
          shelf into the PINNED zone, user-demotable afterwards like any other
          shelf — seeding the existing ``discover_pinned_shelves`` list is the
          whole mechanism; no special-casing of zone determination itself.
        - Rename (both set): migrates whichever zone list currently holds the
          old key to the new one, in place, so a rename never silently drops a
          pin/hide the user set.
        - Delete (``new_name=None``): removes the key from every zone list so
          no orphaned entry lingers forever.
        """
        from metatv.gui.discover_workers import _RECIPE_PREFIX

        old_key = f"{_RECIPE_PREFIX}{old_name}" if old_name else None
        new_key = f"{_RECIPE_PREFIX}{new_name}" if new_name else None
        if old_key == new_key:
            return

        if old_key is None:
            pinned = list(getattr(self._config, "discover_pinned_shelves", []))
            if new_key not in pinned:
                pinned.append(new_key)
                self._config.discover_pinned_shelves = pinned
        else:
            for attr in ("discover_pinned_shelves", "discover_expanded_shelves",
                         "discover_hidden_shelves"):
                lst = list(getattr(self._config, attr, []))
                if old_key in lst:
                    idx = lst.index(old_key)
                    if new_key is not None:
                        lst[idx] = new_key
                    else:
                        lst.pop(idx)
                    setattr(self._config, attr, lst)
        try:
            _cfgsave.save_soon(self)
        except Exception as e:  # never let a config write crash the UI
            logger.warning("RecipeView: could not persist recipe shelf zone: {}", e)

    def load_saved_recipe_by_name(self, name: str) -> None:
        """Load the saved recipe called *name* into the builder.

        Public entry point for a Discover recipe shelf's ✎ click — same effect
        as clicking the card on the Saved tab, looked up by name (the shelf
        key's identity) instead of list index. A no-op if the recipe was
        deleted/renamed since the shelf was built (the click is now stale).
        """
        for index, entry in enumerate(self._saved_recipes()):
            if isinstance(entry, dict) and entry.get("name") == name:
                self._on_saved_load(index)
                return

    # ── Save / render / reload / delete / rename ──────────────────────────

    def _on_save_recipe(self) -> None:
        """Save the current recipe under an auto-generated (editable) name."""
        if not (self._recipe_includes or self._recipe_excludes):
            return
        name = _generate_recipe_name(self._recipe_includes, self._recipe_excludes)
        entry = self._recipe_to_config(self._recipe_includes, self._recipe_excludes, name)
        recipes = list(self._saved_recipes())
        recipes.append(entry)
        self._persist_saved_recipes(recipes)
        logger.debug("RecipeView: saved recipe {!r} ({} total)", name, len(recipes))
        self._sync_recipe_shelf_key(None, name)
        self.savedRecipesChanged.emit()
        # Jump to the Saved tab so the user sees the new card (and can rename it).
        self._tab_bar.set_index(1)
        self._show_tab(1)
        self._load_saved_recipes()

    def _load_saved_recipes(self) -> None:
        """Render the Saved tab from Config and (re)issue the per-card counts."""
        recipes = self._saved_recipes()
        self._saved_panel.set_recipes(recipes)
        self._saved_gen += 1
        self._load_saved_counts(recipes, self._saved_gen)

    def _load_saved_counts(self, recipes: list, gen: int) -> None:
        """Fire one count query per saved recipe; update its card when it lands.

        A ``gen`` generation guard (bumped on every :meth:`_load_saved_recipes`)
        drops results from a superseded render — token_ref is unusable here because
        the N queries would otherwise cancel each other (they share one counter).
        """
        excl_prefixes, excl_categories, excl_content_types, excl_keywords = self._global_exclusion_sets()
        for index, entry in enumerate(recipes):
            inc, exc = self._config_to_recipe(entry)
            includes = {k: set(v) for k, v in inc.items() if v}
            excludes = {k: set(v) for k, v in exc.items() if v}

            def _query(repos, includes=includes, excludes=excludes):
                return repos.tags.count_channels_by_tag_facets(
                    includes=includes,
                    excludes=excludes,
                    excluded_provider_ids=repos.providers.get_hidden_provider_ids(),
                    excluded_prefixes=excl_prefixes,
                    excluded_categories=excl_categories,
                    excluded_tag_content_types=excl_content_types,
                    excluded_keywords=excl_keywords,
                    collapse_variants=True,
                )

            self._run_query(
                _query,
                lambda total, index=index, gen=gen: self._on_saved_count_loaded(index, total, gen),
                on_error=lambda exc, index=index, gen=gen: self._on_saved_count_error(index, gen),
            )

    def _on_saved_count_loaded(self, index: int, total: int, gen: int) -> None:
        if not self._active or gen != self._saved_gen:
            return
        card = self._saved_panel.card(index)
        if card is not None:
            card.set_count(int(total))

    def _on_saved_count_error(self, index: int, gen: int) -> None:
        if not self._active or gen != self._saved_gen:
            return
        card = self._saved_panel.card(index)
        if card is not None:
            card.set_count(0)

    def _on_saved_load(self, index: int) -> None:
        """Load the saved recipe at *index* back into the builder."""
        recipes = self._saved_recipes()
        if not (0 <= index < len(recipes)):
            return
        inc, exc = self._config_to_recipe(recipes[index])
        self._recipe_includes = inc
        self._recipe_excludes = exc
        # Return to the builder overview: drop any drill-in / search.
        self._selected_facet = None
        self._search_query = ""
        self._search_results = []
        self._search_box.clear()
        self._stage_hdr.setText("Browse by facet")
        self._tab_bar.set_index(0)
        self._show_tab(0)
        self._stack.setCurrentIndex(0)
        # Re-render the grid marks + recipe bar, then fetch the matches.
        self._render_clusters()
        self._recipe_bar.update_recipe(self._recipe_includes, self._recipe_excludes, None)
        self._load_results()

    def _on_saved_delete(self, index: int) -> None:
        """Delete the saved recipe at *index* and re-render the Saved tab."""
        recipes = list(self._saved_recipes())
        if not (0 <= index < len(recipes)):
            return
        removed = recipes.pop(index)
        self._persist_saved_recipes(recipes)
        logger.debug("RecipeView: deleted saved recipe {!r}", removed.get("name"))
        self._sync_recipe_shelf_key(removed.get("name"), None)
        self.savedRecipesChanged.emit()
        self._load_saved_recipes()

    def _on_saved_rename(self, index: int, name: str) -> None:
        """Rename the saved recipe at *index* (persist; no re-render churn)."""
        recipes = list(self._saved_recipes())
        if not (0 <= index < len(recipes)):
            return
        old_name = recipes[index].get("name")
        new_name = name or "Untitled recipe"
        recipes[index] = {**recipes[index], "name": new_name}
        self._persist_saved_recipes(recipes)
        self._sync_recipe_shelf_key(old_name, new_name)
        self.savedRecipesChanged.emit()

    def _on_saved_show_toggled(self, index: int, checked: bool) -> None:
        """Saved-tab "Show in Discover" toggle — the per-recipe master switch (#587).

        Purely a Config write; the shelf's pin/hide zone membership is left
        untouched (the layers compose per the locked design) — Discover's own
        reload picks up the new gate on the next refresh.
        """
        recipes = list(self._saved_recipes())
        if not (0 <= index < len(recipes)):
            return
        recipes[index] = {**recipes[index], "show_in_discover": checked}
        self._persist_saved_recipes(recipes)
        self.savedRecipesChanged.emit()
