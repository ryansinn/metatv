"""Behavioral tests for Wave 3 Slice 3B: EPG link blocklist + region gate.

Covers three independent guards inside ``EpgManager._build_match_map``
(core/epg_manager.py), all consulted at match time so ``relink_all()`` — which
re-runs on every EPG view activation — can never silently undo them:

1. ``config.epg_link_blocklist`` — a channel the user manually cleared
   ("Clear EPG link") never re-enters tier 1 (exact epg_channel_id) or
   tiers 2/3 (fuzzy name) on a later relink pass. Removing it from the
   blocklist ("Re-link EPG data") lets the next relink pass re-match it.
2. Region-gated fuzzy matching — ``channel_name_utils.epg_tld_compatible``
   rejects a tier-2/3 fuzzy match when the candidate's detected region/prefix
   is incompatible with the EPG feed's TLD (parsed from its epg_id suffix);
   an unmapped code or unparseable TLD abstains (matches as before).
3. ``config.epg_fuzzy_prefix_blocklist`` — a channel whose detected_prefix is
   a known show-loop/rotation marker (default: EAR, 24/7, 24-7) never enters
   fuzzy tiers 2/3, but a tier-1 exact epg_channel_id match still applies.

Tests drive the real ``_build_match_map`` / ``_relink_provider`` methods
against a file-backed Database (NOT :memory:), matching the existing
test_epg_match_preference.py conventions.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from metatv.core.database import ChannelDB, Database, EpgProgramDB, ProviderDB
from metatv.core.epg_manager import EpgManager
from metatv.core.xmltv_parser import XmltvChannel
from metatv.gui.channel_menu import ACTIONS, SURFACE_LAYOUTS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    """File-backed Database (NOT :memory:) with all tables created."""
    path = tmp_path / "test.db"
    database = Database(f"sqlite:///{path}")
    database.create_tables()
    yield database
    database.engine.dispose()


@pytest.fixture
def manager(db):
    """EpgManager with a minimal-but-real-shaped config mock.

    epg_link_blocklist / epg_fuzzy_prefix_blocklist default to real lists
    (mirroring Config's actual defaults) rather than auto-MagicMocks, since
    _build_match_map does ``self.config.epg_link_blocklist or []``.
    """
    config = MagicMock()
    config.epg_default_refresh_interval = "3d"
    config.epg_link_blocklist = []
    config.epg_fuzzy_prefix_blocklist = ["EAR", "24/7", "24-7"]
    mgr = EpgManager(db, config, notifications=None)
    yield mgr
    mgr._executor.shutdown(wait=False)


def _add_provider(session, pid: str, *, is_active: bool = True, exp: datetime | None = None):
    session.add(ProviderDB(
        id=pid, name=pid, type="xtream", url="http://e.com",
        username="u", password="p",
        is_active=is_active,
        account_exp_date=exp,
    ))
    session.flush()


def _add_channel(
    session,
    *,
    channel_id: str | None = None,
    provider_id: str,
    name: str,
    epg_channel_id: str | None = None,
    is_hidden: bool = False,
    media_type: str = "live",
    detected_prefix: str | None = None,
    detected_region: str | None = None,
) -> str:
    cid = channel_id or str(uuid.uuid4())
    session.add(ChannelDB(
        id=cid,
        source_id=cid,
        provider_id=provider_id,
        name=name,
        media_type=media_type,
        is_hidden=is_hidden,
        epg_channel_id=epg_channel_id,
        detected_prefix=detected_prefix,
        detected_region=detected_region,
    ))
    session.flush()
    return cid


def _add_programme(
    session, *, provider_id: str, channel_epg_id: str, channel_name: str,
    channel_db_id: str | None,
) -> None:
    now = datetime(2026, 8, 1, 12, 0, 0)
    session.add(EpgProgramDB(
        provider_id=provider_id,
        channel_epg_id=channel_epg_id,
        channel_db_id=channel_db_id,
        channel_name=channel_name,
        title="Some Show",
        start_time=now,
        stop_time=now + timedelta(hours=1),
    ))
    session.flush()


# ---------------------------------------------------------------------------
# Part 1: persistent "Clear EPG link" blocklist
# ---------------------------------------------------------------------------

def test_blocklisted_channel_never_relinked_by_relink_pass(db, manager):
    """The regression this feature fixes: a channel already fuzzy-matched, then
    blocklisted (simulating "Clear EPG link"), must stay unlinked across a
    relink_all()-style pass — not get silently re-attached by tier 2/3 fuzzy
    name matching."""
    with db.session_scope() as session:
        _add_provider(session, "prov-a")
        cid = _add_channel(session, provider_id="prov-a", name="BBC One")
        # Programme rows already exist (from an earlier fetch) but the link was
        # just cleared: channel_db_id is None, matching what clear_channel_epg_link
        # leaves behind.
        _add_programme(
            session, provider_id="prov-a", channel_epg_id="epg.bbc1",
            channel_name="BBC One", channel_db_id=None,
        )

    # Simulate the user having cleared this channel's link.
    manager.config.epg_link_blocklist = [cid]

    with db.session_scope() as session:
        updated = manager._relink_provider(session, "prov-a")

    assert updated == 0, "Blocklisted channel must not be re-linked by relink"

    with db.session_scope(commit=False) as session:
        row = (
            session.query(EpgProgramDB)
            .filter_by(channel_epg_id="epg.bbc1")
            .first()
        )
        assert row.channel_db_id is None, (
            "Programme row must stay unlinked — blocklist must survive relink_all()"
        )


def test_reallow_removes_blocklist_and_relink_rematches(db, manager):
    """Baseline contrast + 're-allow' path: the SAME setup as above, but with the
    channel removed from (never added to) the blocklist — relink must re-match it.
    This proves the blocklist (not some other factor) is what suppressed the match
    above, and demonstrates 'Re-link EPG data' (blocklist.remove + relink) works."""
    with db.session_scope() as session:
        _add_provider(session, "prov-a")
        cid = _add_channel(session, provider_id="prov-a", name="BBC One")
        _add_programme(
            session, provider_id="prov-a", channel_epg_id="epg.bbc1",
            channel_name="BBC One", channel_db_id=None,
        )

    # First block it, then re-allow (removes from list) — mirrors relink_channel_epg.
    manager.config.epg_link_blocklist = [cid]
    manager.config.epg_link_blocklist.remove(cid)
    assert manager.config.epg_link_blocklist == []

    with db.session_scope() as session:
        updated = manager._relink_provider(session, "prov-a")

    assert updated == 1, "Re-allowed channel must be re-matched by the next relink"

    with db.session_scope(commit=False) as session:
        row = (
            session.query(EpgProgramDB)
            .filter_by(channel_epg_id="epg.bbc1")
            .first()
        )
        assert row.channel_db_id == cid


def test_blocklist_suppresses_tier1_exact_id_too(db, manager):
    """A blocklisted channel must be excluded from tier-1 (exact epg_channel_id)
    as well — covers the 'provider re-ingestion rewrites epg_channel_id' case
    (providers/xtream.py) where only the blocklist, not a null id, can guard."""
    with db.session_scope() as session:
        _add_provider(session, "prov-a")
        cid = _add_channel(
            session, provider_id="prov-a", name="Random Name",
            epg_channel_id="exact.001",
        )

    manager.config.epg_link_blocklist = [cid]

    xmltv = [XmltvChannel(epg_id="exact.001", display_name="Random Name")]
    with db.session_scope(commit=False) as session:
        result = manager._build_match_map(session, xmltv, provider_id="prov-a")

    assert result.get("exact.001") is None, (
        "Blocklisted channel must be excluded from tier-1 exact matching too"
    )


# ---------------------------------------------------------------------------
# Part 2: region-gated fuzzy matching
# ---------------------------------------------------------------------------

def test_region_gate_rejects_en_prefix_vs_es_tld(db, manager):
    """An EN/US-prefixed channel must not fuzzy-match a Spanish (.es) guide feed."""
    with db.session_scope() as session:
        _add_provider(session, "prov-a")
        _add_channel(
            session, provider_id="prov-a", name="Sports Channel 1",
            detected_prefix="US",
        )

    xmltv = [XmltvChannel(epg_id="feed.sports1.es", display_name="Sports Channel 1")]
    with db.session_scope(commit=False) as session:
        result = manager._build_match_map(session, xmltv, provider_id="prov-a")

    assert result.get("feed.sports1.es") is None, (
        "US-prefixed channel must be rejected against a .es EPG feed"
    )


def test_region_gate_allows_en_prefix_vs_uk_tld(db, manager):
    """The same US-prefixed channel MUST still match a compatible .uk feed —
    proves the gate is a real gate, not a blanket suppression."""
    with db.session_scope() as session:
        _add_provider(session, "prov-a")
        cid = _add_channel(
            session, provider_id="prov-a", name="Sports Channel 1",
            detected_prefix="US",
        )

    xmltv = [XmltvChannel(epg_id="feed.sports1.uk", display_name="Sports Channel 1")]
    with db.session_scope(commit=False) as session:
        result = manager._build_match_map(session, xmltv, provider_id="prov-a")

    assert result.get("feed.sports1.uk") == cid, (
        "US-prefixed channel must match a compatible .uk EPG feed"
    )


def test_region_gate_abstains_on_unknown_prefix(db, manager):
    """A detected_prefix absent from REGION_TLD_COMPATIBILITY must never block a
    match — the gate abstains and behaves exactly as before this feature."""
    with db.session_scope() as session:
        _add_provider(session, "prov-a")
        cid = _add_channel(
            session, provider_id="prov-a", name="Local News",
            detected_prefix="ZZZ",  # not in the compatibility map
        )

    xmltv = [XmltvChannel(epg_id="feed.localnews.es", display_name="Local News")]
    with db.session_scope(commit=False) as session:
        result = manager._build_match_map(session, xmltv, provider_id="prov-a")

    assert result.get("feed.localnews.es") == cid, (
        "Unmapped prefix must abstain (match proceeds) rather than reject"
    )


def test_region_gate_abstains_on_unparseable_tld(db, manager):
    """An epg_id with no dot-suffix (or a non-alpha/long suffix) has no parseable
    TLD — the gate must abstain even for a mapped region code."""
    with db.session_scope() as session:
        _add_provider(session, "prov-a")
        cid = _add_channel(
            session, provider_id="prov-a", name="News Now",
            detected_prefix="US",
        )

    xmltv = [XmltvChannel(epg_id="feed.newsnow", display_name="News Now")]
    with db.session_scope(commit=False) as session:
        result = manager._build_match_map(session, xmltv, provider_id="prov-a")

    assert result.get("feed.newsnow") == cid


# ---------------------------------------------------------------------------
# Part 3: fuzzy prefix blocklist (show-loop / rotation channels)
# ---------------------------------------------------------------------------

def test_ear_prefix_skips_fuzzy_but_keeps_exact(db, manager):
    """A channel with detected_prefix 'EAR' (default fuzzy_prefix_blocklist entry)
    must be excluded from tier 2/3 fuzzy matching, but a tier-1 exact
    epg_channel_id match must still apply."""
    with db.session_scope() as session:
        _add_provider(session, "prov-a")
        # Channel A: EAR-prefixed, no exact id — must NOT be fuzzy-matched.
        _add_channel(
            session, provider_id="prov-a", name="Movie Loop 1",
            detected_prefix="EAR",
        )
        # Channel B: EAR-prefixed, but HAS an exact epg_channel_id — must still match.
        cid_exact = _add_channel(
            session, provider_id="prov-a", name="Movie Loop 2",
            detected_prefix="EAR", epg_channel_id="exact.loop2",
        )

    xmltv = [
        XmltvChannel(epg_id="feed.loop1", display_name="Movie Loop 1"),
        XmltvChannel(epg_id="exact.loop2", display_name="Movie Loop 2"),
    ]
    with db.session_scope(commit=False) as session:
        result = manager._build_match_map(session, xmltv, provider_id="prov-a")

    assert result.get("feed.loop1") is None, (
        "EAR-prefixed channel must be excluded from fuzzy tiers 2/3"
    )
    assert result.get("exact.loop2") == cid_exact, (
        "EAR-prefixed channel must still match via tier-1 exact epg_channel_id"
    )


def test_fuzzy_prefix_blocklist_is_case_insensitive(db, manager):
    """The config list ['EAR', ...] must match a lowercase-stored prefix too."""
    with db.session_scope() as session:
        _add_provider(session, "prov-a")
        _add_channel(
            session, provider_id="prov-a", name="Loop Channel",
            detected_prefix="ear",
        )

    xmltv = [XmltvChannel(epg_id="feed.loop", display_name="Loop Channel")]
    with db.session_scope(commit=False) as session:
        result = manager._build_match_map(session, xmltv, provider_id="prov-a")

    assert result.get("feed.loop") is None


# ---------------------------------------------------------------------------
# Part 4: menu registry — new action on all three surfaces
# ---------------------------------------------------------------------------

def test_clear_epg_link_action_registered_on_three_surfaces():
    assert "clear_epg_link" in ACTIONS
    assert "clear_epg_link" in SURFACE_LAYOUTS["channel"]
    assert "clear_epg_link" in SURFACE_LAYOUTS["epg_on_now"]
    assert "clear_epg_link" in SURFACE_LAYOUTS["epg_browse"]
