"""Behavioral tests for the tag backfill migration (Tags Slice T3, DR-0005).

Every test exercises the actual code path that could regress — no shape/string
assertions.  Tests use file-backed SQLite (``tmp_path``) per the CLAUDE.md rule
("not :memory:, whose pooled connections each get an empty DB").

Coverage:
- Seeds a channel with known category / source_category / detected_* / raw_data
  fields, runs the full backfill, and asserts the expected ``content_tags`` rows.
- Verifies that user-tagged channels survive a re-run unharmed.
- Verifies that a completed run is idempotent (same rows, no duplicates).
- Verifies that ``source="user"`` tags are never touched by the backfill.
- Verifies that confidence rises when multiple feeders agree on the same tag.
- Verifies that ``TagBackfillTask.needs_run`` gates correctly on version.
"""

from __future__ import annotations

import uuid

import pytest

from metatv.core.config import Config
from metatv.core.database import Base, ChannelDB, ContentTagDB, Database, TagDB
from metatv.core.migrations.tag_backfill import (
    CURRENT_TAG_BACKFILL_VERSION,
    TagBackfillTask,
    _collect_tags,
)
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.tag import _compute_confidence


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def file_db(tmp_path):
    """File-backed SQLite Database with all tables created."""
    db_file = tmp_path / "test_tag_backfill.db"
    db = Database(f"sqlite:///{db_file}")
    db.create_tables()
    yield db
    db.close()


@pytest.fixture
def cfg(tmp_path):
    """Isolated Config instance with default filter groups.

    config_dir is set to tmp_path so no write goes to ~/.config/metatv.
    """
    return Config(config_dir=tmp_path / "cfg")


def _add_channel(
    db: Database,
    *,
    name: str = "Test Channel",
    category: str | None = None,
    source_category: str | None = None,
    detected_prefix: str | None = None,
    detected_quality: str | None = None,
    detected_region: str | None = None,
    detected_year: str | None = None,
    raw_data: dict | None = None,
) -> str:
    """Insert a minimal ChannelDB row and return its id."""
    channel_id = str(uuid.uuid4())
    with db.session_scope() as session:
        ch = ChannelDB(
            id=channel_id,
            source_id=str(uuid.uuid4()),
            provider_id="test_provider",
            name=name,
            category=category,
            source_category=source_category,
            detected_prefix=detected_prefix,
            detected_quality=detected_quality,
            detected_region=detected_region,
            detected_year=detected_year,
            raw_data=raw_data,
        )
        session.add(ch)
    return channel_id


def _run_backfill(db: Database, cfg: Config) -> None:
    """Run the backfill to completion (no cancellation)."""
    task = TagBackfillTask(db, config=cfg)
    _progress_calls: list[tuple[int, int]] = []

    def _progress(done: int, total: int) -> None:
        _progress_calls.append((done, total))

    task.run(_progress, is_cancelled=lambda: False)


def _tags_for(db: Database, channel_id: str) -> list[tuple[str, str, str, list[str]]]:
    """Return ``(type, value, source, feeders)`` for all content_tags on a channel."""
    with db.session_scope(commit=False) as session:
        rows = (
            session.query(TagDB.type, TagDB.value, ContentTagDB.source, ContentTagDB.feeders)
            .join(ContentTagDB, ContentTagDB.tag_id == TagDB.id)
            .filter(ContentTagDB.channel_id == channel_id)
            .all()
        )
    return [(r.type, r.value, r.source, list(r.feeders or [])) for r in rows]


def _content_tag_count(db: Database, channel_id: str, source: str = "generated") -> int:
    """Count ContentTagDB rows for a channel with the given source."""
    with db.session_scope(commit=False) as session:
        return (
            session.query(ContentTagDB)
            .filter_by(channel_id=channel_id, source=source)
            .count()
        )


# ---------------------------------------------------------------------------
# needs_run
# ---------------------------------------------------------------------------

