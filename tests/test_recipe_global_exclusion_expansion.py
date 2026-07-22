"""Regression: RecipeView Global-Exclusion scoping must expand category GROUPS.

The bug: ``RecipeView._global_exclusion_sets()`` hand-rolled the excluded-prefix
set as the raw config union::

    set(config.global_filter_excluded_categories) | set(config.global_filter_excluded_prefixes)

and never routed through ``filter_utils.get_active_category_filter`` — the single
canonical resolver that the main channel list uses
(``main_window_channels.py`` ``_query_channels_page``).  The Global Exclusions
dialog persists a *checked language group* by writing all of that group's leaf
prefix codes into ``global_filter_excluded_categories`` (``_GroupSection.checked_prefixes``
→ ``GlobalFilterDialog._save`` line ~1012).  ``get_active_category_filter`` is the
read-side chokepoint for that selection, so the recipe view must delegate to it
rather than re-derive the union locally.

The earlier recipe tests masked the bug by seeding a *single leaf code* directly
into the config lists, which produces the same set under either code path.  These
tests instead exercise the real path:

  1. Seed a ``Config`` exactly as the dialog leaves it after a group is checked
     (the group's leaf codes in ``global_filter_excluded_categories``).
  2. Assert ``_global_exclusion_sets()`` returns a prefix set CONTAINING a leaf
     code that belongs to that group.
  3. Drive the real ``TagRepository`` faceted queries with those sets against a
     file-backed DB and assert the channel carrying that leaf prefix is dropped.
  4. Assert ``global_filter_paused=True`` returns empty sets (channel reappears).
  5. Assert the helper delegates to ``filter_utils.get_active_category_filter`` /
     ``get_excluded_prefixes`` — the part that genuinely regressed (a raw-config
     union does not call the resolver).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from metatv.core.config import BASE_PREFIX_GROUPS, Config
from metatv.core.database import ChannelDB, Database
from metatv.core.repositories import RepositoryFactory
from metatv.gui.recipe_view import RecipeView


# The Arabic language group: a real dialog selection.  Its leaf codes are what
# get written into global_filter_excluded_categories when the group is checked.
_ARABIC_GROUP = "Arabic"
_ARABIC_LEAVES = BASE_PREFIX_GROUPS[_ARABIC_GROUP]
# A leaf code we will stamp onto a channel's detected_prefix.
_LEAF_PREFIX = "EG"  # Egypt — a member of the Arabic group
assert _LEAF_PREFIX in _ARABIC_LEAVES


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def file_db(tmp_path: Path):
    """File-backed SQLite Database (:memory: gives each connection a separate
    empty DB, which breaks session_scope)."""
    db_file = tmp_path / "test_recipe_exclusion.db"
    db = Database(f"sqlite:///{db_file}")
    db.create_tables()
    yield db
    db.close()


def _checked_group_config(tmp_path: Path, group_leaves: list[str]) -> Config:
    """Return a Config in the exact state the Global Exclusions dialog leaves
    after the user checks a whole language group.

    The dialog writes the group's leaf prefix codes into
    ``global_filter_excluded_categories`` (GlobalFilterDialog._save), so we
    reproduce that here — NOT a single hand-picked leaf, and NOT the group name.
    """
    return Config(
        config_dir=tmp_path,
        global_filter_paused=False,
        global_filter_excluded_categories=list(group_leaves),
        global_filter_excluded_prefixes=[],
        global_filter_excluded_user_categories=[],
    )


def _add_arabic_channel(file_db) -> str:
    """Seed one channel whose detected_prefix is a leaf of the Arabic group,
    carrying a language:Arabic content tag.  Returns its id."""
    cid = str(uuid.uuid4())
    with file_db.session_scope() as session:
        session.add(
            ChannelDB(
                id=cid,
                source_id=str(uuid.uuid4()),
                provider_id="test_provider",
                name="EG - Al Jazeera",
                detected_prefix=_LEAF_PREFIX,
            )
        )
        session.flush()
        repos = RepositoryFactory(session)
        repos.tags.set_content_tags(
            cid, [("language", "Arabic", "test_feeder")]
        )
    return cid


def _recipe_view_with_config(config: Config) -> RecipeView:
    """Build a bare RecipeView shell whose only used attribute is _config.

    ``_global_exclusion_sets`` reads nothing but ``self._config``, so we skip the
    full Qt widget construction (per CLAUDE.md async-read test guidance).
    """
    view = RecipeView.__new__(RecipeView)
    view._config = config
    return view


# ---------------------------------------------------------------------------
# 1. _global_exclusion_sets expands a checked GROUP into its leaf prefixes
# ---------------------------------------------------------------------------


def test_global_exclusion_sets_contains_group_leaf(tmp_path):
    """A checked language group's leaf codes are present in the prefix set."""
    cfg = _checked_group_config(tmp_path, _ARABIC_LEAVES)
    view = _recipe_view_with_config(cfg)

    excluded_prefixes, excluded_categories, _excluded_ct = view._global_exclusion_sets()

    assert _LEAF_PREFIX in excluded_prefixes, (
        "A leaf prefix of the checked Arabic group must be excluded — the bug "
        "left this set empty/group-named so nothing matched detected_prefix."
    )
    # The whole group should resolve through, not just the one code.
    assert set(_ARABIC_LEAVES) <= excluded_prefixes
    assert excluded_categories == set()


