"""Behavioral tests for the memory-safe rewrite of update_detected_prefixes.

Guards three invariants:
1. Chunked fetch (BATCH=2000): all channels across batch boundaries are processed and
   their detected_* fields are populated correctly — no rows dropped at the last partial batch.
2. Provider-scoping: calling with provider_id=X only touches X's channels; the other
   provider's rows are unchanged (pins Part 2 of the fix).
3. No-change short-circuit: a second call with identical data returns updated==0
   (the `changed` diff logic still works after the refactor).

All tests use a file-backed (tmp_path) SQLite DB per the CLAUDE.md rule — not :memory:,
whose pooled connections each get an empty schema.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path: Path):
    """File-backed Database with tables created — shared across queries in the test."""
    from metatv.core.database import Database
    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.create_tables()
    yield d
    d.close()


def _make_channel(session, name: str, provider_id: str = "p1") -> str:
    """Insert a minimal ChannelDB row and return its id."""
    from metatv.core.database import ChannelDB
    cid = str(uuid.uuid4())
    session.add(ChannelDB(
        id=cid,
        source_id=str(uuid.uuid4()),
        provider_id=provider_id,
        name=name,
        media_type="live",
    ))
    return cid


# ---------------------------------------------------------------------------
# 1. Cross-batch-boundary coverage
#    Seed 2500 channels (> BATCH=2000) so the method must process at least two
#    chunks.  Spot-check channels at index 0, 1999, 2000, and 2499 to confirm
#    all batches are processed and the partial final batch isn't dropped.
# ---------------------------------------------------------------------------

def test_chunked_processes_all_channels_across_batch_boundary(db):
    """2500 channels across 2 batches: every channel gets its detected_* set."""
    from metatv.core.database import ChannelDB
    from metatv.core.repositories import RepositoryFactory

    # Seed 2500 channels with names that exercise prefix/quality/title detection.
    # Use a stable naming pattern so we can predict expected values by index.
    ids = []
    with db.session_scope() as session:
        for i in range(2500):
            if i % 5 == 0:
                name = f"EN - Movie {i} HD"
            elif i % 5 == 1:
                name = f"ES ★ Pelicula {i}"
            elif i % 5 == 2:
                name = f"DE - Film {i}"
            elif i % 5 == 3:
                name = f"4K-FR - Titre {i}"
            else:
                name = f"Channel {i} Without Prefix"
            ids.append(_make_channel(session, name, provider_id="p1"))

    with db.session_scope() as session:
        repos = RepositoryFactory(session)
        updated_count = repos.channels.update_detected_prefixes()

    # All 2500 were previously unset (detected_prefix=None etc.), so all should
    # register as changed — minimum possible is all the EN/ES/DE/4K-FR ones.
    assert updated_count > 0, "Expected at least some channels to be detected as changed"

    # Spot-check at index 0, 1999 (last of batch 1), 2000 (first of batch 2), 2499 (last)
    # via a fresh session so we read committed state.
    with db.session_scope() as session:
        def _fetch(idx: int) -> ChannelDB:
            return session.query(ChannelDB).filter_by(id=ids[idx]).first()

        # index 0: "EN - Movie 0 HD"
        ch0 = _fetch(0)
        assert ch0.detected_prefix == "EN", f"idx=0 prefix: {ch0.detected_prefix!r}"
        assert ch0.detected_quality == "HD", f"idx=0 quality: {ch0.detected_quality!r}"
        assert ch0.detected_title is not None, f"idx=0 title should not be None"

        # index 1999: 1999 % 5 == 4 → "Channel 1999 Without Prefix"
        ch1999 = _fetch(1999)
        # No EN/ES/etc. prefix — detected_prefix may be None; just assert it was visited
        # (detected_title will be set to the bare name by parse_channel_name).
        assert ch1999.detected_title is not None, (
            f"idx=1999 (last of batch 1) was not processed; detected_title is None"
        )

        # index 2000: 2000 % 5 == 0 → "EN - Movie 2000 HD"  (first of batch 2)
        ch2000 = _fetch(2000)
        assert ch2000.detected_prefix == "EN", f"idx=2000 (first of batch 2) prefix: {ch2000.detected_prefix!r}"
        assert ch2000.detected_quality == "HD", f"idx=2000 quality: {ch2000.detected_quality!r}"

        # index 2499: 2499 % 5 == 4 → "Channel 2499 Without Prefix" (last of partial batch)
        ch2499 = _fetch(2499)
        assert ch2499.detected_title is not None, (
            f"idx=2499 (last of partial batch 2) was not processed; detected_title is None"
        )

        # Also spot-check a 4K-FR compound channel (index 3: "4K-FR - Titre 3")
        ch3 = _fetch(3)
        assert ch3.detected_prefix == "FR", f"idx=3 (4K-FR compound) prefix: {ch3.detected_prefix!r}"
        assert ch3.detected_quality == "4K", f"idx=3 (4K-FR compound) quality: {ch3.detected_quality!r}"


def test_updated_count_equals_channels_changed(db):
    """Return value of update_detected_prefixes equals the number of rows actually changed."""
    from metatv.core.database import ChannelDB
    from metatv.core.repositories import RepositoryFactory

    with db.session_scope() as session:
        # 3 channels — all will go from None → detected value on first call
        ids = [
            _make_channel(session, "EN - Breaking Bad", provider_id="p1"),
            _make_channel(session, "DE - Film", provider_id="p1"),
            _make_channel(session, "NoPrefix Channel", provider_id="p1"),
        ]

    with db.session_scope() as session:
        repos = RepositoryFactory(session)
        count = repos.channels.update_detected_prefixes()

    # All 3 start with detected_* = None, so all should be marked changed.
    assert count == 3, f"Expected 3 updated, got {count}"


# ---------------------------------------------------------------------------
# 2. Provider-scoping: only the target provider's channels are touched
#    This pins the correctness of Part 2 (provider_loader passing provider_id).
# ---------------------------------------------------------------------------

def test_provider_scoped_call_leaves_other_provider_unchanged(db):
    """update_detected_prefixes(provider_id='p1') must NOT touch provider 'p2' rows."""
    from metatv.core.database import ChannelDB
    from metatv.core.repositories import RepositoryFactory

    SENTINEL_PREFIX = "SENTINEL"
    SENTINEL_QUALITY = "SENTINEL_Q"

    with db.session_scope() as session:
        p1_id = _make_channel(session, "EN - Movie HD", provider_id="p1")
        p2_id = _make_channel(session, "FR - Film 4K", provider_id="p2")

    # Pre-set p2's detected_* to sentinel values so we can verify they weren't touched.
    with db.session_scope() as session:
        p2_ch = session.query(ChannelDB).filter_by(id=p2_id).first()
        p2_ch.detected_prefix = SENTINEL_PREFIX
        p2_ch.detected_quality = SENTINEL_QUALITY

    # Run detection scoped to p1 only.
    with db.session_scope() as session:
        repos = RepositoryFactory(session)
        updated = repos.channels.update_detected_prefixes(provider_id="p1")

    # p1 should have been detected.
    with db.session_scope() as session:
        p1_ch = session.query(ChannelDB).filter_by(id=p1_id).first()
        assert p1_ch.detected_prefix == "EN", (
            f"p1 channel prefix not set: {p1_ch.detected_prefix!r}"
        )
        assert p1_ch.detected_quality == "HD", (
            f"p1 channel quality not set: {p1_ch.detected_quality!r}"
        )

    # p2's sentinels must be UNCHANGED — the scoped call must not touch them.
    with db.session_scope() as session:
        p2_ch = session.query(ChannelDB).filter_by(id=p2_id).first()
        assert p2_ch.detected_prefix == SENTINEL_PREFIX, (
            f"p2 detected_prefix was modified! Expected sentinel {SENTINEL_PREFIX!r}, "
            f"got {p2_ch.detected_prefix!r}"
        )
        assert p2_ch.detected_quality == SENTINEL_QUALITY, (
            f"p2 detected_quality was modified! Expected sentinel {SENTINEL_QUALITY!r}, "
            f"got {p2_ch.detected_quality!r}"
        )

    # updated count should be exactly 1 (only p1 channel changed).
    assert updated == 1, f"Expected 1 updated (only p1), got {updated}"


def test_provider_scoped_does_not_return_unscoped_count(db):
    """Return count from a scoped call only counts rows from that provider."""
    from metatv.core.repositories import RepositoryFactory

    with db.session_scope() as session:
        for i in range(5):
            _make_channel(session, f"EN - Movie {i}", provider_id="p1")
        for i in range(3):
            _make_channel(session, f"FR - Film {i}", provider_id="p2")

    with db.session_scope() as session:
        repos = RepositoryFactory(session)
        count_p1 = repos.channels.update_detected_prefixes(provider_id="p1")

    # Only p1's 5 channels changed (all started with detected_* = None).
    assert count_p1 == 5, f"Expected 5 updated for p1, got {count_p1}"


# ---------------------------------------------------------------------------
# 3. No-change short-circuit still works after the refactor
#    A second call with identical detected_* state returns updated == 0.
# ---------------------------------------------------------------------------

def test_no_change_second_call_returns_zero(db):
    """Running update_detected_prefixes twice: second call returns 0 (changed guard intact)."""
    from metatv.core.repositories import RepositoryFactory

    with db.session_scope() as session:
        _make_channel(session, "EN - Breaking Bad", provider_id="p1")
        _make_channel(session, "DE - Film", provider_id="p1")

    # First call: both channels have detected_* = None → both changed.
    with db.session_scope() as session:
        repos = RepositoryFactory(session)
        first = repos.channels.update_detected_prefixes()
    assert first == 2, f"First call should mark 2 changed, got {first}"

    # Second call: detected_* already match what we'd compute → nothing changed.
    with db.session_scope() as session:
        repos = RepositoryFactory(session)
        second = repos.channels.update_detected_prefixes()
    assert second == 0, f"Second call should return 0 (no changes), got {second}"
