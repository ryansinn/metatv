"""Behavioral tests for the per-refresh content-tag hook in ProviderLoadThread.

Every source refresh must recompute ``content_tags`` for its channels via the
decomposer — not just when the one-time ``TagBackfillTask`` migration runs.

Coverage
--------
- The shared ``_collect_tags`` helper (imported from ``tag_backfill``) is the
  same function used by both T3 and the loader hook — one source, no duplication.
- Calling ``_update_tags_in_thread`` on a file-backed DB seeds the expected
  ``content_tags`` rows for channels belonging to the provider.
- The step is memory-safe: it fetches IDs first, then queries only the eight
  feeder columns per batch — never ``.all()`` over full ORM objects.
- A second call to ``_update_tags_in_thread`` is idempotent: same tag set, no
  duplicate ``ContentTagDB`` rows.
- Channels from OTHER providers are not re-tagged (provider-scoped).
- User tags (``source="user"``) survive the hook (non-destructive contract
  identical to the backfill).
- The progress message "Computing content tags…" at pct=93 keeps ``_STEP_PARSE``
  active (not all-done) so the step-checklist UI advances correctly.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from metatv.core.config import Config
from metatv.core.database import ChannelDB, ContentTagDB, Database, TagDB
from metatv.core.migrations.tag_backfill import _collect_tags
from metatv.core.repositories import RepositoryFactory


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def file_db(tmp_path):
    """File-backed SQLite Database with all tables created."""
    db_file = tmp_path / "per_refresh_tags.db"
    db = Database(f"sqlite:///{db_file}")
    db.create_tables()
    yield db
    db.close()


@pytest.fixture
def cfg(tmp_path):
    """Isolated Config instance with config_dir under tmp_path."""
    return Config(config_dir=tmp_path / "cfg")


def _make_provider_id() -> str:
    return f"prov_{uuid.uuid4().hex[:8]}"


def _add_channel(
    db: Database,
    *,
    provider_id: str,
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
            provider_id=provider_id,
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


def _content_tag_rows(
    db: Database, channel_id: str, source: str = "generated"
) -> list[tuple[str, str, list[str]]]:
    """Return ``(type, value, feeders)`` for all content_tags on a channel."""
    with db.session_scope(commit=False) as session:
        rows = (
            session.query(TagDB.type, TagDB.value, ContentTagDB.feeders)
            .join(ContentTagDB, ContentTagDB.tag_id == TagDB.id)
            .filter(
                ContentTagDB.channel_id == channel_id,
                ContentTagDB.source == source,
            )
            .all()
        )
    return [(r.type, r.value, list(r.feeders or [])) for r in rows]


def _content_tag_count(
    db: Database, channel_id: str, source: str = "generated"
) -> int:
    with db.session_scope(commit=False) as session:
        return (
            session.query(ContentTagDB)
            .filter_by(channel_id=channel_id, source=source)
            .count()
        )


def _run_tag_hook(db: Database, provider_id: str, cfg: Config) -> None:
    """Invoke ``_update_tags_in_thread`` directly on a minimal ProviderLoadThread.

    We construct the thread without QThread overhead (no ``run()``), then call
    the private worker method directly — the same way other loader tests work.
    The method only needs ``self.db`` and ``self.provider.id`` / ``self.provider.name``.
    """
    from metatv.core.provider_loader import ProviderLoadThread

    provider = SimpleNamespace(id=provider_id, name="TestProvider")
    thread = ProviderLoadThread.__new__(ProviderLoadThread)
    thread.db = db
    thread.provider = provider

    # Patch Config.load() so the worker uses our isolated config instance.
    # Config is imported inside the method body, so we patch its canonical location.
    # NOTE: Config.load() returns a (Config, migrated_bool) TUPLE — the mock MUST
    # mirror that shape, or it masks the real "config is a tuple" crash in the hook.
    with patch("metatv.core.config.Config.load", return_value=(cfg, False)):
        thread._update_tags_in_thread()


# ---------------------------------------------------------------------------
# Shared helper — _collect_tags is the same object used by both T3 and hook
# ---------------------------------------------------------------------------


class TestSharedHelper:
    """Verifies that ``_collect_tags`` from ``tag_backfill`` is the single,
    importable shared helper — not a duplicate defined in provider_loader.
    """

    def test_collect_tags_is_importable_from_tag_backfill(self, cfg):
        """_collect_tags is callable from the canonical module and returns tags."""
        tags = _collect_tags(
            config=cfg,
            category=None,
            source_category=None,
            detected_prefix=None,
            detected_quality=None,
            detected_region=None,
            detected_year="2005",
            raw_data=None,
        )
        type_value_pairs = {(t, v) for t, v, _f in tags}
        assert ("decade", "2000s") in type_value_pairs, (
            "_collect_tags must return a decade tag for detected_year='2005'"
        )

    def test_provider_loader_imports_same_helper(self):
        """provider_loader._update_tags_in_thread must import _collect_tags from
        tag_backfill — not define a local copy. Verify no local definition exists.
        """
        import inspect
        import metatv.core.provider_loader as _loader_module

        src = inspect.getsource(_loader_module)
        # The import statement must reference tag_backfill._collect_tags.
        assert "from metatv.core.migrations.tag_backfill import _collect_tags" in src, (
            "provider_loader must import _collect_tags from tag_backfill, not redefine it"
        )
        # There must be no standalone def _collect_tags in the loader module.
        assert "def _collect_tags" not in src, (
            "provider_loader must NOT define a local _collect_tags — reuse the backfill helper"
        )


# ---------------------------------------------------------------------------
# Core behavior: hook populates content_tags on refresh
# ---------------------------------------------------------------------------


class TestTagHookPopulatesTags:
    def test_genre_tag_from_raw_data(self, file_db, cfg):
        """A channel with raw_data genre gets a genre content_tag after the hook runs."""
        pid = _make_provider_id()
        cid = _add_channel(file_db, provider_id=pid, raw_data={"genre": "Thriller"})

        _run_tag_hook(file_db, pid, cfg)

        rows = _content_tag_rows(file_db, cid)
        type_value_pairs = {(t, v) for t, v, _f in rows}
        assert ("genre", "Thriller") in type_value_pairs

    def test_region_tag_from_category(self, file_db, cfg):
        """A channel with category='USA' gets a region:US tag after the hook runs."""
        pid = _make_provider_id()
        cid = _add_channel(file_db, provider_id=pid, category="USA")

        _run_tag_hook(file_db, pid, cfg)

        rows = _content_tag_rows(file_db, cid)
        type_value_pairs = {(t, v) for t, v, _f in rows}
        assert ("region", "US") in type_value_pairs

    def test_decade_tag_from_detected_year(self, file_db, cfg):
        """A channel with detected_year='1998' gets a decade:1990s tag."""
        pid = _make_provider_id()
        cid = _add_channel(file_db, provider_id=pid, detected_year="1998")

        _run_tag_hook(file_db, pid, cfg)

        rows = _content_tag_rows(file_db, cid)
        type_value_pairs = {(t, v) for t, v, _f in rows}
        assert ("decade", "1990s") in type_value_pairs

    def test_all_tags_carry_generated_source(self, file_db, cfg):
        """All tags written by the hook carry source='generated'."""
        pid = _make_provider_id()
        cid = _add_channel(file_db, provider_id=pid, raw_data={"genre": "Comedy"})

        _run_tag_hook(file_db, pid, cfg)

        count = _content_tag_count(file_db, cid, source="generated")
        assert count > 0, "Hook should have written at least one generated tag"

    def test_blank_channel_no_tags(self, file_db, cfg):
        """A channel with no feeder data produces no content_tags."""
        pid = _make_provider_id()
        cid = _add_channel(file_db, provider_id=pid, name="No Data Channel")

        _run_tag_hook(file_db, pid, cfg)

        count = _content_tag_count(file_db, cid)
        assert count == 0


# ---------------------------------------------------------------------------
# Provider-scoped: channels from other providers are not re-tagged
# ---------------------------------------------------------------------------


class TestProviderScoping:
    def test_other_provider_channels_not_touched(self, file_db, cfg):
        """The hook only tags channels from the specified provider — not others."""
        pid_a = _make_provider_id()
        pid_b = _make_provider_id()

        cid_a = _add_channel(file_db, provider_id=pid_a, raw_data={"genre": "Action"})
        cid_b = _add_channel(file_db, provider_id=pid_b, raw_data={"genre": "Drama"})

        # Run only for provider A.
        _run_tag_hook(file_db, pid_a, cfg)

        count_a = _content_tag_count(file_db, cid_a)
        count_b = _content_tag_count(file_db, cid_b)

        assert count_a > 0, "Provider A's channel should have been tagged"
        assert count_b == 0, "Provider B's channel must not be tagged by provider A's refresh"


# ---------------------------------------------------------------------------
# Non-destructive: user tags survive the hook
# ---------------------------------------------------------------------------


class TestUserTagsSurvive:
    def test_user_tag_preserved_after_hook(self, file_db, cfg):
        """A source='user' content_tag is untouched by the refresh hook."""
        pid = _make_provider_id()
        cid = _add_channel(file_db, provider_id=pid, name="Minimal Channel")

        # Plant a user tag before running the hook.
        with file_db.session_scope() as session:
            repos = RepositoryFactory(session)
            repos.tags.set_content_tags(
                cid, [("genre", "SciFi", "human")], source="user"
            )

        _run_tag_hook(file_db, pid, cfg)

        user_count = _content_tag_count(file_db, cid, source="user")
        assert user_count == 1, "User tag must survive the refresh hook"

    def test_user_and_generated_coexist(self, file_db, cfg):
        """User and generated tags on the same (type, value) coexist after the hook."""
        pid = _make_provider_id()
        cid = _add_channel(file_db, provider_id=pid, raw_data={"genre": "Drama"})

        with file_db.session_scope() as session:
            repos = RepositoryFactory(session)
            repos.tags.set_content_tags(
                cid, [("genre", "Drama", "human")], source="user"
            )

        _run_tag_hook(file_db, pid, cfg)

        with file_db.session_scope(commit=False) as session:
            rows = (
                session.query(ContentTagDB.source)
                .join(TagDB, TagDB.id == ContentTagDB.tag_id)
                .filter(
                    ContentTagDB.channel_id == cid,
                    TagDB.type == "genre",
                    TagDB.value == "Drama",
                )
                .all()
            )
        sources = {r.source for r in rows}
        assert "user" in sources
        assert "generated" in sources


# ---------------------------------------------------------------------------
# Idempotency: running the hook twice produces the same result
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_second_run_same_tag_count(self, file_db, cfg):
        """Running the hook twice on the same provider produces no duplicates."""
        pid = _make_provider_id()
        cid = _add_channel(file_db, provider_id=pid, raw_data={"genre": "Action"})

        _run_tag_hook(file_db, pid, cfg)
        count_first = _content_tag_count(file_db, cid)
        assert count_first > 0, "First run should produce at least one tag"

        _run_tag_hook(file_db, pid, cfg)
        count_second = _content_tag_count(file_db, cid)

        assert count_first == count_second, (
            "Second run must not duplicate content_tag rows"
        )

    def test_second_run_same_tag_types(self, file_db, cfg):
        """Running the hook twice yields the same (type, value) tag set."""
        pid = _make_provider_id()
        cid = _add_channel(
            file_db, provider_id=pid, raw_data={"genre": "Comedy"}, category="USA"
        )

        _run_tag_hook(file_db, pid, cfg)
        rows_first = sorted(
            (t, v) for t, v, _f in _content_tag_rows(file_db, cid)
        )

        _run_tag_hook(file_db, pid, cfg)
        rows_second = sorted(
            (t, v) for t, v, _f in _content_tag_rows(file_db, cid)
        )

        assert rows_first == rows_second, (
            "Tag set must be identical after a second run (idempotent)"
        )


# ---------------------------------------------------------------------------
# Memory safety: batched ID-based queries, no full ORM materialisation
# ---------------------------------------------------------------------------


class TestMemorySafety:
    def test_many_channels_all_tagged(self, file_db, cfg):
        """With more channels than the internal batch size all get tagged correctly.

        Uses 600 channels — more than the 500-channel _TAG_BATCH so at least two
        batch iterations occur.  Asserts every channel with a genre feeder receives
        its tag, proving the batching doesn't drop channels.
        """
        _TAG_BATCH_PLUS = 600  # > _TAG_BATCH (500) to exercise multi-batch path
        pid = _make_provider_id()

        channel_ids: list[str] = []
        for i in range(_TAG_BATCH_PLUS):
            cid = _add_channel(
                file_db,
                provider_id=pid,
                name=f"Channel {i:04d}",
                raw_data={"genre": "Action"},
            )
            channel_ids.append(cid)

        _run_tag_hook(file_db, pid, cfg)

        # Every channel must have at least one generated tag.
        untagged = [
            cid
            for cid in channel_ids
            if _content_tag_count(file_db, cid) == 0
        ]
        assert untagged == [], (
            f"{len(untagged)}/{_TAG_BATCH_PLUS} channels were not tagged — "
            "batching may have dropped a chunk"
        )


# ---------------------------------------------------------------------------
# Step-checklist: new message fits the PARSE-active phase
# ---------------------------------------------------------------------------


class TestStepChecklistMessage:
    """The new 'Computing content tags…' message at pct=93 must keep
    _STEP_PARSE active (not all-done) so the UI checklist advances correctly.
    """

    def test_computing_tags_message_keeps_parse_active(self):
        from metatv.core.notifications import StepStatus
        from metatv.gui.main_window_providers import (
            _STEP_FETCH,
            _STEP_PARSE,
            _STEP_STORE,
            _advance_steps,
            _make_steps,
        )

        steps = _advance_steps(
            _make_steps(epg=False), "Computing content tags…", 93
        )
        step_map = dict(steps)
        assert step_map[_STEP_FETCH] == StepStatus.DONE
        assert step_map[_STEP_STORE] == StepStatus.DONE
        assert step_map[_STEP_PARSE] == StepStatus.ACTIVE, (
            "'Computing content tags…' must show PARSE as active, not done"
        )
