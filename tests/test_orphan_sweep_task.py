"""Behavioral tests for ``OrphanSweepTask`` (DB-5).

Replaces the two ``PRAGMA user_version``-gated one-shot sweeps that used to
live in ``database.py`` (``_prune_orphaned_channels`` /
``_prune_orphaned_content_tags``, both removed) and ran at most once ever,
from ``Database.create_tables()``. The task version is idempotent: it heals
orphans whenever they exist, off the startup path, via the Migration Center.

Covers:
1. ``run()`` prunes non-engaged orphaned channels (+ dependents — metadata,
   EPG, content_tags) while favorited/queued/rated channels survive;
   ``needs_run`` flips True -> False; a second ``run()`` removes nothing more.
2. Orphaned ``content_tags`` rows (channel gone entirely) are removed; rows
   for a live channel are untouched.
3. Cancellation stops the run after the channel-prune step, before the
   content_tags pass, and ``needs_run`` stays True.

Real file-backed ``Database`` on ``tmp_path`` per project policy — never
``:memory:`` (pooled in-memory connections don't share schema).
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from metatv.core.database import (
    ChannelDB, ContentTagDB, Database, EpgProgramDB, MetadataDB,
    ProviderDB, TagDB, UserRatingDB, WatchQueueDB,
)
from metatv.core.migrations.orphan_sweep import OrphanSweepTask


# ── Fixtures & seed helpers ──────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path):
    """Real file-backed Database with tables created."""
    p = tmp_path / "orphan_sweep_test.db"
    database = Database(f"sqlite:///{p}")
    database.create_tables()
    yield database
    database.close()


def _provider(session, pid: str) -> ProviderDB:
    p = ProviderDB(
        id=pid, name=f"Provider {pid}", type="xtream",
        url="http://example.com", username="u", password="p",
    )
    session.add(p)
    session.flush()
    return p


def _channel(session, provider_id: str, cid: str, *, metadata_id: str = None) -> ChannelDB:
    ch = ChannelDB(
        id=cid, source_id=cid, provider_id=provider_id,
        name=f"Chan {cid}", media_type="live", metadata_id=metadata_id,
    )
    session.add(ch)
    session.flush()
    return ch


def _metadata(session, meta_id: str) -> MetadataDB:
    m = MetadataDB(id=meta_id, title="Test Metadata")
    session.add(m)
    session.flush()
    return m


def _epg(session, channel_id: str, provider_id: str) -> EpgProgramDB:
    prog = EpgProgramDB(
        provider_id=provider_id, channel_epg_id="epg1", channel_db_id=channel_id,
        title="Programme", start_time=datetime(2024, 1, 1, 20, 0),
        stop_time=datetime(2024, 1, 1, 21, 0),
    )
    session.add(prog)
    session.flush()
    return prog


def _tag(session, tag_id: int = 1) -> TagDB:
    t = session.get(TagDB, tag_id)
    if t is None:
        t = TagDB(id=tag_id, type="genre", value="Action")
        session.add(t)
        session.flush()
    return t


def _content_tag(session, channel_id: str, tag_id: int = 1) -> ContentTagDB:
    ct = ContentTagDB(channel_id=channel_id, tag_id=tag_id, source="generated")
    session.add(ct)
    session.flush()
    return ct


def _orphan_provider(session, provider_id: str) -> None:
    """Delete the providers row directly, leaving its channels dangling.

    This is the exact shape a provider removal leaves behind — SQLite foreign
    keys are OFF, so a delete anywhere that doesn't route through
    ``ChannelRepository.prune_provider_content`` (a crash mid-delete, a direct
    row removal) drops the providers row without touching its channels.
    """
    session.query(ProviderDB).filter_by(id=provider_id).delete()
    session.flush()


# ── Test 1: engaged rows survive, plain rows + dependents are gone ──────────


def test_run_prunes_nonengaged_orphans_preserves_engaged(db):
    fav_id = f"ch-fav-{uuid.uuid4()}"
    queued_id = f"ch-queued-{uuid.uuid4()}"
    rated_id = f"ch-rated-{uuid.uuid4()}"
    plain_id = f"ch-plain-{uuid.uuid4()}"

    with db.session_scope() as session:
        _provider(session, "pid-a")

        _channel(session, "pid-a", fav_id)
        session.query(ChannelDB).filter_by(id=fav_id).update({"is_favorite": True})

        _channel(session, "pid-a", queued_id)
        session.add(WatchQueueDB(
            channel_id=queued_id, channel_name="Queued", media_type="movie",
            source_id="src1", position=0,
        ))

        _channel(session, "pid-a", rated_id)
        session.add(UserRatingDB(channel_id=rated_id, rating=1))

        _metadata(session, "meta-plain")
        _channel(session, "pid-a", plain_id, metadata_id="meta-plain")
        _epg(session, plain_id, "pid-a")
        _tag(session)
        _content_tag(session, plain_id)

        _orphan_provider(session, "pid-a")

    task = OrphanSweepTask(db)
    assert task.needs_run(None) is True, \
        "an orphaned non-engaged channel must make needs_run True"

    progress_calls = []
    task.run(lambda d, t: progress_calls.append((d, t)), lambda: False)

    with db.session_scope(commit=False) as session:
        assert session.query(ChannelDB).filter_by(id=fav_id).first() is not None, \
            "favourited channel must survive"
        assert session.query(ChannelDB).filter_by(id=queued_id).first() is not None, \
            "queued channel must survive"
        assert session.query(ChannelDB).filter_by(id=rated_id).first() is not None, \
            "rated channel must survive"
        assert session.query(ChannelDB).filter_by(id=plain_id).first() is None, \
            "plain (non-engaged) orphan must be pruned"
        assert session.query(MetadataDB).filter_by(id="meta-plain").first() is None, \
            "metadata linked to the pruned channel must be removed"
        assert session.query(EpgProgramDB).filter_by(channel_db_id=plain_id).count() == 0, \
            "EPG rows for the pruned channel must be removed"
        assert session.query(ContentTagDB).filter_by(channel_id=plain_id).count() == 0, \
            "content_tags for the pruned channel must be removed"

    assert progress_calls, "run() must report progress"
    assert progress_calls[-1] == (2, 2)

    assert task.needs_run(None) is False, \
        "needs_run must be False once the orphan is healed"

    with db.session_scope(commit=False) as session:
        remaining_before = session.query(ChannelDB).count()
    task.run(lambda d, t: None, lambda: False)
    with db.session_scope(commit=False) as session:
        remaining_after = session.query(ChannelDB).count()
    assert remaining_after == remaining_before, \
        "a second run() must not remove anything more"


# ── Test 2: orphaned content_tags rows are removed; live ones are not ───────


def test_run_removes_content_tags_for_missing_channels_only(db):
    live_id = f"ch-live-{uuid.uuid4()}"
    ghost_id = "ghost-channel-never-existed"

    with db.session_scope() as session:
        _provider(session, "pid-b")
        _channel(session, "pid-b", live_id)
        _tag(session)
        _content_tag(session, live_id)     # valid link — channel exists
        _content_tag(session, ghost_id)     # orphaned link — channel never existed

    assert OrphanSweepTask(db).needs_run(None) is True, \
        "an orphaned content_tags row must make needs_run True"

    OrphanSweepTask(db).run(lambda d, t: None, lambda: False)

    with db.session_scope(commit=False) as session:
        assert session.query(ContentTagDB).filter_by(channel_id=ghost_id).count() == 0, \
            "content_tags row for a missing channel must be removed"
        assert session.query(ContentTagDB).filter_by(channel_id=live_id).count() == 1, \
            "content_tags row for a live channel must be preserved"


# ── Test 3: cancellation stops after the first step ──────────────────────────


def test_cancellation_stops_after_channel_prune_needs_run_stays_true(db):
    plain_id = f"ch-plain-{uuid.uuid4()}"
    ghost_id = "ghost-channel-cancel"

    with db.session_scope() as session:
        _provider(session, "pid-c")
        _channel(session, "pid-c", plain_id)
        _tag(session)
        _content_tag(session, ghost_id)   # orphaned content_tags row
        _orphan_provider(session, "pid-c")

    task = OrphanSweepTask(db)
    assert task.needs_run(None) is True

    # is_cancelled: False on the first check (run the channel-prune step),
    # True on the second (skip the content_tags step).
    calls = {"n": 0}

    def is_cancelled() -> bool:
        calls["n"] += 1
        return calls["n"] > 1

    task.run(lambda d, t: None, is_cancelled)

    with db.session_scope(commit=False) as session:
        assert session.query(ChannelDB).filter_by(id=plain_id).first() is None, \
            "the channel-prune step must have completed before cancellation"
        assert session.query(ContentTagDB).filter_by(channel_id=ghost_id).count() == 1, \
            "the content_tags step must have been skipped by cancellation"

    assert task.needs_run(None) is True, \
        "needs_run must stay True — the content_tags orphan was never healed"