class TestNeedsRun:
    def test_needs_run_when_version_zero(self, cfg):
        """Task reports needs_run when tag_backfill_version is 0."""
        task = TagBackfillTask(None, config=cfg)  # type: ignore[arg-type]
        assert task.needs_run(cfg) is True

    def test_does_not_need_run_when_version_current(self, cfg):
        """Task reports not-needs_run when version already at current."""
        cfg.tag_backfill_version = CURRENT_TAG_BACKFILL_VERSION
        task = TagBackfillTask(None, config=cfg)  # type: ignore[arg-type]
        assert task.needs_run(cfg) is False

    def test_needs_run_when_version_behind(self, cfg):
        """Task reports needs_run when stored version is behind current."""
        cfg.tag_backfill_version = CURRENT_TAG_BACKFILL_VERSION - 1
        task = TagBackfillTask(None, config=cfg)  # type: ignore[arg-type]
        assert task.needs_run(cfg) is True


# ---------------------------------------------------------------------------
# on_completed
# ---------------------------------------------------------------------------

class TestOnCompleted:
    def test_on_completed_bumps_version(self, tmp_path, cfg):
        """on_completed sets tag_backfill_version to CURRENT and saves config."""
        task = TagBackfillTask(None, config=cfg)  # type: ignore[arg-type]
        task.on_completed(cfg)
        assert cfg.tag_backfill_version == CURRENT_TAG_BACKFILL_VERSION


# ---------------------------------------------------------------------------
# Feeder wiring (_collect_tags)
# ---------------------------------------------------------------------------

class TestCollectTags:
    """Unit tests for _collect_tags — pure function, no DB needed."""

    def test_provider_category_feeder_region(self, cfg):
        """A recognized region code in category produces a region tag via provider_category."""
        tags = _collect_tags(
            config=cfg,
            category="USA",
            source_category=None,
            detected_prefix=None,
            detected_quality=None,
            detected_region=None,
            detected_year=None,
            raw_data=None,
        )
        feeder_map = {(t, v): feeders for t, v, feeders in tags}
        # "USA" should produce a region:US tag from the compound decomposer
        assert ("region", "US") in feeder_map
        assert "provider_category" in feeder_map[("region", "US")]

    def test_provider_category_unrecognized_becomes_collection(self, cfg):
        """An unrecognized compound category token becomes a collection tag."""
        tags = _collect_tags(
            config=cfg,
            category="Drama",
            source_category=None,
            detected_prefix=None,
            detected_quality=None,
            detected_region=None,
            detected_year=None,
            raw_data=None,
        )
        feeder_map = {(t, v): feeders for t, v, feeders in tags}
        # "Drama" as a raw category string → collection (not genre, since no genre feeder)
        assert ("collection", "Drama") in feeder_map
        assert "provider_category" in feeder_map[("collection", "Drama")]

    def test_genre_feeder(self, cfg):
        """raw_data['genre'] produces a genre tag with feeder='genre'."""
        tags = _collect_tags(
            config=cfg,
            category=None,
            source_category=None,
            detected_prefix=None,
            detected_quality=None,
            detected_region=None,
            detected_year=None,
            raw_data={"genre": "Action"},
        )
        feeder_map = {(t, v): feeders for t, v, feeders in tags}
        assert ("genre", "Action") in feeder_map
        assert "genre" in feeder_map[("genre", "Action")]

    def test_name_parse_year_produces_decade(self, cfg):
        """A detected_year field produces a decade tag with feeder='name_parse'."""
        tags = _collect_tags(
            config=cfg,
            category=None,
            source_category=None,
            detected_prefix=None,
            detected_quality=None,
            detected_region=None,
            detected_year="1994",
            raw_data=None,
        )
        feeder_map = {(t, v): feeders for t, v, feeders in tags}
        assert ("decade", "1990s") in feeder_map
        assert "name_parse" in feeder_map[("decade", "1990s")]

    def test_two_feeders_agreeing_produce_two_entries(self, cfg):
        """When name_parse and genre both yield a decade tag, two (type, value, feeder)
        tuples are returned — one per feeder — so set_content_tags can merge them.

        The genre feeder produces genre tags; name_parse produces decade tags from
        detected_year.  To get two feeders to agree on the same (type, value), we use
        the header feeder (source_category) and the genre feeder on the same genre string,
        which both route through _decompose_genre for the genre feeder but NOT for the
        header feeder.  Instead, we verify that two independent feeders both produce a
        region tag from the same code — header "USA" → region:US and category "USA" →
        region:US — giving two entries for (region, US).
        """
        tags = _collect_tags(
            config=cfg,
            category="USA",          # provider_category → region:US
            source_category="USA",   # header → region:US
            detected_prefix=None,
            detected_quality=None,
            detected_region=None,
            detected_year=None,
            raw_data=None,
        )
        us_feeders = [feeder for t, v, feeder in tags if t == "region" and v == "US"]
        assert len(us_feeders) == 2
        assert set(us_feeders) == {"provider_category", "header"}

    def test_empty_inputs_return_empty_list(self, cfg):
        """All-None inputs → empty tag list."""
        tags = _collect_tags(
            config=cfg,
            category=None,
            source_category=None,
            detected_prefix=None,
            detected_quality=None,
            detected_region=None,
            detected_year=None,
            raw_data=None,
        )
        assert tags == []


