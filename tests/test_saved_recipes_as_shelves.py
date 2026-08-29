"""A saved recipe is a shelf everywhere, or it is not really saved.

Owner: "saved recipes should be available as Discover Shelves".

A recipe already IS a shelf in everything but where it appears — a named facet
query the user built and kept. The work is not inventing a query; it is making
sure the shelf and the Recipe view answer with the SAME titles, because a
recipe that shows different content depending on which screen you open it from
is worse than not having it on the second screen at all.
"""

import pytest

from metatv.core.config import Config
from metatv.core.database import ChannelDB, Database
from metatv.gui.discover_workers import _RECIPE_PREFIX, fetch_cards_for_key

NO_KWARGS = {"sk": {}, "fk": {}, "af": {}, "ek": {}}


@pytest.fixture
def db(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'shelves.db'}")
    database.create_tables()
    return database


def _config(recipes) -> Config:
    cfg = Config()
    cfg.saved_recipes = recipes
    return cfg


# ── the shelf resolves ──────────────────────────────────────────────────────

def test_a_saved_recipe_is_addressable_as_a_shelf_key(db) -> None:
    """The dispatcher must recognise the namespace at all."""
    cfg = _config([{"name": "Noir", "includes": {"genre": ["Drama"]}, "excludes": {}}])
    with db.session_scope() as s:
        # No channels in this fixture DB, so zero cards — the assertion is that
        # the key ROUTES rather than falling through to the unknown-key branch.
        assert fetch_cards_for_key(s, cfg, f"{_RECIPE_PREFIX}Noir", 8, **NO_KWARGS) == []


def test_a_recipe_that_no_longer_exists_yields_nothing(db) -> None:
    """A shelf key can outlive its recipe — a stale pin, a stale zone entry.

    It must return empty rather than raise, or deleting a recipe would break
    the whole Discover load.
    """
    cfg = _config([])
    with db.session_scope() as s:
        assert fetch_cards_for_key(s, cfg, f"{_RECIPE_PREFIX}Gone", 8, **NO_KWARGS) == []


def test_a_recipe_with_no_ingredients_yields_nothing(db) -> None:
    """An empty recipe matches EVERYTHING as a facet query.

    Rendering the entire library under a shelf the user has not actually
    specified is not a useful shelf; it is the catalogue with a name on it.
    """
    cfg = _config([{"name": "Blank", "includes": {}, "excludes": {}}])
    with db.session_scope() as s:
        assert fetch_cards_for_key(s, cfg, f"{_RECIPE_PREFIX}Blank", 8, **NO_KWARGS) == []


@pytest.mark.parametrize("junk", [None, "string", 42, {"no_name": 1}, {"name": "  "}])
def test_a_malformed_saved_recipe_does_not_break_the_load(db, junk) -> None:
    """saved_recipes is user-writable config; one bad entry must not take
    Discover down with it."""
    cfg = _config([junk])
    with db.session_scope() as s:
        assert fetch_cards_for_key(s, cfg, f"{_RECIPE_PREFIX}x", 8, **NO_KWARGS) == []


# ── it must obey the same exclusions the recipe view obeys ──────────────────
#
# These were originally written with ``inspect.getsource`` + a substring check,
# and a mutation that deleted the exclusion resolution ENTIRELY still passed —
# because the function's own docstring contains the words it was grepping for.
# That is the exact defect this project's audit kept finding, reproduced here
# by hand. They assert behaviour now.


def _seed(db, rows) -> None:
    """``rows`` = ``(channel_id, provider_id, genre)``, tagged for the sampler."""
    from metatv.core.database import ContentTagDB, ProviderDB, TagDB

    with db.session_scope() as s:
        # A ProviderDB row per provider_id, or get_hidden_provider_ids() reads
        # them as ORPHANED and excludes every card — which is the gate working
        # correctly against unrealistic fixture data. The first draft of this
        # file omitted them and every assertion saw an empty shelf.
        for pid in {p for _cid, p, _g in rows}:
            s.add(ProviderDB(id=pid, name=pid, type="xtream", url="u", is_active=True))
        s.flush()
        tag_ids: dict[str, int] = {}
        for cid, pid, genre in rows:
            s.add(ChannelDB(id=cid, source_id=cid, provider_id=pid,
                            name=f"Title {cid}", detected_title=f"Title {cid}",
                            media_type="movie"))
            if genre not in tag_ids:
                tag = TagDB(type="genre", value=genre)
                s.add(tag)
                s.flush()
                tag_ids[genre] = tag.id
            s.add(ContentTagDB(channel_id=cid, tag_id=tag_ids[genre],
                               source="generated", confidence=1.0))


