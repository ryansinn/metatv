"""Behavioral tests for provider-delete cascade and orphan-heal migration.

Covers:
1. Cascade deletes non-engaged channels and their dependents when a provider is
   deleted via ProviderRepository.delete().
2. Engaged channels (favorited / played / queued) survive the cascade.
3. The one-time orphan-prune migration in create_tables() heals existing orphans
   while preserving engaged content.
4. Prune works correctly across more than one batch (> _PRUNE_BATCH_SIZE channels).

All tests use file-backed DBs (tmp_path) per project policy — pooled :memory:
connections each start with an empty schema and don't share user_version state.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

import pytest

from metatv.core.database import Database, ProviderDB, ChannelDB, MetadataDB
from metatv.core.database import (
    EpgProgramDB, SeasonDB, EpisodeDB,
    UserRatingDB, AlertMatchDB, WatchQueueDB,
)
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.provider import ProviderRepository
from metatv.core.repositories.channel import ChannelRepository


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def db_path(tmp_path):
    """Return a fresh file-backed Database with tables created."""
    p = tmp_path / "cascade_test.db"
    db = Database(f"sqlite:///{p}")
    db.create_tables()
    yield db
    db.close()


# ── Seed helpers ──────────────────────────────────────────────────────────────


def _provider(session, pid: str = None) -> ProviderDB:
    pid = pid or str(uuid.uuid4())
    p = ProviderDB(
        id=pid, name=f"Provider {pid}", type="xtream",
        url="http://example.com", username="u", password="p",
    )
    session.add(p)
    session.flush()
    return p


def _channel(
    session,
    provider_id: str,
    *,
    cid: str = None,
    is_favorite: bool = False,
    last_played: datetime = None,
    play_count: int = 0,
    metadata_id: str = None,
) -> ChannelDB:
    cid = cid or str(uuid.uuid4())
    ch = ChannelDB(
        id=cid,
        source_id=cid,
        provider_id=provider_id,
        name=f"Chan {cid[:8]}",
        media_type="live",
        is_favorite=is_favorite,
        last_played=last_played,
        play_count=play_count,
        metadata_id=metadata_id,
    )
    session.add(ch)
    session.flush()
    return ch


def _metadata(session, meta_id: str = None) -> MetadataDB:
    meta_id = meta_id or f"meta_{uuid.uuid4()}"
    m = MetadataDB(id=meta_id, title="Test Metadata")
    session.add(m)
    session.flush()
    return m


def _epg_by_channel(session, channel_id: str, provider_id: str) -> EpgProgramDB:
    prog = EpgProgramDB(
        provider_id=provider_id,
        channel_epg_id="ch_epg_1",
        channel_db_id=channel_id,
        title="Test Programme",
        start_time=datetime(2024, 1, 1, 20, 0),
        stop_time=datetime(2024, 1, 1, 21, 0),
    )
    session.add(prog)
    session.flush()
    return prog


def _epg_by_provider(session, provider_id: str) -> EpgProgramDB:
    prog = EpgProgramDB(
        provider_id=provider_id,
        channel_epg_id="ch_epg_feed",
        channel_db_id=None,
        title="Feed Programme",
        start_time=datetime(2024, 1, 2, 20, 0),
        stop_time=datetime(2024, 1, 2, 21, 0),
    )
    session.add(prog)
    session.flush()
    return prog


def _season(session, series_id: str, provider_id: str) -> SeasonDB:
    sid = f"{series_id}_s1"
    s = SeasonDB(
        id=sid, series_id=series_id, provider_id=provider_id,
        season_number=1, name="Season 1",
    )
    session.add(s)
    session.flush()
    return s


def _episode(session, series_id: str, season_id: str, provider_id: str) -> EpisodeDB:
    eid = str(uuid.uuid4())
    e = EpisodeDB(
        id=eid, season_id=season_id, series_id=series_id,
        provider_id=provider_id,
        episode_id=eid, episode_num=1, season_num=1,
        title="Episode 1",
    )
    session.add(e)
    session.flush()
    return e


def _queue_entry(session, channel_id: str) -> WatchQueueDB:
    row = WatchQueueDB(
        channel_id=channel_id, channel_name="Queued Chan",
        media_type="movie", source_id="src1", position=0,
    )
    session.add(row)
    session.flush()
    return row


def _rating(session, channel_id: str) -> UserRatingDB:
    r = UserRatingDB(channel_id=channel_id, rating=1)
    session.add(r)
    session.flush()
    return r


def _alert_match(session, channel_id: str) -> AlertMatchDB:
    from metatv.core.database import AlertPatternDB
    # Need an alert_pattern_id — use a placeholder (no FK enforcement in SQLite)
    am = AlertMatchDB(
        id=str(uuid.uuid4()),
        alert_pattern_id="ap_test",
        channel_id=channel_id,
    )
    session.add(am)
    session.flush()
    return am


# ── Test 1: cascade deletes non-engaged content and dependents ────────────────


def test_cascade_deletes_nonengaged_and_dependents(db_path):
    """ProviderRepository.delete() removes non-engaged channels + all dependents."""
    db = db_path
    with db.session_scope() as session:
        prov = _provider(session, "pid-1")
        pid = prov.id

        # Metadata row
        meta = _metadata(session, "meta_ch1")
        # Non-engaged channel with metadata
        ch = _channel(session, pid, cid="ch-ne-1", metadata_id="meta_ch1")
        # EPG linked by channel_db_id
        _epg_by_channel(session, ch.id, pid)
        # Feed-level EPG (provider_id only, no channel_db_id)
        _epg_by_provider(session, pid)
        # Season + episode on this series channel
        season = _season(session, ch.id, pid)
        _episode(session, ch.id, season.id, pid)
        # Rating and alert match
        _rating(session, ch.id)
        _alert_match(session, ch.id)

    # Delete via ProviderRepository
    with db.session_scope() as session:
        result = ProviderRepository(session).delete("pid-1")

    assert result is True

    # Verify everything is gone
    with db.session_scope(commit=False) as session:
        assert session.query(ProviderDB).filter_by(id="pid-1").first() is None, \
            "provider row must be deleted"
        assert session.query(ChannelDB).filter_by(id="ch-ne-1").first() is None, \
            "non-engaged channel must be deleted"
        assert session.query(MetadataDB).filter_by(id="meta_ch1").first() is None, \
            "metadata linked to deleted channel must be removed"
        assert session.query(EpgProgramDB).filter_by(channel_db_id="ch-ne-1").count() == 0, \
            "EPG matched to deleted channel must be removed"
        assert session.query(EpgProgramDB).filter_by(provider_id="pid-1").count() == 0, \
            "feed-level EPG for deleted provider must be removed"
        assert session.query(SeasonDB).filter_by(provider_id="pid-1").count() == 0, \
            "seasons for deleted provider must be removed"
        assert session.query(EpisodeDB).filter_by(provider_id="pid-1").count() == 0, \
            "episodes for deleted provider must be removed"
        assert session.query(UserRatingDB).filter_by(channel_id="ch-ne-1").count() == 0, \
            "user rating for deleted channel must be removed"
        assert session.query(AlertMatchDB).filter_by(channel_id="ch-ne-1").count() == 0, \
            "alert match for deleted channel must be removed"


# ── Test 2: engaged channels survive the cascade ──────────────────────────────


def test_engaged_channels_preserved_after_provider_delete(db_path):
    """The three engagement signals each independently preserve a channel.

    Favorited, last_played-set, and queued channels survive provider deletion.
    Non-engaged channels on the same provider are removed.
    The engaged orphans are then hidden by get_hidden_provider_ids() but still
    appear in get_favorites_dto() and the watch queue.
    """
    db = db_path
    ch_fav_id = str(uuid.uuid4())
    ch_watched_id = str(uuid.uuid4())
    ch_queued_id = str(uuid.uuid4())
    ch_ne_id = str(uuid.uuid4())

    with db.session_scope() as session:
        _provider(session, "pid-eng")

        # Engaged: favorited
        _channel(session, "pid-eng", cid=ch_fav_id, is_favorite=True)
        # Engaged: played
        _channel(session, "pid-eng", cid=ch_watched_id, last_played=datetime(2024, 6, 1))
        # Engaged: queued (play_count=0, not favorited, last_played=None)
        ch_q = _channel(session, "pid-eng", cid=ch_queued_id)
        _queue_entry(session, ch_q.id)
        # Non-engaged
        _channel(session, "pid-eng", cid=ch_ne_id)

    # Delete the provider
    with db.session_scope() as session:
        ProviderRepository(session).delete("pid-eng")

    # Assert engaged channels still exist; non-engaged is gone
    with db.session_scope(commit=False) as session:
        assert session.query(ChannelDB).filter_by(id=ch_fav_id).first() is not None, \
            "favorited channel must survive provider deletion"
        assert session.query(ChannelDB).filter_by(id=ch_watched_id).first() is not None, \
            "played channel must survive provider deletion"
        assert session.query(ChannelDB).filter_by(id=ch_queued_id).first() is not None, \
            "queued channel must survive provider deletion"
        assert session.query(ChannelDB).filter_by(id=ch_ne_id).first() is None, \
            "non-engaged channel must be deleted"

        # Engaged channels are orphaned — provider row is gone
        # get_hidden_provider_ids() must include "pid-eng" (orphan detection)
        hidden = set(ProviderRepository(session).get_hidden_provider_ids())
        assert "pid-eng" in hidden, \
            "orphaned provider_id must appear in hidden set so engaged channels are scoped out"

        # But get_favorites_dto still returns the favorited channel (engaged exception)
        fav_dtos = ChannelRepository(session).get_favorites_dto(hidden_provider_ids=hidden)
        fav_ids = {d.id for d in fav_dtos}
        assert ch_fav_id in fav_ids, \
            "favorited channel must still appear in get_favorites_dto"
        # The favorite DTO annotates it as unavailable (provider gone)
        fav_dto = next(d for d in fav_dtos if d.id == ch_fav_id)
        assert fav_dto.available is False, \
            "favorited channel on deleted provider must be annotated unavailable"

        # Watch queue entry still resolves
        from metatv.core.repositories.queue import WatchQueueRepository
        queue_entries = WatchQueueRepository(session).get_all(hidden_provider_ids=hidden)
        queued_ids = {e.channel_id for e in queue_entries}
        assert ch_queued_id in queued_ids, \
            "queued channel must still appear in the watch queue"
        queued_entry = next(e for e in queue_entries if e.channel_id == ch_queued_id)
        assert queued_entry.available is False, \
            "queued channel on deleted provider must be annotated unavailable"


# ── Test 3: one-time migration heals existing orphans ────────────────────────


def test_one_time_migration_heals_existing_orphans(tmp_path):
    """create_tables() prunes existing orphans on first run; idempotent on second run."""
    db_file = tmp_path / "heal_test.db"

    # --- Build a raw DB with orphaned channels (no providers row) ---
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from metatv.core.database import Base

    raw_engine = create_engine(f"sqlite:///{db_file}", echo=False,
                                connect_args={"check_same_thread": False})
    Base.metadata.create_all(raw_engine)
    RawSession = sessionmaker(bind=raw_engine)

    orphaned_ne_id = str(uuid.uuid4())
    orphaned_engaged_id = str(uuid.uuid4())

    with RawSession() as s:
        # Orphaned non-engaged channel (provider_id "p-gone" has no providers row)
        s.add(ChannelDB(
            id=orphaned_ne_id, source_id=orphaned_ne_id,
            provider_id="p-gone", name="Orphan NE", media_type="live",
        ))
        # Orphaned engaged channel (favorited)
        s.add(ChannelDB(
            id=orphaned_engaged_id, source_id=orphaned_engaged_id,
            provider_id="p-gone", name="Orphan Engaged", media_type="movie",
            is_favorite=True,
        ))
        s.commit()

    raw_engine.dispose()

    # --- Run create_tables() — triggers orphan prune migration ---
    db = Database(f"sqlite:///{db_file}")
    db.create_tables()

    # Non-engaged orphan is gone; engaged orphan survives
    with db.session_scope(commit=False) as session:
        assert session.query(ChannelDB).filter_by(id=orphaned_ne_id).first() is None, \
            "non-engaged orphan must be pruned by the one-time migration"
        assert session.query(ChannelDB).filter_by(id=orphaned_engaged_id).first() is not None, \
            "engaged (favorited) orphan must be preserved by the migration"

    db.close()

    # --- Second create_tables() call: idempotent — no error, no double-delete ---
    db2 = Database(f"sqlite:///{db_file}")
    db2.create_tables()  # must not raise; user_version=2 gates the migration

    with db2.session_scope(commit=False) as session:
        # Engaged orphan still present after second run
        assert session.query(ChannelDB).filter_by(id=orphaned_engaged_id).first() is not None, \
            "engaged orphan must still exist after second create_tables() call"

    db2.close()


# ── Test 4: large prune (> one batch) ────────────────────────────────────────


def test_large_prune_works_across_batches(db_path):
    """prune_provider_content handles > _PRUNE_BATCH_SIZE channels without error."""
    db = db_path
    from metatv.core.repositories.channel import ChannelRepository

    batch_size = ChannelRepository._PRUNE_BATCH_SIZE
    n_doomed = batch_size + 200   # spans two batches
    n_engaged = 5                 # a handful of engaged ones

    pid = "pid-large"
    with db.session_scope() as session:
        _provider(session, pid)
        for i in range(n_doomed):
            session.add(ChannelDB(
                id=f"ch-ne-{i}",
                source_id=f"src-{i}",
                provider_id=pid,
                name=f"NE Channel {i}",
                media_type="live",
            ))
        for i in range(n_engaged):
            session.add(ChannelDB(
                id=f"ch-eng-{i}",
                source_id=f"src-eng-{i}",
                provider_id=pid,
                name=f"Engaged Channel {i}",
                media_type="live",
                is_favorite=True,
            ))

    with db.session_scope() as session:
        counts = ChannelRepository(session).prune_provider_content([pid])

    assert counts["channels"] == n_doomed, \
        f"expected {n_doomed} channels pruned, got {counts['channels']}"

    with db.session_scope(commit=False) as session:
        remaining = session.query(ChannelDB).filter_by(provider_id=pid).count()
        assert remaining == n_engaged, \
            f"only the {n_engaged} engaged channels must remain; found {remaining}"


# ── Test 5: delete returns False for nonexistent provider ────────────────────


def test_delete_nonexistent_provider_returns_false(db_path):
    """ProviderRepository.delete() returns False for a provider_id that does not exist."""
    db = db_path
    with db.session_scope() as session:
        result = ProviderRepository(session).delete("no-such-provider")
    assert result is False