# ---------------------------------------------------------------------------
# Full backfill — seed → run → assert content_tags
# ---------------------------------------------------------------------------

class TestBackfillPopulatesTags:
    def test_region_from_category(self, file_db, cfg):
        """A channel with category='USA' gets a region:US content_tag after backfill."""
        cid = _add_channel(file_db, category="USA")
        _run_backfill(file_db, cfg)

        tags = _tags_for(file_db, cid)
        type_value_pairs = {(t, v) for t, v, _src, _f in tags}
        assert ("region", "US") in type_value_pairs

    def test_genre_from_raw_data(self, file_db, cfg):
        """A channel with raw_data genre gets a genre tag after backfill."""
        cid = _add_channel(file_db, raw_data={"genre": "Thriller"})
        _run_backfill(file_db, cfg)

        tags = _tags_for(file_db, cid)
        type_value_pairs = {(t, v) for t, v, _src, _f in tags}
        assert ("genre", "Thriller") in type_value_pairs

    def test_decade_from_detected_year(self, file_db, cfg):
        """A channel with detected_year='2003' gets a decade:2000s tag."""
        cid = _add_channel(file_db, detected_year="2003")
        _run_backfill(file_db, cfg)

        tags = _tags_for(file_db, cid)
        type_value_pairs = {(t, v) for t, v, _src, _f in tags}
        assert ("decade", "2000s") in type_value_pairs

    def test_tags_have_generated_source(self, file_db, cfg):
        """All backfill-created tags carry source='generated'."""
        cid = _add_channel(file_db, raw_data={"genre": "Comedy"})
        _run_backfill(file_db, cfg)

        tags = _tags_for(file_db, cid)
        assert tags, "Expected at least one tag from the genre feeder"
        assert all(src == "generated" for _t, _v, src, _f in tags)

    def test_multi_feeder_confidence_higher(self, file_db, cfg):
        """When category and header both produce region:US, confidence is higher than
        one feeder alone — because two independent feeders corroborate the same tag."""
        cid = _add_channel(file_db, category="USA", source_category="USA")
        _run_backfill(file_db, cfg)

        with file_db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            tag = session.query(TagDB).filter_by(type="region", value="US").first()
            assert tag is not None, "region:US tag should have been created"
            link = (
                session.query(ContentTagDB)
                .filter_by(channel_id=cid, tag_id=tag.id, source="generated")
                .one()
            )
            assert len(set(link.feeders)) == 2
            assert link.confidence > _compute_confidence(["single_feeder"])

    def test_no_channel_produces_no_tags(self, file_db, cfg):
        """A channel with all-None feeder fields gets no content_tags."""
        cid = _add_channel(file_db, name="Blank Channel")
        _run_backfill(file_db, cfg)

        count = _content_tag_count(file_db, cid)
        assert count == 0


# ---------------------------------------------------------------------------
# Non-destructive: user tags survive a backfill run
# ---------------------------------------------------------------------------

