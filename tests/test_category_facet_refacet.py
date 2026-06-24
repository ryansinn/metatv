"""Behavioral tests for the category-facet re-facet (category: / genre: routing).

Tests:
1. remap_content_descriptor_facets() helper — pure routing logic, no DB.
2. _collect_tags() integration — asserts that content-descriptor values route
   to the correct facet based on media_type.
3. Migration task (CategoryFacetRefacetTask) — seeds a file-backed DB with
   wrong-facet tags, runs the task, then asserts the tags are corrected and
   the orphan wrong-facet TagDB rows are pruned.

All tests use file-backed SQLite (tmp_path) per the CLAUDE.md rule.
"""

from __future__ import annotations

import uuid

import pytest

from metatv.core.channel_name_utils import CONTENT_DESCRIPTOR_GROUPS
from metatv.core.config import Config
from metatv.core.database import Base, ChannelDB, ContentTagDB, Database, TagDB
from metatv.core.migrations.tag_backfill import _collect_tags
from metatv.core.repositories import RepositoryFactory
from metatv.core.tag_decomposer import remap_content_descriptor_facets


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def file_db(tmp_path):
    """File-backed SQLite Database with all tables created."""
    db_file = tmp_path / "test_category_refacet.db"
    db = Database(f"sqlite:///{db_file}")
    db.create_tables()
    yield db
    db.close()


@pytest.fixture
def cfg(tmp_path):
    """Isolated Config with default filter groups.  No write to real ~/.config."""
    return Config(config_dir=tmp_path / "cfg")


# ---------------------------------------------------------------------------
# 1.  remap_content_descriptor_facets — pure helper
# ---------------------------------------------------------------------------

class TestRemapContentDescriptorFacets:
    """Pure routing logic — no DB."""

    def test_live_channel_sports_becomes_category(self):
        """live Sports → category:Sports"""
        fmap = {("platform", "Sports"): {"header"}}
        result = remap_content_descriptor_facets(fmap, "live")
        assert ("category", "Sports") in result
        assert ("platform", "Sports") not in result
        assert result[("category", "Sports")] == {"header"}

    def test_movie_channel_sports_becomes_genre(self):
        """movie Sports → genre:Sports"""
        fmap = {("platform", "Sports"): {"provider_category"}}
        result = remap_content_descriptor_facets(fmap, "movie")
        assert ("genre", "Sports") in result
        assert ("platform", "Sports") not in result

    def test_live_adult_becomes_category(self):
        """live Adult (from language: group) → category:Adult"""
        fmap = {("language", "Adult"): {"provider_category"}}
        result = remap_content_descriptor_facets(fmap, "live")
        assert ("category", "Adult") in result
        assert ("language", "Adult") not in result

    def test_movie_adult_becomes_genre(self):
        """movie Adult → genre:Adult"""
        fmap = {("language", "Adult"): {"provider_category"}}
        result = remap_content_descriptor_facets(fmap, "movie")
        assert ("genre", "Adult") in result
        assert ("language", "Adult") not in result

    def test_unknown_media_type_becomes_genre(self):
        """media_type=None → treat as non-live → genre:"""
        fmap = {("platform", "Kids"): {"header"}}
        result = remap_content_descriptor_facets(fmap, None)
        assert ("genre", "Kids") in result
        assert ("platform", "Kids") not in result

    def test_unknown_media_type_string_becomes_genre(self):
        """media_type='unknown' → genre:"""
        fmap = {("platform", "Music"): {"header"}}
        result = remap_content_descriptor_facets(fmap, "unknown")
        assert ("genre", "Music") in result

    def test_non_descriptor_tag_unchanged(self):
        """English stays language:English — not a descriptor group."""
        fmap = {("language", "English"): {"name_parse"}}
        result = remap_content_descriptor_facets(fmap, "live")
        assert ("language", "English") in result

    def test_drama_genre_unchanged(self):
        """genre:Drama is not a descriptor group and must not be touched."""
        fmap = {("genre", "Drama"): {"genre"}}
        result = remap_content_descriptor_facets(fmap, "live")
        assert ("genre", "Drama") in result

    def test_pay_tv_unchanged(self):
        """platform:Pay TV stays — Pay TV is NOT in CONTENT_DESCRIPTOR_GROUPS."""
        fmap = {("platform", "Pay TV"): {"header"}}
        result = remap_content_descriptor_facets(fmap, "live")
        # Pay TV is deliberately absent from CONTENT_DESCRIPTOR_GROUPS so it must
        # pass through the remap unchanged.
        assert ("platform", "Pay TV") in result
        assert ("category", "Pay TV") not in result

    def test_feeders_merged_when_target_key_already_exists(self):
        """If genre:Sports already exists, feeders from platform:Sports are merged in."""
        fmap = {
            ("platform", "Sports"): {"header"},
            ("genre", "Sports"):    {"genre"},
        }
        result = remap_content_descriptor_facets(fmap, "movie")
        assert ("genre", "Sports") in result
        assert result[("genre", "Sports")] == {"header", "genre"}
        assert ("platform", "Sports") not in result

    def test_correct_facet_already_set_no_duplicate(self):
        """A category:Sports key on a live channel must not be moved (already correct)."""
        fmap = {("category", "Sports"): {"provider_category"}}
        result = remap_content_descriptor_facets(fmap, "live")
        assert ("category", "Sports") in result
        # Only one entry for Sports
        sports_keys = [k for k in result if k[1] == "Sports"]
        assert len(sports_keys) == 1


