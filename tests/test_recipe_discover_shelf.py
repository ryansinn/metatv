"""Behavioral tests for saved recipes as live Discover shelves (#587).

Owner-locked design: a saved recipe with ``show_in_discover`` (default True)
gets its own ``recipe:<name>`` Discover shelf — ✦-marked, cards from its own
facet query via ``TagRepository.sample_channels_by_tag_facets`` (the SAME call
the Recipe view's own results shelf uses, so the two screens never drift).
Toggling the master switch off drops the shelf entirely, even collapsed; an
empty recipe never emits one either. Recipe shelves also get an ✎ edit
affordance the header never shows anyone else, and a newly-saved recipe seeds
its shelf into Discover's pinned zone.

Covers, each proven against real behavior (not shape):
1. show_in_discover=True (default) → emits a recipe:<name> shelf carrying the
   ✦ marker and cards from the recipe's own facet query — real Database on
   tmp_path with a few tagged channels. This is the emission test; it fails
   pre-fix (the old title had no ✦ marker at all).
2. show_in_discover=False → emits no shelf, even in the collapsed zone.
3. An empty recipe (zero matches) → no shelf, same gate every other
   card-bearing shelf type already uses.
4. The ✎ edit button exists on a recipe shelf and NOT on a genre shelf
   (rendered-state assertion: the widget instance and its visible state).
5. Saving a new recipe seeds its shelf key into the pinned zone (the locked
   default), and deleting it removes the key again.
6. The Saved-tab toggle persists show_in_discover and fires
   savedRecipesChanged so the host refreshes Discover.
"""

from __future__ import annotations

import uuid

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def tagged_db(tmp_path):
    """File-backed DB (not :memory:) with a provider + 5 Drama-tagged channels."""
    from metatv.core.database import ChannelDB, Database, ProviderDB
    from metatv.core.repositories import RepositoryFactory

    db = Database(f"sqlite:///{tmp_path / 'recipe_shelf_test.db'}")
    db.create_tables()

    session = db.get_session()
    try:
        session.add(ProviderDB(
            id="p1", name="Test Provider", type="xtream",
            url="http://test.example.com", is_active=True,
        ))
        channel_ids = []
        for i in range(5):
            cid = str(uuid.uuid4())
            session.add(ChannelDB(
                id=cid, source_id=str(i), provider_id="p1",
                name=f"Drama Title {i}", media_type="movie",
            ))
            channel_ids.append(cid)
        session.commit()

        repos = RepositoryFactory(session)
        for cid in channel_ids:
            repos.tags.set_content_tags(cid, [("genre", "Drama", "test_feeder")])
        session.commit()
    finally:
        session.close()

    yield db
    db.close()


def _snap(pinned=(), expanded=(), collapsed=(), hidden=(), first_launch=False):
    from metatv.gui.discover_workers import _ZoneSnapshot
    return _ZoneSnapshot(
        pinned=frozenset(pinned), expanded=frozenset(expanded),
        collapsed=frozenset(collapsed), hidden=frozenset(hidden),
        default_expanded=frozenset(), first_launch=first_launch,
    )


def _config_with_recipe(**overrides) -> "object":
    from metatv.core.config import Config
    cfg = Config()
    recipe = {
        "name": "Cold Drama",
        "includes": {"genre": ["Drama"]},
        "excludes": {},
        "show_in_discover": True,
    }
    recipe.update(overrides)
    cfg.saved_recipes = [recipe]
    return cfg


# ---------------------------------------------------------------------------
# 1 & 2 & 3. _LoaderWorker emission behavior
# ---------------------------------------------------------------------------