class TestUserTagsSurvive:
    def test_user_tag_preserved_after_backfill(self, file_db, cfg):
        """A source='user' content_tag is untouched by the backfill."""
        cid = _add_channel(file_db, name="No Feeders Channel")

        # Plant a user tag before running the backfill.
        with file_db.session_scope() as session:
            repos = RepositoryFactory(session)
            repos.tags.set_content_tags(
                cid,
                [("genre", "Drama", "human_curation")],
                source="user",
            )

        _run_backfill(file_db, cfg)

        user_links = _content_tag_count(file_db, cid, source="user")
        assert user_links == 1, "user tag must survive the backfill"

    def test_user_tag_and_generated_tag_coexist(self, file_db, cfg):
        """User and generated tags for the same (type, value) coexist independently.

        The channel has raw_data genre='Drama' so the backfill produces a
        generated genre:Drama tag; a pre-existing user tag on the same (type, value)
        must survive alongside it.
        """
        cid = _add_channel(file_db, raw_data={"genre": "Drama"})

        with file_db.session_scope() as session:
            repos = RepositoryFactory(session)
            repos.tags.set_content_tags(
                cid, [("genre", "Drama", "human")], source="user"
            )

        _run_backfill(file_db, cfg)

        tags = _tags_for(file_db, cid)
        sources = {src for _t, _v, src, _f in tags if _t == "genre" and _v == "Drama"}
        assert "user" in sources
        assert "generated" in sources


# ---------------------------------------------------------------------------
# Idempotency: running the backfill twice produces the same result
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_second_run_same_tags(self, file_db, cfg):
        """Running the backfill twice on the same channel produces identical tag sets."""
        cid = _add_channel(file_db, raw_data={"genre": "Action"})

        _run_backfill(file_db, cfg)
        tags_first = sorted(_tags_for(file_db, cid))

        _run_backfill(file_db, cfg)
        tags_second = sorted(_tags_for(file_db, cid))

        assert tags_first == tags_second

    def test_second_run_no_duplicate_links(self, file_db, cfg):
        """Running the backfill twice does not double the number of ContentTagDB rows."""
        cid = _add_channel(file_db, raw_data={"genre": "Comedy"})

        _run_backfill(file_db, cfg)
        count_first = _content_tag_count(file_db, cid)
        assert count_first > 0, "Expected at least one tag from the genre feeder"

        _run_backfill(file_db, cfg)
        count_second = _content_tag_count(file_db, cid)

        assert count_first == count_second


# ---------------------------------------------------------------------------
# delete_generated_for_channel (TagRepository helper)
# ---------------------------------------------------------------------------

class TestDeleteGeneratedForChannel:
    def test_only_channel_generated_tags_removed(self, file_db, cfg):
        """delete_generated_for_channel removes only the target channel's generated tags."""
        cid1 = _add_channel(file_db, category="Drama")
        cid2 = _add_channel(file_db, category="Action")

        with file_db.session_scope() as session:
            repos = RepositoryFactory(session)
            repos.tags.set_content_tags(cid1, [("genre", "Drama", "f")])
            repos.tags.set_content_tags(cid2, [("genre", "Action", "f")])

        with file_db.session_scope() as session:
            repos = RepositoryFactory(session)
            deleted = repos.tags.delete_generated_for_channel(cid1)

        assert deleted == 1
        assert _content_tag_count(file_db, cid2) == 1, "channel2 tags should be untouched"
        assert _content_tag_count(file_db, cid1) == 0

    def test_user_tags_on_channel_unaffected(self, file_db):
        """delete_generated_for_channel leaves user tags on the same channel intact."""
        cid = _add_channel(file_db)

        with file_db.session_scope() as session:
            repos = RepositoryFactory(session)
            repos.tags.set_content_tags(cid, [("genre", "Sci-Fi", "gen")], source="generated")
            repos.tags.set_content_tags(cid, [("genre", "Sci-Fi", "user")], source="user")

        with file_db.session_scope() as session:
            repos = RepositoryFactory(session)
            repos.tags.delete_generated_for_channel(cid)

        assert _content_tag_count(file_db, cid, source="generated") == 0
        assert _content_tag_count(file_db, cid, source="user") == 1