# ---------------------------------------------------------------------------
# 2.  _collect_tags integration — media_type routing
# ---------------------------------------------------------------------------

class TestCollectTagsMediaTypeRouting:
    """_collect_tags routes content-descriptor groups by media_type."""

    def test_live_sports_category_in_collect_tags(self, cfg):
        """_collect_tags(media_type='live') routes Sports → category:Sports."""
        tags = _collect_tags(
            config=cfg,
            category="Sports",
            source_category=None,
            detected_prefix=None,
            detected_quality=None,
            detected_region=None,
            detected_year=None,
            raw_data=None,
            media_type="live",
        )
        type_values = {(t, v) for t, v, _ in tags}
        assert ("category", "Sports") in type_values
        assert ("platform", "Sports") not in type_values
        assert ("language", "Sports") not in type_values

    def test_movie_sports_genre_in_collect_tags(self, cfg):
        """_collect_tags(media_type='movie') routes Sports → genre:Sports."""
        tags = _collect_tags(
            config=cfg,
            category="Sports",
            source_category=None,
            detected_prefix=None,
            detected_quality=None,
            detected_region=None,
            detected_year=None,
            raw_data=None,
            media_type="movie",
        )
        type_values = {(t, v) for t, v, _ in tags}
        assert ("genre", "Sports") in type_values
        assert ("platform", "Sports") not in type_values

    def test_live_adult_category_in_collect_tags(self, cfg):
        """_collect_tags(media_type='live') routes Adult → category:Adult."""
        tags = _collect_tags(
            config=cfg,
            category="Adult",
            source_category=None,
            detected_prefix=None,
            detected_quality=None,
            detected_region=None,
            detected_year=None,
            raw_data=None,
            media_type="live",
        )
        type_values = {(t, v) for t, v, _ in tags}
        assert ("category", "Adult") in type_values
        assert ("language", "Adult") not in type_values

    def test_movie_adult_genre_in_collect_tags(self, cfg):
        """_collect_tags(media_type='movie') routes Adult → genre:Adult."""
        tags = _collect_tags(
            config=cfg,
            category="Adult",
            source_category=None,
            detected_prefix=None,
            detected_quality=None,
            detected_region=None,
            detected_year=None,
            raw_data=None,
            media_type="movie",
        )
        type_values = {(t, v) for t, v, _ in tags}
        assert ("genre", "Adult") in type_values
        assert ("language", "Adult") not in type_values

    def test_non_descriptor_language_untouched_by_routing(self, cfg):
        """language:English must not be touched regardless of media_type."""
        tags = _collect_tags(
            config=cfg,
            category="English",
            source_category=None,
            detected_prefix=None,
            detected_quality=None,
            detected_region=None,
            detected_year=None,
            raw_data=None,
            media_type="live",
        )
        type_values = {(t, v) for t, v, _ in tags}
        assert ("language", "English") in type_values

    def test_drama_genre_untouched(self, cfg):
        """genre:Drama from raw_data must not be moved to category: even on live."""
        tags = _collect_tags(
            config=cfg,
            category=None,
            source_category=None,
            detected_prefix=None,
            detected_quality=None,
            detected_region=None,
            detected_year=None,
            raw_data={"genre": "Drama"},
            media_type="live",
        )
        type_values = {(t, v) for t, v, _ in tags}
        assert ("genre", "Drama") in type_values
        assert ("category", "Drama") not in type_values

    def test_pay_tv_not_in_descriptor_groups(self):
        """Pay TV must NOT be in CONTENT_DESCRIPTOR_GROUPS — it is a real platform."""
        # The routing helper must leave Pay TV alone.
        # In practice the decomposer surfaces it as collection: when no prefix matches,
        # but the important invariant is that CONTENT_DESCRIPTOR_GROUPS doesn't include it.
        assert "Pay TV" not in CONTENT_DESCRIPTOR_GROUPS