class TestRecipeShelfEmission:

    def test_recipe_shelf_emits_marked_cards_from_its_own_facet_query(self, tagged_db, qapp):
        """show_in_discover=True → a recipe:<name> shelf, ✦-marked, cards from
        the SAME facet query the Recipe view's results shelf uses.

        This is the emission test: pinning forces the eager fetch, so the
        cards must come back non-empty and matching what the recipe's own
        includes describe. Fails pre-fix on the title's ✦ marker — the old
        code emitted "Recipe: Cold Drama" with no non-color cue at all.
        """
        from metatv.gui.discover_workers import _LoaderWorker
        from metatv.gui import icons

        cfg = _config_with_recipe()
        snapshot = _snap(
            pinned={"recipe:Cold Drama"},
            collapsed={"recently_added", "top_movies", "top_series"},
        )
        w = _LoaderWorker(tagged_db, cfg, zone_snapshot=snapshot)
        shelves: list = []
        w.shelfReady.connect(lambda d: shelves.append(d))
        w.run()

        recipe_shelves = [s for s in shelves if s.shelf_key == "recipe:Cold Drama"]
        assert recipe_shelves, "recipe shelf must be emitted when show_in_discover=True"
        s = recipe_shelves[0]
        assert s.header_only is False
        assert len(s.cards) == 5, "must carry cards matching the recipe's facet query"
        assert {c.title for c in s.cards} == {f"Drama Title {i}" for i in range(5)}
        assert s.title.startswith(icons.recipe_icon), (
            "shelf title must carry the ✦ non-color recipe marker"
        )

    def test_show_in_discover_false_emits_no_shelf_at_all(self, tagged_db, qapp):
        """The master switch OFF suppresses the shelf entirely — not even a
        header-only collapsed strip."""
        from metatv.gui.discover_workers import _LoaderWorker

        cfg = _config_with_recipe(show_in_discover=False)
        # Pin it anyway — if the master switch worked via zone plumbing alone
        # this would still emit a header, so pinning proves the gate is a
        # hard skip, not a side-effect of zone routing.
        snapshot = _snap(
            pinned={"recipe:Cold Drama"},
            collapsed={"recently_added", "top_movies", "top_series"},
        )
        w = _LoaderWorker(tagged_db, cfg, zone_snapshot=snapshot)
        shelves: list = []
        w.shelfReady.connect(lambda d: shelves.append(d))
        w.run()

        keys = [s.shelf_key for s in shelves]
        assert "recipe:Cold Drama" not in keys, (
            "show_in_discover=False must suppress the shelf entirely"
        )

    def test_empty_recipe_emits_no_shelf(self, tagged_db, qapp):
        """A recipe whose facet query matches nothing never emits a shelf —
        same hide-when-empty gate every card-bearing shelf type already uses."""
        from metatv.gui.discover_workers import _LoaderWorker

        cfg = _config_with_recipe(includes={"genre": ["Nonexistent Genre"]})
        snapshot = _snap(
            pinned={"recipe:Cold Drama"},
            collapsed={"recently_added", "top_movies", "top_series"},
        )
        w = _LoaderWorker(tagged_db, cfg, zone_snapshot=snapshot)
        shelves: list = []
        w.shelfReady.connect(lambda d: shelves.append(d))
        w.run()

        keys = [s.shelf_key for s in shelves]
        assert "recipe:Cold Drama" not in keys, "an empty recipe must not emit a shelf"


# ---------------------------------------------------------------------------
# 4. ✎ edit icon — recipe shelves only (rendered-state assertion)
# ---------------------------------------------------------------------------

class TestEditIconOnlyOnRecipeShelves:

    def test_recipe_shelf_has_visible_edit_button(self, qapp, tmp_path):
        from metatv.core.config import Config
        from metatv.gui.discover_shelf import _Shelf
        from metatv.gui import icons

        cfg = Config(config_dir=tmp_path / "config", data_dir=tmp_path / "data",
                     cache_dir=tmp_path / "cache")
        shelf = _Shelf("✦ Cold Drama", "recipe:Cold Drama", [],
                        image_cache=None, config=cfg, collapsed=False)

        assert shelf._edit_btn is not None, "a recipe shelf must build the ✎ button"
        assert shelf._edit_btn.text() == icons.recipe_edit_icon
        # isVisibleTo(shelf), not isVisible(): the widget is never shown as a
        # real top-level window in this test, so isVisible() would be False
        # regardless of the internal setVisible() state we're actually
        # asserting on.
        assert shelf._edit_btn.isVisibleTo(shelf), (
            "the ✎ button must be visible on an expanded shelf"
        )

        # Clicking it must emit the shelf's own key so the host can route it.
        received: list[str] = []
        shelf.editRequested.connect(received.append)
        shelf._edit_btn.click()
        assert received == ["recipe:Cold Drama"]

    def test_genre_shelf_has_no_edit_button(self, qapp, tmp_path):
        from metatv.core.config import Config
        from metatv.gui.discover_shelf import _Shelf

        cfg = Config(config_dir=tmp_path / "config", data_dir=tmp_path / "data",
                     cache_dir=tmp_path / "cache")
        shelf = _Shelf("Action", "genre:Action", [],
                        image_cache=None, config=cfg, collapsed=False)

        assert shelf._edit_btn is None, "a non-recipe shelf must never build the ✎ button"


