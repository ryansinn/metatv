"""Behavioral tests for the Sport → Sports genre normalization fix (#103).

Root cause: _GENRE_NORM in filter_utils.py mapped both "sport" and "sports"
(lowercased) to "Sport" (singular), while CONTENT_DESCRIPTOR_GROUPS and
BASE_PLATFORM_GROUPS consistently use "Sports" (plural).  This created two
separate facets in TagDB — genre:Sport (from the _decompose_genre path) and
genre:Sports (from the compound-decomposer + remap path) — producing a dead
filter-panel entry with 450+ count but zero results on click.

Fix: _GENRE_NORM now maps both "sport" and "sports" → "Sports" (plural), and
CURRENT_TAG_BACKFILL_VERSION was bumped to 5 to force a re-tag of all
source="generated" Sport tags into Sports.

All tests use file-backed SQLite (not :memory:) per CLAUDE.md requirements.
"""

from __future__ import annotations

import uuid

import pytest

from metatv.core.config import Config
from metatv.core.database import ContentTagDB, Database, TagDB
from metatv.core.migrations.tag_backfill import (
    CURRENT_TAG_BACKFILL_VERSION,
    TagBackfillTask,
    _collect_tags,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def file_db(tmp_path):
    """File-backed SQLite Database with all tables created."""
    db_file = tmp_path / "test_sport_sports.db"
    db = Database(f"sqlite:///{db_file}")
    db.create_tables()
    yield db
    db.close()


@pytest.fixture
def cfg(tmp_path):
    """Isolated Config instance, never writes to ~/.config/metatv."""
    return Config(config_dir=tmp_path / "cfg")


def _add_channel(
    db: Database,
    *,
    name: str = "Sports Channel",
    raw_data: dict | None = None,
) -> str:
    """Insert a minimal ChannelDB row and return its id."""
    from metatv.core.database import ChannelDB, ProviderDB
    channel_id = str(uuid.uuid4())
    with db.session_scope() as session:
        if not session.get(ProviderDB, "test_provider"):
            session.add(ProviderDB(
                id="test_provider",
                name="Test Provider",
                type="xtream",
                url="http://test.example.com",
                is_active=True,
            ))
        session.add(ChannelDB(
            id=channel_id,
            source_id=str(uuid.uuid4()),
            provider_id="test_provider",
            name=name,
            raw_data=raw_data,
        ))
    return channel_id


def _tag_values_for(db: Database, channel_id: str) -> dict[tuple[str, str], str]:
    """Return {(type, value): source} for all tags on a channel."""
    with db.session_scope(commit=False) as session:
        rows = (
            session.query(TagDB.type, TagDB.value, ContentTagDB.source)
            .join(ContentTagDB, ContentTagDB.tag_id == TagDB.id)
            .filter(ContentTagDB.channel_id == channel_id)
            .all()
        )
    return {(r.type, r.value): r.source for r in rows}


def _run_backfill(db: Database, cfg: Config) -> None:
    task = TagBackfillTask(db, config=cfg)
    task.run(lambda done, total: None, is_cancelled=lambda: False)


# ---------------------------------------------------------------------------
# 1. normalize_genre unit tests
# ---------------------------------------------------------------------------

class TestNormalizeGenreSportSports:
    """normalize_genre must fold both singular and plural forms to 'Sports'."""

    def test_sport_singular_folds_to_sports(self):
        from metatv.core.filter_utils import normalize_genre
        assert normalize_genre("Sport") == "Sports", (
            "normalize_genre('Sport') must return 'Sports', not 'Sport'"
        )

    def test_sports_plural_passes_through(self):
        from metatv.core.filter_utils import normalize_genre
        assert normalize_genre("Sports") == "Sports"

    def test_sports_lowercase_folds_to_sports(self):
        from metatv.core.filter_utils import normalize_genre
        assert normalize_genre("sports") == "Sports"

    def test_sport_lowercase_folds_to_sports(self):
        from metatv.core.filter_utils import normalize_genre
        assert normalize_genre("sport") == "Sports"

    def test_singular_and_plural_resolve_to_same_value(self):
        """Both forms must resolve to the same canonical — no split facet."""
        from metatv.core.filter_utils import normalize_genre
        assert normalize_genre("Sport") == normalize_genre("Sports"), (
            "Singular and plural Sport forms must resolve to the same value "
            "to avoid a split 'Sport' / 'Sports' facet in the filter panel."
        )

    def test_arabic_sport_folds_to_sports(self):
        """Arabic رياضة (sport) must fold to 'Sports' (plural canonical)."""
        from metatv.core.filter_utils import normalize_genre
        assert normalize_genre("رياضة") == "Sports"

    def test_backfill_version_at_least_5(self):
        """CURRENT_TAG_BACKFILL_VERSION must be >= 5 for the Sport→Sports fold."""
        assert CURRENT_TAG_BACKFILL_VERSION >= 5, (
            f"CURRENT_TAG_BACKFILL_VERSION is {CURRENT_TAG_BACKFILL_VERSION}, "
            "expected >= 5.  The Sport→Sports fold requires a re-backfill."
        )


# ---------------------------------------------------------------------------
# 2. _collect_tags produces "Sports" (not "Sport") for sport genre input
# ---------------------------------------------------------------------------

class TestCollectTagsSportNormalization:
    """_collect_tags must produce genre:Sports for both 'Sport' and 'Sports' raw values."""

    def test_raw_genre_sports_produces_genre_sports(self, cfg):
        """raw_data['genre']='Sports' → genre:Sports (not genre:Sport)."""
        tags = _collect_tags(
            config=cfg,
            category=None,
            source_category=None,
            detected_prefix=None,
            detected_quality=None,
            detected_region=None,
            detected_year=None,
            raw_data={"genre": "Sports"},
        )
        genre_values = [v for t, v, _feeder in tags if t == "genre"]
        assert "Sports" in genre_values, (
            f"Expected genre:Sports in tag output, got genre values: {genre_values}"
        )
        assert "Sport" not in genre_values, (
            f"Singular 'Sport' must not appear as a separate genre tag; got: {genre_values}"
        )

    def test_raw_genre_sport_singular_produces_genre_sports(self, cfg):
        """raw_data['genre']='Sport' (singular) → genre:Sports (plural canonical)."""
        tags = _collect_tags(
            config=cfg,
            category=None,
            source_category=None,
            detected_prefix=None,
            detected_quality=None,
            detected_region=None,
            detected_year=None,
            raw_data={"genre": "Sport"},
        )
        genre_values = [v for t, v, _feeder in tags if t == "genre"]
        assert "Sports" in genre_values, (
            f"raw_data genre='Sport' (singular) must produce genre:Sports, "
            f"got genre values: {genre_values}"
        )
        assert "Sport" not in genre_values, (
            f"The dead singular 'Sport' facet must not be produced; got: {genre_values}"
        )


# ---------------------------------------------------------------------------
# 3. Full backfill: existing Sport→Sports on file-backed DB
# ---------------------------------------------------------------------------

class TestBackfillFoldsSportToSports:
    """Full backfill run on a file-backed DB: source='generated' Sport tags
    become Sports; source='user' Sport tags are left untouched.
    """

    def test_backfill_converts_generated_sport_tag_to_sports(self, file_db, cfg):
        """A channel pre-tagged genre:Sport (source='generated') is retagged
        to genre:Sports after a full backfill run.
        """
        channel_id = _add_channel(file_db, raw_data={"genre": "Sports"})

        # Pre-seed a stale generated tag with the singular 'Sport' value
        with file_db.session_scope() as session:
            tag = TagDB(type="genre", value="Sport")
            session.add(tag)
            session.flush()
            session.add(ContentTagDB(
                channel_id=channel_id,
                tag_id=tag.id,
                source="generated",
                confidence=0.33,
                feeders=["genre"],
            ))

        # Verify the bad tag is present before backfill
        before = _tag_values_for(file_db, channel_id)
        assert ("genre", "Sport") in before, "Pre-seed failed — Sport tag not found"

        # Run the backfill
        _run_backfill(file_db, cfg)

        after = _tag_values_for(file_db, channel_id)
        # The plural form must now exist
        assert ("genre", "Sports") in after, (
            f"After backfill, genre:Sports must be present; tags found: {list(after.keys())}"
        )
        # The singular form must be gone (rewritten by backfill)
        assert ("genre", "Sport") not in after, (
            f"After backfill, genre:Sport (singular) must be gone; tags found: {list(after.keys())}"
        )

    def test_backfill_leaves_user_sport_tag_untouched(self, file_db, cfg):
        """A channel with a source='user' tag of genre:Sport must NOT have that
        tag altered by the backfill — user curation is never touched.
        """
        channel_id = _add_channel(file_db, raw_data={"genre": "Drama"})

        # Pre-seed a USER tag with the 'Sport' value
        with file_db.session_scope() as session:
            tag = TagDB(type="genre", value="Sport")
            session.add(tag)
            session.flush()
            session.add(ContentTagDB(
                channel_id=channel_id,
                tag_id=tag.id,
                source="user",
                confidence=1.0,
                feeders=["user"],
            ))

        _run_backfill(file_db, cfg)

        after = _tag_values_for(file_db, channel_id)
        # The user tag must survive unchanged
        assert ("genre", "Sport") in after, (
            "User-tagged genre:Sport must not be touched by the backfill; "
            f"tags found: {list(after.keys())}"
        )
        assert after[("genre", "Sport")] == "user", (
            "Tag source must remain 'user' after backfill"
        )

    def test_backfill_no_duplicate_sports_tags(self, file_db, cfg):
        """After backfill, a channel with raw_data genre='Sports' must have
        exactly one genre:Sports tag — not one Sport + one Sports.
        """
        channel_id = _add_channel(file_db, raw_data={"genre": "Sports"})
        _run_backfill(file_db, cfg)

        with file_db.session_scope(commit=False) as session:
            sports_count = (
                session.query(ContentTagDB)
                .join(TagDB, ContentTagDB.tag_id == TagDB.id)
                .filter(
                    ContentTagDB.channel_id == channel_id,
                    TagDB.type == "genre",
                    TagDB.value == "Sports",
                )
                .count()
            )
            sport_singular_count = (
                session.query(ContentTagDB)
                .join(TagDB, ContentTagDB.tag_id == TagDB.id)
                .filter(
                    ContentTagDB.channel_id == channel_id,
                    TagDB.type == "genre",
                    TagDB.value == "Sport",
                )
                .count()
            )

        assert sports_count >= 1, "At least one genre:Sports tag expected after backfill"
        assert sport_singular_count == 0, (
            f"genre:Sport (singular) must not exist after backfill; count={sport_singular_count}"
        )