# ---------------------------------------------------------------------------
# Helpers for migration tests
# ---------------------------------------------------------------------------

def _add_channel(
    db: Database,
    *,
    name: str = "Test Channel",
    media_type: str = "live",
    category: str | None = None,
    source_category: str | None = None,
    detected_prefix: str | None = None,
) -> str:
    """Insert a minimal ChannelDB row and return its id."""
    channel_id = str(uuid.uuid4())
    with db.session_scope() as session:
        ch = ChannelDB(
            id=channel_id,
            source_id=str(uuid.uuid4()),
            provider_id="test_provider",
            name=name,
            media_type=media_type,
            category=category,
            source_category=source_category,
            detected_prefix=detected_prefix,
        )
        session.add(ch)
    return channel_id


def _set_tags_directly(
    db: Database,
    channel_id: str,
    tags: list[tuple[str, str]],  # (type, value) pairs
) -> None:
    """Directly insert content_tags rows (bypasses routing — simulates old wrong state)."""
    with db.session_scope() as session:
        repos = RepositoryFactory(session)
        tuples = [(t, v, "provider_category") for t, v in tags]
        repos.tags.set_content_tags(channel_id, tuples, source="generated")


def _tags_for(db: Database, channel_id: str) -> set[tuple[str, str]]:
    """Return {(type, value)} for all content_tags of a channel."""
    with db.session_scope(commit=False) as session:
        rows = (
            session.query(TagDB.type, TagDB.value)
            .join(ContentTagDB, ContentTagDB.tag_id == TagDB.id)
            .filter(ContentTagDB.channel_id == channel_id)
            .all()
        )
    return {(r[0], r[1]) for r in rows}


def _orphan_tag_exists(db: Database, tag_type: str, tag_value: str) -> bool:
    """Return True if a TagDB row exists with zero content_tags links."""
    with db.session_scope(commit=False) as session:
        tag = (
            session.query(TagDB)
            .filter(TagDB.type == tag_type, TagDB.value == tag_value)
            .first()
        )
        if tag is None:
            return False
        count = (
            session.query(ContentTagDB)
            .filter(ContentTagDB.tag_id == tag.id)
            .count()
        )
        return count == 0


def _run_migration(db: Database, cfg: Config) -> None:
    """Run CategoryFacetRefacetTask to completion and call on_completed."""
    from metatv.core.migrations.category_facet_refacet import CategoryFacetRefacetTask

    task = CategoryFacetRefacetTask(db, config=cfg)
    task.run(
        progress_cb=lambda done, total: None,
        is_cancelled=lambda: False,
    )
    task.on_completed(cfg)


# ---------------------------------------------------------------------------
# 3.  Migration task — end-to-end via file-backed DB
# ---------------------------------------------------------------------------