# ---------------------------------------------------------------------------
# 5. New recipe defaults into the pinned zone; delete cleans it up
# ---------------------------------------------------------------------------

class TestPinDefaultAndCleanup:

    def _make_view(self, qapp, config):
        from metatv.gui.recipe_view import RecipeView
        from PyQt6.QtCore import QObject, pyqtSignal

        class _FakeSeam:
            def _run_query(self, query_fn, on_result, *, token_ref=None, on_error=None):
                if token_ref is not None:
                    token_ref[0] += 1

        class _FakeImageCache(QObject):
            image_loaded = pyqtSignal(str, object)
            image_failed = pyqtSignal(str, str)

            def get_image_async(self, url):
                pass

        seam = _FakeSeam()
        view = RecipeView(
            db=object(), config=config, run_query_fn=seam._run_query,
            image_cache=_FakeImageCache(), parent=None,
        )
        view._active = True
        return view

    def test_save_pins_the_new_recipe_shelf(self, qapp, tmp_path):
        from metatv.core.config import Config
        config = Config(config_dir=tmp_path)
        view = self._make_view(qapp, config)

        view._recipe_includes = {"genre": {"Drama"}}
        view._recipe_excludes = {}
        view._on_save_recipe()

        name = config.saved_recipes[0]["name"]
        assert f"recipe:{name}" in config.discover_pinned_shelves

    def test_save_fires_saved_recipes_changed(self, qapp, tmp_path):
        from metatv.core.config import Config
        config = Config(config_dir=tmp_path)
        view = self._make_view(qapp, config)

        fired: list = []
        view.savedRecipesChanged.connect(lambda: fired.append(True))
        view._recipe_includes = {"genre": {"Drama"}}
        view._on_save_recipe()

        assert fired, "saving a recipe must notify the host to refresh Discover"

    def test_delete_removes_the_pinned_shelf_key(self, qapp, tmp_path):
        from metatv.core.config import Config
        config = Config(config_dir=tmp_path)
        view = self._make_view(qapp, config)

        view._recipe_includes = {"genre": {"Drama"}}
        view._on_save_recipe()
        name = config.saved_recipes[0]["name"]
        assert f"recipe:{name}" in config.discover_pinned_shelves

        view._on_saved_delete(0)
        assert f"recipe:{name}" not in config.discover_pinned_shelves


# ---------------------------------------------------------------------------
# 6. Saved-tab "Show in Discover" toggle
# ---------------------------------------------------------------------------

class TestShowInDiscoverToggle:

    def test_toggle_persists_and_notifies_host(self, qapp, tmp_path):
        from metatv.core.config import Config
        from metatv.gui.recipe_view import RecipeView
        from PyQt6.QtCore import QObject, pyqtSignal

        class _FakeSeam:
            def _run_query(self, query_fn, on_result, *, token_ref=None, on_error=None):
                if token_ref is not None:
                    token_ref[0] += 1

        class _FakeImageCache(QObject):
            image_loaded = pyqtSignal(str, object)
            image_failed = pyqtSignal(str, str)

            def get_image_async(self, url):
                pass

        config = Config(config_dir=tmp_path)
        config.saved_recipes = [
            {"name": "R", "includes": {"genre": ["Drama"]}, "excludes": {},
             "show_in_discover": True},
        ]
        seam = _FakeSeam()
        view = RecipeView(
            db=object(), config=config, run_query_fn=seam._run_query,
            image_cache=_FakeImageCache(), parent=None,
        )
        view._active = True
        view._load_saved_recipes()

        card = view._saved_panel.card(0)
        assert card._show_check.isChecked() is True

        fired: list = []
        view.savedRecipesChanged.connect(lambda: fired.append(True))
        card._show_check.setChecked(False)

        assert config.saved_recipes[0]["show_in_discover"] is False
        assert fired, "toggling off must notify the host to refresh Discover"
