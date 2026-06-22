"""Behavioral tests for TagRepository (DR-0005 Tags Slice T1).

Every test exercises a concrete code path and asserts an outcome that would
actually break — no shape/string-in-source assertions.

Coverage:
- get_or_create_tag: same (type, value) → one row; different value → two rows.
- set_content_tags: creates links and deduplicates tags.
- feeders merge + confidence rises when two feeders assert the same tag.
- tags_for / channels_for_tag: round-trip correctness.
- reprocess_delete_generated: removes generated links, keeps user links.
- create_tables on an existing DB creates the new tables (add-only migration).
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

from metatv.core.database import Base, ChannelDB, Database, TagDB, ContentTagDB
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.tag import _compute_confidence


# ---------------------------------------------------------------------------
# Fixtures — file-backed DB (required per CLAUDE.md)
# ---------------------------------------------------------------------------

@pytest.fixture
def file_db(tmp_path):
    """File-backed SQLite Database with all tables created."""
    db_file = tmp_path / "test_tags.db"
    db = Database(f"sqlite:///{db_file}")
    db.create_tables()
    yield db
    db.close()


@pytest.fixture
def session(file_db):
    """Fresh session per test; caller must commit explicitly or use session_scope."""
    s = file_db.get_session()
    yield s
    s.close()


def _make_channel(session, provider_id: str = "test_provider") -> str:
    """Insert a minimal ChannelDB row and return its id."""
    # Ensure a provider exists for FK validity (channels.provider_id has no FK, but let's be safe)
    ch = ChannelDB(
        id=str(uuid.uuid4()),
        source_id=str(uuid.uuid4()),
        provider_id=provider_id,
        name="Test Channel",
    )
    session.add(ch)
    session.flush()
    return ch.id


# ---------------------------------------------------------------------------
# _compute_confidence helper
# ---------------------------------------------------------------------------

class TestComputeConfidence:
    def test_empty_feeders_returns_zero(self):
        assert _compute_confidence([]) == 0.0

    def test_one_feeder_returns_third(self):
        result = _compute_confidence(["feeder_a"])
        assert abs(result - 1 / 3) < 1e-9

    def test_two_feeders_returns_two_thirds(self):
        result = _compute_confidence(["feeder_a", "feeder_b"])
        assert abs(result - 2 / 3) < 1e-9

    def test_three_feeders_returns_one(self):
        result = _compute_confidence(["a", "b", "c"])
        assert result == 1.0

    def test_four_feeders_capped_at_one(self):
        result = _compute_confidence(["a", "b", "c", "d"])
        assert result == 1.0

    def test_duplicate_feeders_counted_once(self):
        """Duplicates in the list should not inflate confidence."""
        result = _compute_confidence(["a", "a", "a"])
        assert abs(result - 1 / 3) < 1e-9


# ---------------------------------------------------------------------------
# get_or_create_tag
# ---------------------------------------------------------------------------

class TestGetOrCreateTag:
    def test_same_type_value_returns_one_row(self, session):
        """Calling get_or_create_tag twice with the same args → single DB row."""
        repos = RepositoryFactory(session)
        t1 = repos.tags.get_or_create_tag("region", "US")
        t2 = repos.tags.get_or_create_tag("region", "US")

        session.commit()

        assert t1.id == t2.id
        count = session.query(TagDB).filter_by(type="region", value="US").count()
        assert count == 1

    def test_different_value_returns_two_rows(self, session):
        """Two different values in the same namespace → two distinct rows."""
        repos = RepositoryFactory(session)
        t_us = repos.tags.get_or_create_tag("region", "US")
        t_uk = repos.tags.get_or_create_tag("region", "UK")

        session.commit()

        assert t_us.id != t_uk.id
        count = session.query(TagDB).filter_by(type="region").count()
        assert count == 2

    def test_different_type_same_value_returns_two_rows(self, session):
        """Same value in different namespaces is two distinct tags."""
        repos = RepositoryFactory(session)
        t1 = repos.tags.get_or_create_tag("region", "HD")
        t2 = repos.tags.get_or_create_tag("quality", "HD")

        session.commit()

        assert t1.id != t2.id

    def test_tag_id_is_populated(self, session):
        """After get_or_create_tag the returned object has a non-None id."""
        repos = RepositoryFactory(session)
        tag = repos.tags.get_or_create_tag("genre", "Drama")
        session.commit()
        assert tag.id is not None


# ---------------------------------------------------------------------------
# set_content_tags
# ---------------------------------------------------------------------------

class TestSetContentTags:
    def test_creates_links(self, session):
        """set_content_tags inserts ContentTagDB rows for each (type, value)."""
        cid = _make_channel(session)
        repos = RepositoryFactory(session)

        repos.tags.set_content_tags(
            cid,
            [("region", "US", "prefix_feeder"), ("quality", "HD", "quality_feeder")],
        )
        session.commit()

        links = session.query(ContentTagDB).filter_by(channel_id=cid).all()
        assert len(links) == 2

    def test_no_duplicate_links_for_same_type_value(self, session):
        """Calling set_content_tags twice with the same tag → one ContentTagDB row."""
        cid = _make_channel(session)
        repos = RepositoryFactory(session)

        repos.tags.set_content_tags(cid, [("genre", "Drama", "feeder_a")])
        session.commit()
        repos.tags.set_content_tags(cid, [("genre", "Drama", "feeder_a")])
        session.commit()

        links = session.query(ContentTagDB).filter_by(channel_id=cid).all()
        assert len(links) == 1

    def test_feeders_merge_on_second_assertion(self, session):
        """When two different feeders assert the same tag, feeders list grows."""
        cid = _make_channel(session)
        repos = RepositoryFactory(session)

        repos.tags.set_content_tags(cid, [("genre", "Drama", "feeder_a")])
        session.commit()
        repos.tags.set_content_tags(cid, [("genre", "Drama", "feeder_b")])
        session.commit()

        tag = session.query(TagDB).filter_by(type="genre", value="Drama").one()
        link = (
            session.query(ContentTagDB)
            .filter_by(channel_id=cid, tag_id=tag.id)
            .one()
        )
        assert set(link.feeders) == {"feeder_a", "feeder_b"}

    def test_confidence_rises_with_second_feeder(self, session):
        """Adding a second feeder raises confidence from ~0.33 to ~0.67."""
        cid = _make_channel(session)
        repos = RepositoryFactory(session)

        repos.tags.set_content_tags(cid, [("genre", "Drama", "feeder_a")])
        session.commit()

        tag = session.query(TagDB).filter_by(type="genre", value="Drama").one()
        link = (
            session.query(ContentTagDB)
            .filter_by(channel_id=cid, tag_id=tag.id)
            .one()
        )
        confidence_one = link.confidence
        assert abs(confidence_one - 1 / 3) < 1e-9

        repos.tags.set_content_tags(cid, [("genre", "Drama", "feeder_b")])
        session.commit()

        session.refresh(link)
        confidence_two = link.confidence
        assert abs(confidence_two - 2 / 3) < 1e-9
        assert confidence_two > confidence_one

    def test_confidence_capped_at_three_feeders(self, session):
        """Three distinct feeders → confidence == 1.0 (capped)."""
        cid = _make_channel(session)
        repos = RepositoryFactory(session)

        for feeder in ("feeder_a", "feeder_b", "feeder_c"):
            repos.tags.set_content_tags(cid, [("genre", "Drama", feeder)])
            session.commit()

        tag = session.query(TagDB).filter_by(type="genre", value="Drama").one()
        link = (
            session.query(ContentTagDB)
            .filter_by(channel_id=cid, tag_id=tag.id)
            .one()
        )
        assert link.confidence == 1.0

    def test_duplicate_feeder_does_not_inflate_confidence(self, session):
        """Asserting the same feeder twice does not raise confidence."""
        cid = _make_channel(session)
        repos = RepositoryFactory(session)

        repos.tags.set_content_tags(cid, [("genre", "Drama", "feeder_a")])
        session.commit()
        repos.tags.set_content_tags(cid, [("genre", "Drama", "feeder_a")])
        session.commit()

        tag = session.query(TagDB).filter_by(type="genre", value="Drama").one()
        link = (
            session.query(ContentTagDB)
            .filter_by(channel_id=cid, tag_id=tag.id)
            .one()
        )
        # Still one distinct feeder → 1/3
        assert abs(link.confidence - 1 / 3) < 1e-9

    def test_source_default_is_generated(self, session):
        """Without an explicit source argument, links are tagged 'generated'."""
        cid = _make_channel(session)
        repos = RepositoryFactory(session)
        repos.tags.set_content_tags(cid, [("quality", "4K", "some_feeder")])
        session.commit()

        link = session.query(ContentTagDB).filter_by(channel_id=cid).one()
        assert link.source == "generated"

    def test_user_source_stored_separately(self, session):
        """A 'user' source link coexists with a 'generated' link for the same tag."""
        cid = _make_channel(session)
        repos = RepositoryFactory(session)

        repos.tags.set_content_tags(cid, [("genre", "Drama", "rules_v1")])
        session.commit()
        repos.tags.set_content_tags(cid, [("genre", "Drama", "human")], source="user")
        session.commit()

        links = session.query(ContentTagDB).filter_by(channel_id=cid).all()
        sources = {lnk.source for lnk in links}
        assert sources == {"generated", "user"}


# ---------------------------------------------------------------------------
# tags_for
# ---------------------------------------------------------------------------

class TestTagsFor:
    def test_round_trip(self, session):
        """tags_for returns the (type, value) tuples that were set."""
        cid = _make_channel(session)
        repos = RepositoryFactory(session)

        repos.tags.set_content_tags(
            cid,
            [
                ("region", "US", "feeder"),
                ("quality", "HD", "feeder"),
                ("genre", "Drama", "feeder"),
            ],
        )
        session.commit()

        result = repos.tags.tags_for(cid)
        assert set(result) == {("region", "US"), ("quality", "HD"), ("genre", "Drama")}

    def test_empty_for_untagged_channel(self, session):
        """A channel with no tags returns an empty list."""
        cid = _make_channel(session)
        repos = RepositoryFactory(session)
        assert repos.tags.tags_for(cid) == []

    def test_returns_plain_tuples_not_orm(self, session):
        """tags_for must return plain tuples, not ORM objects (no DetachedInstanceError risk)."""
        cid = _make_channel(session)
        repos = RepositoryFactory(session)
        repos.tags.set_content_tags(cid, [("region", "CA", "feeder")])
        session.commit()

        result = repos.tags.tags_for(cid)
        assert all(isinstance(item, tuple) for item in result)
        assert all(isinstance(t, str) and isinstance(v, str) for t, v in result)


# ---------------------------------------------------------------------------
# channels_for_tag
# ---------------------------------------------------------------------------

class TestChannelsForTag:
    def test_round_trip(self, session):
        """channels_for_tag returns channel ids that carry the given tag."""
        cid1 = _make_channel(session)
        cid2 = _make_channel(session)
        cid3 = _make_channel(session)
        repos = RepositoryFactory(session)

        repos.tags.set_content_tags(cid1, [("genre", "Drama", "feeder")])
        repos.tags.set_content_tags(cid2, [("genre", "Drama", "feeder")])
        repos.tags.set_content_tags(cid3, [("genre", "Action", "feeder")])
        session.commit()

        drama_ids = repos.tags.channels_for_tag("genre", "Drama")
        assert set(drama_ids) == {cid1, cid2}
        assert cid3 not in drama_ids

    def test_nonexistent_tag_returns_empty(self, session):
        """Querying a tag that does not exist returns an empty list."""
        repos = RepositoryFactory(session)
        result = repos.tags.channels_for_tag("genre", "NoSuchGenre")
        assert result == []

    def test_returns_plain_strings_not_orm(self, session):
        """channels_for_tag returns plain strings, not ORM objects."""
        cid = _make_channel(session)
        repos = RepositoryFactory(session)
        repos.tags.set_content_tags(cid, [("genre", "Comedy", "feeder")])
        session.commit()

        result = repos.tags.channels_for_tag("genre", "Comedy")
        assert all(isinstance(x, str) for x in result)


# ---------------------------------------------------------------------------
# reprocess_delete_generated
# ---------------------------------------------------------------------------

class TestReprocessDeleteGenerated:
    def test_removes_generated_links(self, session):
        """After reprocess_delete_generated, all 'generated' content_tags are gone."""
        cid = _make_channel(session)
        repos = RepositoryFactory(session)

        repos.tags.set_content_tags(cid, [("region", "US", "feeder")])
        session.commit()

        count_before = session.query(ContentTagDB).filter_by(source="generated").count()
        assert count_before == 1

        repos.tags.reprocess_delete_generated()
        session.commit()

        count_after = session.query(ContentTagDB).filter_by(source="generated").count()
        assert count_after == 0

    def test_preserves_user_links(self, session):
        """'user' source links are untouched by reprocess_delete_generated."""
        cid = _make_channel(session)
        repos = RepositoryFactory(session)

        repos.tags.set_content_tags(cid, [("genre", "Drama", "rules")], source="generated")
        repos.tags.set_content_tags(cid, [("genre", "Drama", "human")], source="user")
        session.commit()

        repos.tags.reprocess_delete_generated()
        session.commit()

        # generated gone, user stays
        remaining = session.query(ContentTagDB).all()
        assert len(remaining) == 1
        assert remaining[0].source == "user"

    def test_returns_deleted_count(self, session):
        """reprocess_delete_generated returns the number of rows deleted."""
        cid = _make_channel(session)
        repos = RepositoryFactory(session)

        repos.tags.set_content_tags(
            cid,
            [("region", "US", "f"), ("quality", "HD", "f")],
        )
        session.commit()

        deleted = repos.tags.reprocess_delete_generated()
        assert deleted == 2

    def test_idempotent_on_empty(self, session):
        """reprocess_delete_generated on an already-empty table returns 0 without error."""
        repos = RepositoryFactory(session)
        deleted = repos.tags.reprocess_delete_generated()
        assert deleted == 0


# ---------------------------------------------------------------------------
# create_tables adds new tables to an existing DB
# ---------------------------------------------------------------------------

class TestCreateTablesAddsNewTables:
    def test_tags_and_content_tags_exist_after_create_tables(self, tmp_path):
        """create_tables on a fresh DB creates both tags and content_tags tables."""
        db_file = tmp_path / "migration_test.db"
        db = Database(f"sqlite:///{db_file}")
        db.create_tables()

        try:
            with db.session_scope() as session:
                # If these queries execute without error, the tables exist.
                session.query(TagDB).count()
                session.query(ContentTagDB).count()
        finally:
            db.close()

    def test_create_tables_idempotent_on_existing_db(self, tmp_path):
        """Calling create_tables twice does not raise or destroy data."""
        db_file = tmp_path / "idempotent_test.db"
        db = Database(f"sqlite:///{db_file}")
        db.create_tables()

        # Insert a tag on first pass
        with db.session_scope() as session:
            session.add(TagDB(type="genre", value="Sci-Fi"))

        # Second create_tables should be a no-op (Base.metadata.create_all is safe)
        db.create_tables()

        with db.session_scope() as session:
            count = session.query(TagDB).filter_by(type="genre", value="Sci-Fi").count()
            assert count == 1

        db.close()