class TestCategoryFacetRefacetMigration:
    """End-to-end migration tests via file-backed SQLite."""

    def test_needs_run_when_version_at_zero(self, cfg):
        """needs_run() must return True when category_facet_version == 0."""
        from metatv.core.migrations.category_facet_refacet import (
            CURRENT_VERSION,
            CategoryFacetRefacetTask,
        )
        task = CategoryFacetRefacetTask.__new__(CategoryFacetRefacetTask)
        assert task.needs_run(cfg) is True

    def test_needs_run_false_after_completion(self, file_db, cfg):
        """needs_run() returns False after on_completed() bumps the version."""
        from metatv.core.migrations.category_facet_refacet import CategoryFacetRefacetTask

        task = CategoryFacetRefacetTask(file_db, config=cfg)
        task.run(lambda d, t: None, lambda: False)
        task.on_completed(cfg)

        task2 = CategoryFacetRefacetTask(file_db, config=cfg)
        assert task2.needs_run(cfg) is False

    def test_live_adult_becomes_category_adult(self, file_db, cfg):
        """live channel: language:Adult → category:Adult after migration."""
        ch_id = _add_channel(file_db, media_type="live", category="Adult")
        # Seed the wrong facet directly
        _set_tags_directly(file_db, ch_id, [("language", "Adult")])
        assert ("language", "Adult") in _tags_for(file_db, ch_id)

        _run_migration(file_db, cfg)

        tags = _tags_for(file_db, ch_id)
        assert ("category", "Adult") in tags, f"expected category:Adult; got {tags}"
        assert ("language", "Adult") not in tags, f"language:Adult must be gone; got {tags}"

    def test_movie_adult_becomes_genre_adult(self, file_db, cfg):
        """movie channel: language:Adult → genre:Adult after migration."""
        ch_id = _add_channel(file_db, media_type="movie", category="Adult")
        _set_tags_directly(file_db, ch_id, [("language", "Adult")])

        _run_migration(file_db, cfg)

        tags = _tags_for(file_db, ch_id)
        assert ("genre", "Adult") in tags, f"expected genre:Adult; got {tags}"
        assert ("language", "Adult") not in tags

    def test_live_sports_becomes_category_sports(self, file_db, cfg):
        """live channel: platform:Sports → category:Sports after migration."""
        ch_id = _add_channel(file_db, media_type="live", category="Sports")
        _set_tags_directly(file_db, ch_id, [("platform", "Sports")])

        _run_migration(file_db, cfg)

        tags = _tags_for(file_db, ch_id)
        assert ("category", "Sports") in tags, f"expected category:Sports; got {tags}"
        assert ("platform", "Sports") not in tags

    def test_movie_sports_becomes_genre_sports(self, file_db, cfg):
        """movie channel: platform:Sports → genre:Sports after migration."""
        ch_id = _add_channel(file_db, media_type="movie", category="Sports")
        _set_tags_directly(file_db, ch_id, [("platform", "Sports")])

        _run_migration(file_db, cfg)

        tags = _tags_for(file_db, ch_id)
        assert ("genre", "Sports") in tags, f"expected genre:Sports; got {tags}"
        assert ("platform", "Sports") not in tags

    def test_orphan_wrong_facet_tags_pruned(self, file_db, cfg):
        """After migration, orphaned language:Adult and platform:Sports rows are deleted."""
        ch_live = _add_channel(file_db, media_type="live", category="Adult")
        _set_tags_directly(file_db, ch_live, [("language", "Adult")])

        ch_movie = _add_channel(file_db, media_type="movie", category="Sports")
        _set_tags_directly(file_db, ch_movie, [("platform", "Sports")])

        _run_migration(file_db, cfg)

        # The old-facet TagDB rows should have zero links and on_completed() prunes them.
        assert not _orphan_tag_exists(file_db, "language", "Adult"), (
            "language:Adult TagDB row must be pruned (zero links)"
        )
        assert not _orphan_tag_exists(file_db, "platform", "Sports"), (
            "platform:Sports TagDB row must be pruned (zero links)"
        )

    def test_non_descriptor_tags_from_stored_fields_preserved(self, file_db, cfg):
        """language:English from detected_prefix='EN' must survive the migration.

        The migration re-runs _collect_tags from the channel's stored DB columns,
        so non-descriptor tags are preserved when their source field is still set.
        """
        # Channel with both a descriptor (Sports → should become genre:) and a
        # non-descriptor (EN → should stay language:English).
        ch_id = _add_channel(
            file_db,
            media_type="movie",
            category="Sports",
            detected_prefix="EN",
        )
        # Seed with the currently-wrong tag for Sports
        _set_tags_directly(file_db, ch_id, [("platform", "Sports")])

        _run_migration(file_db, cfg)

        tags = _tags_for(file_db, ch_id)
        # Sports re-derived as genre: (movie)
        assert ("genre", "Sports") in tags
        # EN re-derived as language:English from detected_prefix
        assert ("language", "English") in tags

    def test_no_op_on_empty_db(self, file_db, cfg):
        """Migration must complete without error when there are no channels."""
        from metatv.core.migrations.category_facet_refacet import CategoryFacetRefacetTask

        called: list[tuple[int, int]] = []
        task = CategoryFacetRefacetTask(file_db, config=cfg)
        task.run(lambda d, t: called.append((d, t)), lambda: False)
        # (0, 0) emitted when nothing to do
        assert called == [(0, 0)]

    def test_idempotent_second_run(self, file_db, cfg):
        """Running the migration twice produces the same result (idempotent)."""
        ch_id = _add_channel(file_db, media_type="live", category="Sports")
        _set_tags_directly(file_db, ch_id, [("platform", "Sports")])

        _run_migration(file_db, cfg)
        tags_after_first = _tags_for(file_db, ch_id)

        # Force needs_run to return True again
        cfg.category_facet_version = 0
        _run_migration(file_db, cfg)
        tags_after_second = _tags_for(file_db, ch_id)

        assert tags_after_first == tags_after_second
