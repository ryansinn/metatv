"""Behavioral tests: Reconnect Engaged Content (Wave 4 — orphan recovery).

Guards ``ChannelRepository.get_reconnect_candidates`` (the query) and
``ChannelRepository.reconnect_engaged_content`` (the mutation) — the
constructive counterpart to ``clear_unavailable_favorites``: instead of just
un-favoriting an orphaned engaged channel, these let the user move its
engagement onto a live same-``content_key`` replacement.

Per CLAUDE.md every test uses a real ``Database`` on a ``tmp_path`` file —
never ``:memory:`` (pooled in-memory connections don't share schema /
``user_version``).
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from pathlib import Path

import pytest

from metatv.core.database import (
    Database, ProviderDB, ChannelDB, UserRatingDB, WatchQueueDB,
)
from metatv.core.repositories.channel import ChannelRepository
from metatv.core.repositories.provider import ProviderRepository


# ── Fixtures & helpers ───────────────────────────────────────────────────────


@pytest.fixture()
def db(tmp_path: Path):
    d = Database(f"sqlite:///{tmp_path / 'reconnect.db'}")
    d.create_tables()
    yield d
    d.close()


def _provider(session, pid: str, *, is_active: bool = True) -> str:
    session.add(ProviderDB(
        id=pid, name=f"Provider {pid}", type="xtream",
        url="http://example.com", username="u", password="p",
        is_active=is_active,
    ))
    session.flush()
    return pid


def _channel(
    session,
    provider_id: str,
    *,
    cid: str,
    name: str | None = None,
    media_type: str = "movie",
    content_key: str | None = None,
    detected_quality: str | None = None,
    is_favorite: bool = False,
    last_played: datetime | None = None,
    play_count: int = 0,
    watch_progress: int = 0,
    watch_completed: bool = False,
    watch_percent: int = 0,
    last_played_via: str | None = None,
    is_hidden: bool = False,
) -> str:
    session.add(ChannelDB(
        id=cid, source_id=cid, provider_id=provider_id,
        name=name or f"Chan {cid}", media_type=media_type,
        content_key=content_key, detected_quality=detected_quality,
        is_favorite=is_favorite, last_played=last_played, play_count=play_count,
        watch_progress=watch_progress, watch_completed=watch_completed,
        watch_percent=watch_percent, last_played_via=last_played_via,
        is_hidden=is_hidden,
    ))
    session.flush()
    return cid


def _hidden_ids(session) -> set:
    return set(ProviderRepository(session).get_hidden_provider_ids())


# ── get_reconnect_candidates ─────────────────────────────────────────────────


def test_orphaned_favorite_finds_live_same_content_key_match(db):
    """An orphaned favorited channel whose provider is hidden proposes the live
    channel sharing its content_key on a still-active provider."""
    pid_dead, pid_live = "p-dead1", "p-live1"
    key = "movie:reconnect one|movie|2020"
    with db.session_scope() as session:
        _provider(session, pid_dead, is_active=False)
        _provider(session, pid_live, is_active=True)
        _channel(session, pid_dead, cid="orphan1", content_key=key, is_favorite=True)
        _channel(session, pid_live, cid="live1", content_key=key, detected_quality="HD")

    with db.session_scope(commit=False) as session:
        hidden = _hidden_ids(session)
        candidates = ChannelRepository(session).get_reconnect_candidates(hidden)

    assert len(candidates) == 1
    assert candidates[0].orphan_id == "orphan1"
    assert candidates[0].is_favorite is True
    assert candidates[0].match is not None
    assert candidates[0].match.channel_id == "live1"


def test_active_provider_channel_not_listed_as_orphan(db):
    """A favorited channel on a still-ACTIVE provider must never appear as an
    orphan candidate — only channels on a hidden provider qualify."""
    pid_active, pid_dead = "p-active2", "p-dead2"
    with db.session_scope() as session:
        _provider(session, pid_active, is_active=True)
        _provider(session, pid_dead, is_active=False)
        _channel(session, pid_active, cid="active-fav", content_key="k1", is_favorite=True)
        _channel(session, pid_dead, cid="orphan-fav", content_key="k2", is_favorite=True)

    with db.session_scope(commit=False) as session:
        hidden = _hidden_ids(session)
        candidates = ChannelRepository(session).get_reconnect_candidates(hidden)

    ids = {c.orphan_id for c in candidates}
    assert "orphan-fav" in ids
    assert "active-fav" not in ids


def test_null_content_key_yields_no_match_not_a_fuzzy_one(db):
    """A NULL content_key must never match by title heuristic, even when a
    live channel shares the exact same name."""
    pid_dead, pid_live = "p-dead3", "p-live3"
    with db.session_scope() as session:
        _provider(session, pid_dead, is_active=False)
        _provider(session, pid_live, is_active=True)
        _channel(session, pid_dead, cid="orphan3", name="Same Title",
                  content_key=None, is_favorite=True)
        _channel(session, pid_live, cid="live3", name="Same Title",
                  content_key="some:key|movie|2020")

    with db.session_scope(commit=False) as session:
        hidden = _hidden_ids(session)
        candidates = ChannelRepository(session).get_reconnect_candidates(hidden)

    assert len(candidates) == 1
    assert candidates[0].orphan_id == "orphan3"
    assert candidates[0].content_key is None
    assert candidates[0].match is None


def test_best_quality_tier_wins_among_several_candidates(db):
    """When multiple live channels share the orphan's content_key, the highest
    channel_name_utils.QUALITY_TIER_RANK candidate is proposed."""
    pid_dead = "p-dead4"
    pid_live_sd, pid_live_4k, pid_live_hd = "p-live4a", "p-live4b", "p-live4c"
    key = "movie:reconnect four|movie|2021"
    with db.session_scope() as session:
        _provider(session, pid_dead, is_active=False)
        _provider(session, pid_live_sd, is_active=True)
        _provider(session, pid_live_4k, is_active=True)
        _provider(session, pid_live_hd, is_active=True)
        _channel(session, pid_dead, cid="orphan4", content_key=key, is_favorite=True)
        _channel(session, pid_live_sd, cid="live4-sd", content_key=key, detected_quality="SD")
        _channel(session, pid_live_4k, cid="live4-4k", content_key=key, detected_quality="4K")
        _channel(session, pid_live_hd, cid="live4-hd", content_key=key, detected_quality="HD")

    with db.session_scope(commit=False) as session:
        hidden = _hidden_ids(session)
        candidates = ChannelRepository(session).get_reconnect_candidates(hidden)

    assert len(candidates) == 1
    assert candidates[0].match.channel_id == "live4-4k"


def test_get_reconnect_candidates_dto_survives_session_boundary(db):
    """The returned DTOs must be plain frozen dataclasses readable after the
    building session has committed/closed (a raw ORM object would raise
    DetachedInstanceError on the next attribute access post-commit)."""
    pid_dead, pid_live = "p-dead8", "p-live8"
    key = "movie:reconnect eight|movie|2020"
    with db.session_scope() as session:
        _provider(session, pid_dead, is_active=False)
        _provider(session, pid_live, is_active=True)
        _channel(session, pid_dead, cid="orphan8", content_key=key, is_favorite=True)
        _channel(session, pid_live, cid="live8", content_key=key, detected_quality="HD")

    with db.session_scope() as session:   # commit=True → expires ORM instances
        hidden = _hidden_ids(session)
        candidates = ChannelRepository(session).get_reconnect_candidates(hidden)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert dataclasses.is_dataclass(candidate)
    # Attribute access after the session closed must not raise.
    assert candidate.orphan_id == "orphan8"
    assert candidate.match.channel_id == "live8"


# ── reconnect_engaged_content ────────────────────────────────────────────────


def test_reconnect_moves_every_engagement_field_and_clears_orphan(db):
    """Reconnecting moves is_favorite/last_played/play_count/watch_progress/
    watch_completed/watch_percent/last_played_via, the UserRatingDB row, and
    WatchQueueDB membership onto the live channel — and clears all of it from
    the orphan, atomically."""
    pid_dead, pid_live = "p-dead5", "p-live5"
    orphan_id, live_id = "orphan5", "live5"
    key = "movie:reconnect five|movie|2019"
    played_at = datetime(2026, 7, 1, 12, 0, 0)
    with db.session_scope() as session:
        _provider(session, pid_dead, is_active=False)
        _provider(session, pid_live, is_active=True)
        _channel(
            session, pid_dead, cid=orphan_id, content_key=key,
            is_favorite=True, last_played=played_at, play_count=7,
            watch_progress=930, watch_completed=True, watch_percent=100,
            last_played_via="manual",
        )
        _channel(session, pid_live, cid=live_id, content_key=key, detected_quality="HD")
        session.add(UserRatingDB(channel_id=orphan_id, rating=1, rated_at=played_at))
        session.add(WatchQueueDB(
            channel_id=orphan_id, channel_name="Orphan Five", media_type="movie",
            source_id=orphan_id, position=0,
        ))

    with db.session_scope() as session:
        ChannelRepository(session).reconnect_engaged_content(orphan_id, live_id)

    with db.session_scope(commit=False) as session:
        orphan = session.get(ChannelDB, orphan_id)
        live = session.get(ChannelDB, live_id)

        # Moved onto the live channel.
        assert live.is_favorite is True
        assert live.last_played == played_at
        assert live.play_count == 7
        assert live.watch_progress == 930
        assert live.watch_completed is True
        assert live.watch_percent == 100
        assert live.last_played_via == "manual"

        # Cleared on the orphan.
        assert orphan.is_favorite is False
        assert orphan.last_played is None
        assert orphan.play_count == 0
        assert orphan.watch_progress == 0
        assert orphan.watch_completed is False
        assert orphan.watch_percent == 0
        assert orphan.last_played_via is None

        # Rating moved.
        assert session.get(UserRatingDB, orphan_id) is None
        live_rating = session.get(UserRatingDB, live_id)
        assert live_rating is not None
        assert live_rating.rating == 1

        # Queue membership moved.
        assert session.query(WatchQueueDB).filter_by(channel_id=orphan_id).count() == 0
        moved_row = session.query(WatchQueueDB).filter_by(channel_id=live_id).first()
        assert moved_row is not None
        assert moved_row.channel_name == live.name


def test_reconnect_rolls_back_atomically_on_mid_move_failure(db, monkeypatch):
    """A failure partway through the move (after the scalar fields are already
    mutated in-memory, before commit) must leave BOTH rows completely
    untouched — session_scope's rollback, not a partial write."""
    pid_dead, pid_live = "p-dead6", "p-live6"
    orphan_id, live_id = "orphan6", "live6"
    key = "movie:reconnect six|movie|2020"
    with db.session_scope() as session:
        _provider(session, pid_dead, is_active=False)
        _provider(session, pid_live, is_active=True)
        _channel(session, pid_dead, cid=orphan_id, content_key=key, is_favorite=True,
                  play_count=3)
        _channel(session, pid_live, cid=live_id, content_key=key, is_favorite=False,
                  play_count=0)

    with pytest.raises(RuntimeError, match="simulated mid-move failure"):
        with db.session_scope() as session:
            repo = ChannelRepository(session)
            orig_query = session.query

            def _boom(model, *args, **kwargs):
                if model is WatchQueueDB:
                    # The scalar engagement fields (is_favorite, play_count, ...)
                    # are already set in-memory on `live`/`orphan` by this point —
                    # a genuine MID-move failure, not a before-any-write one.
                    raise RuntimeError("simulated mid-move failure")
                return orig_query(model, *args, **kwargs)

            monkeypatch.setattr(session, "query", _boom)
            repo.reconnect_engaged_content(orphan_id, live_id)

    with db.session_scope(commit=False) as session:
        orphan = session.get(ChannelDB, orphan_id)
        live = session.get(ChannelDB, live_id)
        assert orphan.is_favorite is True, "rollback must leave the orphan untouched"
        assert orphan.play_count == 3, "rollback must leave the orphan untouched"
        assert live.is_favorite is False, "rollback must leave the live channel untouched"
        assert live.play_count == 0, "rollback must leave the live channel untouched"