def _titles(cards) -> set[str]:
    return {c.title for c in cards}


def test_an_empty_recipe_does_not_render_the_whole_library(db) -> None:
    """An empty facet query matches EVERYTHING.

    Seeded with real rows so the guard is actually exercised — the first
    version of this test used an empty database, where removing the guard
    changed nothing and the mutation passed.
    """
    _seed(db, [("a", "p1", "Drama"), ("b", "p1", "Comedy")])
    cfg = _config([{"name": "Blank", "includes": {}, "excludes": {}}])

    with db.session_scope() as s:
        assert fetch_cards_for_key(s, cfg, f"{_RECIPE_PREFIX}Blank", 8, **NO_KWARGS) == []


def test_the_shelf_returns_what_the_recipe_asks_for(db) -> None:
    """Baseline, so the exclusion tests below cannot pass by returning nothing."""
    _seed(db, [("a", "p1", "Drama"), ("b", "p1", "Comedy")])
    cfg = _config([{"name": "D", "includes": {"genre": ["Drama"]}, "excludes": {}}])

    with db.session_scope() as s:
        cards = fetch_cards_for_key(s, cfg, f"{_RECIPE_PREFIX}D", 8, **NO_KWARGS)
    assert _titles(cards) == {"Title a"}


def test_a_hidden_source_never_reaches_a_recipe_shelf(db) -> None:
    """Hidden-provider content is an absolute gate (CLAUDE.md).

    A shelf built from the user's OWN recipe is where a leak would feel most
    like a betrayal — they asked for this list.
    """
    from metatv.core.database import ProviderDB

    _seed(db, [("a", "live", "Drama"), ("b", "off", "Drama")])
    with db.session_scope() as s:
        s.query(ProviderDB).filter_by(id="off").update({"is_active": False})

    cfg = _config([{"name": "D", "includes": {"genre": ["Drama"]}, "excludes": {}}])
    with db.session_scope() as s:
        cards = fetch_cards_for_key(s, cfg, f"{_RECIPE_PREFIX}D", 8, **NO_KWARGS)

    assert _titles(cards) == {"Title a"}, (
        "a disabled source's content appeared on a recipe shelf"
    )


def test_a_global_keyword_exclusion_applies_to_a_recipe_shelf(db) -> None:
    """The user's Global Exclusions outrank their own recipe.

    Built from ``filter_utils.global_exclusion_sets`` rather than the shelf
    kwargs, which have no separate category axis and would silently drop one
    of the axes the Recipe view applies.
    """
    _seed(db, [("a", "p1", "Drama"), ("b", "p1", "Drama")])
    cfg = _config([{"name": "D", "includes": {"genre": ["Drama"]}, "excludes": {}}])
    cfg.global_excluded_keywords = ["Title b"]

    with db.session_scope() as s:
        cards = fetch_cards_for_key(s, cfg, f"{_RECIPE_PREFIX}D", 8, **NO_KWARGS)

    assert "Title b" not in _titles(cards), (
        f"a globally excluded keyword survived onto a recipe shelf: {_titles(cards)}"
    )


def test_pausing_global_exclusions_empties_every_axis() -> None:
    """Paused means paused — the shelf must not keep applying a stale set."""
    from metatv.core.filter_utils import global_exclusion_sets

    cfg = Config()
    cfg.global_filter_paused = True
    assert all(not axis for axis in global_exclusion_sets(cfg))


def test_the_recipe_view_and_the_shelf_share_one_composer() -> None:
    """Two copies of the composition is how one recipe comes to show two
    different things on two screens.

    Structural because it is a statement about WHERE the code lives, which has
    no runtime signature — but it is the only structural claim left in this
    file, and it checks a call, not a docstring.
    """
    import ast
    import inspect

    from metatv.gui.recipe_view import RecipeView

    tree = ast.parse(inspect.getsource(RecipeView._global_exclusion_sets).strip())
    called = {
        getattr(n.func, "id", None) or getattr(n.func, "attr", None)
        for n in ast.walk(tree) if isinstance(n, ast.Call)
    }
    assert "global_exclusion_sets" in called, (
        "RecipeView re-derives the exclusion sets instead of calling the shared one"
    )