# ---------------------------------------------------------------------------
# Incremental tagging via tag_fingerprint (provider_loader._update_tags_in_thread)
# ---------------------------------------------------------------------------

class TestIncrementalTagging:
    """Behavioral tests for the skip-unchanged fingerprint logic and defer-during-migration."""

    def _run_update_tags(self, db: Database, provider_id: str, provider_name: str, cfg: Config) -> None:
        """Drive _update_tags_in_thread via a minimal ProviderLoadThread stub."""
        from unittest.mock import MagicMock
        from metatv.core.provider_loader import ProviderLoadThread

        provider = MagicMock()
        provider.id = provider_id
        provider.name = provider_name

        thread = ProviderLoadThread.__new__(ProviderLoadThread)
        thread.db = db
        thread.provider = provider
        thread._update_tags_in_thread()

    def test_unchanged_channel_skipped_on_second_run(self, file_db, cfg, monkeypatch):
        """A channel whose feeder fields have not changed is NOT re-tagged on second run.

        The tag repository's ``delete_generated_for_channel`` must NOT be called for
        the unchanged channel after the fingerprint is populated on the first run.
        """
        import metatv.core.repositories.tag as _tag_repo_module

        monkeypatch.setattr(
            "metatv.core.config.Config.load",
            staticmethod(lambda: (cfg, False)),
        )

        cid = _add_channel(file_db, category="USA", name="Test US Channel")

        # First run — populates fingerprint and tags.
        self._run_update_tags(file_db, "test_provider", "TestProvider", cfg)

        count_after_first = _content_tag_count(file_db, cid)
        assert count_after_first > 0, "Expected tags after first run"

        # Check that fingerprint was stored.
        with file_db.session_scope(commit=False) as session:
            from metatv.core.database import ChannelDB as _CDB
            ch = session.query(_CDB).filter_by(id=cid).one()
            assert ch.tag_fingerprint is not None, "fingerprint must be set after first run"
            stored_fp = ch.tag_fingerprint

        # Track delete_generated calls on second run.
        delete_calls: list[str] = []
        original_delete = _tag_repo_module.TagRepository.delete_generated_for_channel

        def _tracking_delete(self_repo, channel_id: str) -> int:
            delete_calls.append(channel_id)
            return original_delete(self_repo, channel_id)

        monkeypatch.setattr(
            _tag_repo_module.TagRepository,
            "delete_generated_for_channel",
            _tracking_delete,
        )

        # Second run — feeder fields unchanged, must skip.
        self._run_update_tags(file_db, "test_provider", "TestProvider", cfg)

        assert cid not in delete_calls, (
            "delete_generated_for_channel must NOT be called for an unchanged channel"
        )
        # Tags must still be there (not deleted).
        assert _content_tag_count(file_db, cid) == count_after_first

    def test_changed_channel_retagged_and_fingerprint_updated(self, file_db, cfg, monkeypatch):
        """A channel whose category changes IS re-tagged and its fingerprint updated."""
        monkeypatch.setattr(
            "metatv.core.config.Config.load",
            staticmethod(lambda: (cfg, False)),
        )

        cid = _add_channel(file_db, category="USA", name="Changeable Channel")

        # First run — tags and fingerprint set.
        self._run_update_tags(file_db, "test_provider", "TestProvider", cfg)

        with file_db.session_scope(commit=False) as session:
            from metatv.core.database import ChannelDB as _CDB
            ch = session.query(_CDB).filter_by(id=cid).one()
            fp_after_first = ch.tag_fingerprint
        assert fp_after_first is not None

        # Mutate the category field to simulate an ingestion change.
        with file_db.session_scope() as session:
            from metatv.core.database import ChannelDB as _CDB
            ch = session.query(_CDB).filter_by(id=cid).one()
            ch.category = "UK"   # different value → different fingerprint

        # Second run — changed feeder field must trigger re-tag.
        self._run_update_tags(file_db, "test_provider", "TestProvider", cfg)

        with file_db.session_scope(commit=False) as session:
            from metatv.core.database import ChannelDB as _CDB
            ch = session.query(_CDB).filter_by(id=cid).one()
            fp_after_second = ch.tag_fingerprint

        assert fp_after_second != fp_after_first, "fingerprint must be updated after field change"
        # The new tags should reflect the changed category.
        tags = _tags_for(file_db, cid)
        tag_pairs = {(t, v) for t, v, _src, _f in tags}
        # "UK" → region:UK
        assert any(t == "region" for t, v in tag_pairs), "region tag expected from new 'UK' category"

    def test_new_channel_with_null_fingerprint_is_tagged(self, file_db, cfg, monkeypatch):
        """A brand-new channel (NULL fingerprint) is tagged on first run."""
        monkeypatch.setattr(
            "metatv.core.config.Config.load",
            staticmethod(lambda: (cfg, False)),
        )

        cid = _add_channel(file_db, raw_data={"genre": "Drama"})

        # Verify fingerprint starts as NULL.
        with file_db.session_scope(commit=False) as session:
            from metatv.core.database import ChannelDB as _CDB
            ch = session.query(_CDB).filter_by(id=cid).one()
            assert ch.tag_fingerprint is None

        self._run_update_tags(file_db, "test_provider", "TestProvider", cfg)

        assert _content_tag_count(file_db, cid) > 0, "NULL-fingerprint channel must be tagged"
        tags = _tags_for(file_db, cid)
        assert any(t == "genre" and v == "Drama" for t, v, _src, _f in tags)

    def test_hook_returns_early_when_backfill_active(self, file_db, cfg, monkeypatch):
        """_update_tags_in_thread returns immediately when TagBackfillTask is running.

        No tags are written and delete_generated_for_channel is never called.
        """
        import metatv.core.migrations.tag_backfill as _tbm
        import metatv.core.repositories.tag as _tag_repo_module

        monkeypatch.setattr(
            "metatv.core.config.Config.load",
            staticmethod(lambda: (cfg, False)),
        )

        # Plant a channel with a tag so we can confirm it is not deleted.
        cid = _add_channel(file_db, category="USA")
        with file_db.session_scope() as session:
            from metatv.core.repositories import RepositoryFactory
            repos = RepositoryFactory(session)
            repos.tags.set_content_tags(cid, [("region", "US", "provider_category")], source="generated")

        count_before = _content_tag_count(file_db, cid)
        assert count_before > 0

        # Simulate a running backfill by patching is_backfill_active.
        monkeypatch.setattr(_tbm, "is_backfill_active", lambda: True)

        delete_calls: list[str] = []
        original_delete = _tag_repo_module.TagRepository.delete_generated_for_channel

        def _tracking_delete(self_repo, channel_id: str) -> int:
            delete_calls.append(channel_id)
            return original_delete(self_repo, channel_id)

        monkeypatch.setattr(
            _tag_repo_module.TagRepository,
            "delete_generated_for_channel",
            _tracking_delete,
        )

        self._run_update_tags(file_db, "test_provider", "TestProvider", cfg)

        assert delete_calls == [], "No tags must be touched when backfill is active"
        assert _content_tag_count(file_db, cid) == count_before, "Existing tags must survive"

    def test_migration_adds_tag_fingerprint_column(self, tmp_path):
        """The tag_fingerprint column is present (and readable) after create_tables.

        On an old DB that didn't have the column, the ALTER TABLE migration in
        _migrate() adds it.  This test verifies the column exists and defaults NULL.
        """
        db_file = tmp_path / "mig_test.db"
        db = Database(f"sqlite:///{db_file}")
        db.create_tables()

        try:
            with db.session_scope() as session:
                import uuid as _uuid
                from metatv.core.database import ChannelDB as _CDB
                ch = _CDB(
                    id=str(_uuid.uuid4()),
                    source_id="s1",
                    provider_id="p1",
                    name="Migration Test Channel",
                )
                session.add(ch)

            with db.session_scope(commit=False) as session:
                from metatv.core.database import ChannelDB as _CDB
                ch = session.query(_CDB).filter_by(name="Migration Test Channel").one()
                assert ch.tag_fingerprint is None, (
                    "tag_fingerprint should default NULL on a new row"
                )
        finally:
            db.close()