def test_reconnect_transfers_queue_membership_without_duplicating(db):
    """When the live channel already has its own channel-grain queue row,
    reconnecting must not create a second one — the orphan's redundant row is
    dropped instead of moved."""
    pid_dead, pid_live = "p-dead7", "p-live7"
    orphan_id, live_id = "orphan7", "live7"
    key = "movie:reconnect seven|movie|2018"
    with db.session_scope() as session:
        _provider(session, pid_dead, is_active=False)
        _provider(session, pid_live, is_active=True)
        _channel(session, pid_dead, cid=orphan_id, content_key=key, is_favorite=True)
        _channel(session, pid_live, cid=live_id, content_key=key)
        session.add(WatchQueueDB(channel_id=orphan_id, channel_name="Orphan Seven",
                                  media_type="movie", source_id=orphan_id, position=0))
        session.add(WatchQueueDB(channel_id=live_id, channel_name="Live Seven",
                                  media_type="movie", source_id=live_id, position=1))

    with db.session_scope() as session:
        ChannelRepository(session).reconnect_engaged_content(orphan_id, live_id)

    with db.session_scope(commit=False) as session:
        assert session.query(WatchQueueDB).filter_by(channel_id=orphan_id).count() == 0
        live_rows = (
            session.query(WatchQueueDB)
            .filter_by(channel_id=live_id, episode_id=None)
            .all()
        )
        assert len(live_rows) == 1, "must not duplicate the live channel's queue row"


def test_reconnect_refuses_content_key_mismatch(db):
    """Defense in depth: reconnect_engaged_content must refuse to move engagement
    across different content_keys, even if called directly."""
    pid_dead, pid_live = "p-dead9", "p-live9"
    orphan_id, live_id = "orphan9", "live9"
    with db.session_scope() as session:
        _provider(session, pid_dead, is_active=False)
        _provider(session, pid_live, is_active=True)
        _channel(session, pid_dead, cid=orphan_id, content_key="key:a|movie|2020",
                  is_favorite=True)
        _channel(session, pid_live, cid=live_id, content_key="key:b|movie|2020")

    with pytest.raises(ValueError, match="content_key mismatch"):
        with db.session_scope() as session:
            ChannelRepository(session).reconnect_engaged_content(orphan_id, live_id)

    with db.session_scope(commit=False) as session:
        orphan = session.get(ChannelDB, orphan_id)
        assert orphan.is_favorite is True, "refused move must leave the orphan untouched"
