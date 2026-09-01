"""The collapsed zone recorded the default, 818 times, and grew forever.

Owner: *"discover collapsed shelves state should be stored in the database and
not be append only, why is it append only?"*

It was never append-only by intent — the write rebuilds the list from the
currently-rendered shelves. What made it grow is that **collapsed is the
DEFAULT zone**: ``determine_zone`` ends ``return _ZONE_COLLAPSED``. So the list
was "every shelf ever rendered that you did not pin, expand or hide" — 818
entries on the owner's config (17% of the whole file), each recording the
answer the code reaches with no entry at all.

Storing only the three zones that DEVIATE from the default says exactly the
same thing in nothing.

**The trap, and why this needed a migration rather than a deletion.**
``_is_first_launch`` meant "all four zone lists are empty". Stop storing
collapsed and a user who had only ever collapsed shelves matches that — so
every start looks like their first and re-expands the defaults they put away.
Inferring a first run from an absence of data breaks the moment having no data
is legitimate, so there is now an explicit ``discover_zones_seeded`` marker and
a migration that transfers the old meaning before clearing anything.
"""
from __future__ import annotations

import pytest

from metatv.core.config import Config


@pytest.fixture()
def cfg(tmp_path):
    return Config(config_dir=tmp_path / "config", data_dir=tmp_path / "data",
                  cache_dir=tmp_path / "cache")


# ── the migration ──────────────────────────────────────────────────────────


def test_a_returning_user_is_not_treated_as_first_launch(cfg):
    """The whole reason this needed a migration.

    Only ever collapsed things → all other lists empty. Under the old rule
    that is indistinguishable from a fresh install.
    """
    cfg.discover_collapsed_shelves = ["genre:Action", "genre:Drama"]
    cfg._retire_collapsed_shelves()

    assert cfg.discover_zones_seeded is True, (
        "a user who had only collapsed shelves would be re-shown the "
        "first-launch defaults on every start")
    assert cfg.discover_collapsed_shelves == [], "the stored default was not dropped"


def test_a_genuinely_new_config_is_still_a_first_launch(cfg):
    """Non-degeneracy: the migration must not seed someone who has never run."""
    cfg._retire_collapsed_shelves()
    assert cfg.discover_zones_seeded is False, (
        "a fresh install was marked as having already seen the defaults, so it "
        "would never get them")


def test_the_other_three_zones_survive_untouched(cfg):
    """Only the default is dropped. Everything the user actually chose stays."""
    cfg.discover_pinned_shelves = ["genre:Horror"]
    cfg.discover_expanded_shelves = ["genre:Comedy"]
    cfg.discover_hidden_shelves = ["genre:Sport"]
    cfg.discover_collapsed_shelves = ["genre:Action"]

    cfg._retire_collapsed_shelves()

    assert cfg.discover_pinned_shelves == ["genre:Horror"]
    assert cfg.discover_expanded_shelves == ["genre:Comedy"]
    assert cfg.discover_hidden_shelves == ["genre:Sport"]
    assert cfg.discover_collapsed_shelves == []


def test_the_migration_runs_once_and_then_leaves_it_alone(cfg):
    """A second pass must not re-seed or re-clear — it is a one-time move."""
    cfg.discover_collapsed_shelves = ["genre:Action"]
    cfg._retire_collapsed_shelves()
    # Someone legitimately writes the field again (an old build, a restored
    # backup). Already seeded, so the migration must not touch it.
    cfg.discover_collapsed_shelves = ["genre:Later"]
    cfg._retire_collapsed_shelves()
    assert cfg.discover_collapsed_shelves == ["genre:Later"]


def test_it_runs_on_load(tmp_path, monkeypatch):
    """The migration is wired into Config.load, not merely available."""
    import inspect
    src = inspect.getsource(Config.load)
    assert src.count("_retire_collapsed_shelves()") == 2, (
        "both load paths — normal and backup-restore — must migrate, or a "
        "config recovered from backup keeps the 818 entries")


# ── the zone rule itself ───────────────────────────────────────────────────


def test_an_unlisted_shelf_still_resolves_to_collapsed():
    """The reason dropping the list is safe: it is the fallthrough."""
    from metatv.gui.discover_workers import determine_zone

    zone = determine_zone(
        "genre:Anything", pinned=frozenset(), expanded=frozenset(),
        collapsed=frozenset(), hidden=frozenset(),
        default_expanded=frozenset(), first_launch=False)
    assert zone == "collapsed"


def test_first_launch_still_expands_the_shipped_defaults():
    """And the one case where absence does NOT mean collapsed."""
    from metatv.gui.discover_workers import determine_zone

    zone = determine_zone(
        "genre:Action", pinned=frozenset(), expanded=frozenset(),
        collapsed=frozenset(), hidden=frozenset(),
        default_expanded=frozenset({"genre:Action"}), first_launch=True)
    assert zone == "expanded"


def test_the_view_no_longer_writes_the_collapsed_zone():
    """Source-level, because the write is one line in a persist method."""
    import inspect

    from metatv.gui.discover_view import DiscoverView

    src = inspect.getsource(DiscoverView)
    assert "cfg.discover_collapsed_shelves =" not in src, (
        "the view still persists the collapsed zone, so it will grow again")
    assert "discover_zones_seeded = True" in src, (
        "nothing marks the zones as seeded, so every launch is a first launch")