# ---------------------------------------------------------------------------
# 2. End-to-end: the engine drops the channel when scoped with those sets
# ---------------------------------------------------------------------------


def test_engine_drops_channel_for_checked_group(tmp_path, file_db):
    """get_tag_counts_for_facet / count_channels_by_tag_facets scoped with the
    recipe view's resolved sets drop the Arabic-group channel."""
    cid = _add_arabic_channel(file_db)
    cfg = _checked_group_config(tmp_path, _ARABIC_LEAVES)
    view = _recipe_view_with_config(cfg)
    excluded_prefixes, excluded_categories, _excluded_ct = view._global_exclusion_sets()

    with file_db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)

        # Sanity: WITHOUT exclusions the channel is counted for language:Arabic.
        unscoped = repos.tags.get_tag_counts_for_facet("language")
        assert any(
            dto.value == "Arabic" and dto.channel_count == 1 for dto in unscoped
        ), "Arabic channel should be visible before exclusion"

        # WITH the resolved exclusion sets, the channel is dropped — the facet
        # value disappears entirely (its only carrier is excluded).
        scoped = repos.tags.get_tag_counts_for_facet(
            "language",
            excluded_prefixes=excluded_prefixes,
            excluded_categories=excluded_categories,
        )
        assert all(dto.value != "Arabic" for dto in scoped), (
            "Arabic facet value must vanish once the group's leaf prefix is excluded"
        )

        # And the faceted match count for language:Arabic is now zero.
        # (The faceted engine only applies Global Exclusions under the
        # visible-channel scope, i.e. when excluded_provider_ids is not None —
        # the recipe view always passes get_hidden_provider_ids(); [] excludes
        # no providers but still opts into the prefix/category scope.)
        n = repos.tags.count_channels_by_tag_facets(
            {"language": {"Arabic"}},
            excluded_provider_ids=[],
            excluded_prefixes=excluded_prefixes,
            excluded_categories=excluded_categories,
        )
        assert n == 0, "No Arabic channels should remain after exclusion"

        # Without exclusions, the same faceted count finds the channel.
        n_unscoped = repos.tags.count_channels_by_tag_facets(
            {"language": {"Arabic"}},
            excluded_provider_ids=[],
        )
        assert n_unscoped == 1
    assert cid  # channel was actually seeded


# ---------------------------------------------------------------------------
# 3. Paused → empty sets → channel reappears
# ---------------------------------------------------------------------------


def test_paused_returns_empty_sets_channel_reappears(tmp_path, file_db):
    """global_filter_paused=True yields empty sets, so the channel is counted."""
    _add_arabic_channel(file_db)
    cfg = _checked_group_config(tmp_path, _ARABIC_LEAVES)
    cfg.global_filter_paused = True
    view = _recipe_view_with_config(cfg)

    excluded_prefixes, excluded_categories, _excluded_ct = view._global_exclusion_sets()
    assert excluded_prefixes == set()
    assert excluded_categories == set()

    with file_db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        n = repos.tags.count_channels_by_tag_facets(
            {"language": {"Arabic"}},
            excluded_provider_ids=[],
            excluded_prefixes=excluded_prefixes,
            excluded_categories=excluded_categories,
        )
        assert n == 1, "Paused global filter must let the Arabic channel reappear"


# ---------------------------------------------------------------------------
# 4. Delegation: the helper routes through the canonical filter_utils resolvers
# ---------------------------------------------------------------------------


def test_global_exclusion_sets_delegates_to_filter_utils(tmp_path, monkeypatch):
    """The prefix set is built via filter_utils.get_active_category_filter +
    get_excluded_prefixes, NOT a raw-config union.

    This is the half that regressed: a raw union never calls the resolver, so a
    checked GROUP (which the resolver would expand) silently excluded nothing.
    """
    import metatv.core.filter_utils as fu

    cfg = _checked_group_config(tmp_path, _ARABIC_LEAVES)
    cfg.global_filter_excluded_prefixes = ["KU"]  # explicit "Block [PREFIX]"
    view = _recipe_view_with_config(cfg)

    called = {"category": False, "prefixes": False}
    real_category = fu.get_active_category_filter
    real_prefixes = fu.get_excluded_prefixes

    def _spy_category(config):
        called["category"] = True
        return real_category(config)

    def _spy_prefixes(config):
        called["prefixes"] = True
        return real_prefixes(config)

    # Patch on the module RecipeView imports from (it imports inside the method).
    monkeypatch.setattr(fu, "get_active_category_filter", _spy_category)
    monkeypatch.setattr(fu, "get_excluded_prefixes", _spy_prefixes)

    excluded_prefixes, _, _ = view._global_exclusion_sets()

    assert called["category"], "_global_exclusion_sets must call get_active_category_filter"
    assert called["prefixes"], "_global_exclusion_sets must call get_excluded_prefixes"
    # Both contributions present: group leaves + the explicit blocked prefix.
    assert _LEAF_PREFIX in excluded_prefixes
    assert "KU" in excluded_prefixes
