"""Tag counts and recipe samples honour "hide dead streams" (ledger D42).

The list, Discover, Recommendations and Similar all applied
``VisibilityScope.dead_signal_streak_floor``; the tag repository's count and
sample family did not, so a dead live channel still counted in a facet and
could be sampled into a recipe shelf. ``filter_utils.tag_query_scope`` now
carries the floor and every tag caller spreads it.
"""

from metatv.core.config import Config
from metatv.core.filter_utils import tag_query_scope
from metatv.core.repositories import RepositoryFactory
from tests.conftest import add_content_tag, make_channel


def _seed(db) -> tuple[str, str]:
    with db.session_scope() as session:
        alive = make_channel(session, "Alive Sports", media_type="live")
        dead = make_channel(session, "Dead Sports", media_type="live",
                            signal_dead_streak=5)
        tag_id = RepositoryFactory(session).tags.get_or_create_tag_id("category", "Sports")
        add_content_tag(session, alive.id, tag_id)
        add_content_tag(session, dead.id, tag_id)
        return alive.id, dead.id


def _config(tmp_path, hide: bool) -> Config:
    cfg = Config(config_dir=tmp_path)
    cfg.hide_dead_events = hide
    cfg.signal_dead_streak_to_hide = 3
    return cfg


def test_scope_carries_the_floor_only_when_hiding(tmp_path):
    assert tag_query_scope(_config(tmp_path, True))["dead_signal_streak_floor"] == 3
    assert tag_query_scope(_config(tmp_path, False))["dead_signal_streak_floor"] is None


def test_a_dead_channel_is_not_counted_in_its_facet(db, tmp_path):
    _seed(db)
    with db.session_scope(commit=False) as session:
        tags = RepositoryFactory(session).tags
        hiding = tags.get_facet_value_counts(
            excluded_provider_ids=[], **tag_query_scope(_config(tmp_path, True)))
        showing = tags.get_facet_value_counts(
            excluded_provider_ids=[], **tag_query_scope(_config(tmp_path, False)))
    assert hiding["category"]["Sports"] == 1
    assert showing["category"]["Sports"] == 2


def test_a_dead_channel_is_not_sampled_into_a_recipe(db, tmp_path):
    alive_id, dead_id = _seed(db)
    with db.session_scope(commit=False) as session:
        cards = RepositoryFactory(session).tags.sample_channels_by_tag_facets(
            includes={"category": {"Sports"}}, excluded_provider_ids=[],
            **tag_query_scope(_config(tmp_path, True)))
    ids = {getattr(c, "id", None) or getattr(c, "channel_id", None) for c in cards}
    assert alive_id in ids
    assert dead_id not in ids


def test_exclusions_apply_without_provider_ids(db, tmp_path):
    """F25: passing an exclusion but no provider-id list used to drop it."""
    alive_id, dead_id = _seed(db)
    with db.session_scope(commit=False) as session:
        ids = RepositoryFactory(session).tags.get_channel_ids_by_tag_facets(
            {"category": {"Sports"}}, dead_signal_streak_floor=3)
    assert alive_id in ids and dead_id not in ids
