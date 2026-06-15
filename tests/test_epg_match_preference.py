"""Behavioral tests for EPG match preference order in _build_match_map (PR-1).

Tests drive the real ``_build_match_map`` method against a file-backed Database
(NOT :memory:) so that the session/table isolation is correct.  Each test
asserts the concrete outcome that would break if the priority logic regressed.

Priority order under test:
  1. Exact epg_channel_id match (unchanged tier — provider-agnostic).
  2. Same-provider fuzzy name match wins over cross-provider.
  3. Cross-provider fuzzy match fills gaps when same-provider has nothing.
  Hidden-provider channels (inactive or expired) are excluded from both fuzzy
  tiers regardless of name match.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from metatv.core.database import ChannelDB, Database, ProviderDB
from metatv.core.epg_manager import EpgManager
from metatv.core.xmltv_parser import XmltvChannel
from unittest.mock import MagicMock


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
    """EpgManager with a minimal mock config."""
    config = MagicMock()
    config.epg_default_refresh_interval = "3d"
    mgr = EpgManager(db, config, notifications=None)
    yield mgr
    mgr._executor.shutdown(wait=False)


def _add_provider(session, pid: str, *, is_active: bool = True, exp: datetime | None = None):
    """Seed a minimal ProviderDB row."""
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
) -> str:
    """Seed a ChannelDB row and return its id."""
    cid = channel_id or str(uuid.uuid4())
    session.add(ChannelDB(
        id=cid,
        source_id=cid,
        provider_id=provider_id,
        name=name,
        media_type=media_type,
        is_hidden=is_hidden,
        epg_channel_id=epg_channel_id,
    ))
    session.flush()
    return cid


# ---------------------------------------------------------------------------
# Test 1: same-provider fuzzy match beats cross-provider
# ---------------------------------------------------------------------------

def test_same_provider_wins_over_cross_provider(db, manager):
    """When two channels normalize to the same name, the one from the feed's own
    provider must be chosen — not the cross-provider channel."""
    with db.session_scope() as session:
        _add_provider(session, "prov-a")
        _add_provider(session, "prov-b")
        # Both normalize to "bein sports 1" via normalize_channel_name():
        #   "US ★ BEIN Sports 1" → strips "US ★ " prefix → "bein sports 1"
        #   "BEIN Sports 1 HD"   → strips " HD" suffix  → "bein sports 1"
        ch_a = _add_channel(session, provider_id="prov-a", name="US ★ BEIN Sports 1")
        ch_b = _add_channel(session, provider_id="prov-b", name="BEIN Sports 1 HD")

    xmltv = [XmltvChannel(epg_id="ch.bein1", display_name="BEIN Sports 1")]

    session = db.get_session()
    try:
        result = manager._build_match_map(session, xmltv, provider_id="prov-a")
    finally:
        session.close()

    assert "ch.bein1" in result, "XMLTV channel must be matched"
    assert result["ch.bein1"] == ch_a, (
        f"Expected provider-A's channel ({ch_a}); got {result['ch.bein1']} — "
        "same-provider match must beat cross-provider"
    )


# ---------------------------------------------------------------------------
# Test 2: cross-provider fallback when same-provider has no match
# ---------------------------------------------------------------------------

def test_cross_provider_fallback_when_no_same_provider_match(db, manager):
    """When the feed's own provider has no channel matching the XMLTV name,
    the cross-provider channel must still be returned (not None)."""
    with db.session_scope() as session:
        _add_provider(session, "prov-a")
        _add_provider(session, "prov-b")
        # Only provider-B has this channel; prov-a (the feed owner) has nothing
        ch_b = _add_channel(session, provider_id="prov-b", name="Sky Sports News")

    xmltv = [XmltvChannel(epg_id="ch.skynews", display_name="Sky Sports News")]

    session = db.get_session()
    try:
        result = manager._build_match_map(session, xmltv, provider_id="prov-a")
    finally:
        session.close()

    assert "ch.skynews" in result, (
        "Cross-provider fallback must match when the feed's own provider has no candidate"
    )
    assert result["ch.skynews"] == ch_b


# ---------------------------------------------------------------------------
# Test 3: hidden (inactive) provider channels are excluded from fuzzy matching
# ---------------------------------------------------------------------------

def test_hidden_inactive_provider_excluded_from_fuzzy(db, manager):
    """A channel on an inactive (toggled-off) provider must not receive guide data
    even if its name is the only fuzzy match.  The XMLTV id maps to None."""
    with db.session_scope() as session:
        _add_provider(session, "prov-active")
        _add_provider(session, "prov-inactive", is_active=False)
        # Only the inactive provider has a matching channel name
        _add_channel(session, provider_id="prov-inactive", name="CNN International")

    xmltv = [XmltvChannel(epg_id="ch.cnn", display_name="CNN International")]

    session = db.get_session()
    try:
        result = manager._build_match_map(session, xmltv, provider_id="prov-active")
    finally:
        session.close()

    assert result.get("ch.cnn") is None, (
        "Guide data must not attach to an inactive provider's channel; expected None"
    )


# ---------------------------------------------------------------------------
# Test 4: hidden (expired) provider channels are excluded from fuzzy matching
# ---------------------------------------------------------------------------

def test_hidden_expired_provider_excluded_from_fuzzy(db, manager):
    """A channel on an expired provider must never receive guide data,
    even if it's the only name match."""
    expired_date = datetime.now() - timedelta(days=1)

    with db.session_scope() as session:
        _add_provider(session, "prov-live")
        _add_provider(session, "prov-expired", exp=expired_date)
        # Only the expired provider has a matching channel
        _add_channel(session, provider_id="prov-expired", name="BBC One")

    xmltv = [XmltvChannel(epg_id="ch.bbc1", display_name="BBC One")]

    session = db.get_session()
    try:
        result = manager._build_match_map(session, xmltv, provider_id="prov-live")
    finally:
        session.close()

    assert result.get("ch.bbc1") is None, (
        "Guide data must not attach to an expired provider's channel; expected None"
    )


# ---------------------------------------------------------------------------
# Test 5: hidden provider excluded even if it would be same-provider match
# ---------------------------------------------------------------------------

def test_hidden_provider_excluded_even_as_same_provider(db, manager):
    """If the feed's own provider is inactive (edge case: fetching for an inactive
    provider, or provider deactivated mid-fetch), its channels are still excluded
    from the fuzzy pool via get_hidden_provider_ids()."""
    with db.session_scope() as session:
        _add_provider(session, "prov-self-inactive", is_active=False)
        # Channel belongs to the feed's own provider, but it's hidden
        _add_channel(session, provider_id="prov-self-inactive", name="Eurosport 1")

    xmltv = [XmltvChannel(epg_id="ch.euro1", display_name="Eurosport 1")]

    session = db.get_session()
    try:
        result = manager._build_match_map(session, xmltv, provider_id="prov-self-inactive")
    finally:
        session.close()

    assert result.get("ch.euro1") is None, (
        "Channels from a hidden provider must be excluded even if it is the feed's own provider"
    )


# ---------------------------------------------------------------------------
# Test 6: exact epg_channel_id match — tier 1 unaffected, provider-agnostic
# ---------------------------------------------------------------------------

def test_exact_epg_channel_id_match_wins(db, manager):
    """Tier 1 (exact epg_channel_id) must still fire regardless of provider,
    and must not be affected by the new same/cross-provider logic."""
    with db.session_scope() as session:
        _add_provider(session, "prov-x")
        _add_provider(session, "prov-y")
        # Channel on prov-y has a matching epg_channel_id
        ch_y = _add_channel(
            session,
            provider_id="prov-y",
            name="Something Else Entirely",
            epg_channel_id="exact-id-001",
        )
        # Channel on prov-x normalizes the same as the XMLTV display_name
        ch_x = _add_channel(session, provider_id="prov-x", name="The Sports Channel")

    # Feed belongs to prov-x; XMLTV channel has epg_id that matches prov-y's epg_channel_id
    xmltv = [XmltvChannel(epg_id="exact-id-001", display_name="The Sports Channel")]

    session = db.get_session()
    try:
        result = manager._build_match_map(session, xmltv, provider_id="prov-x")
    finally:
        session.close()

    assert "exact-id-001" in result, "Exact-id matched channel must be in result"
    assert result["exact-id-001"] == ch_y, (
        f"Exact epg_channel_id match must win over same-provider fuzzy match; "
        f"expected {ch_y}, got {result.get('exact-id-001')}"
    )


# ---------------------------------------------------------------------------
# Test 7: hidden provider channel loses to active cross-provider alternative
# ---------------------------------------------------------------------------

def test_hidden_provider_skipped_active_cross_provider_wins(db, manager):
    """When the same-normalized-name exists on both a hidden provider and an
    active provider, the active cross-provider channel must win."""
    with db.session_scope() as session:
        _add_provider(session, "prov-feed")
        _add_provider(session, "prov-hidden", is_active=False)
        _add_provider(session, "prov-active")

        _add_channel(session, provider_id="prov-hidden", name="RTE One")
        ch_active = _add_channel(session, provider_id="prov-active", name="RTE One HD")

    xmltv = [XmltvChannel(epg_id="ch.rte1", display_name="RTE One")]

    session = db.get_session()
    try:
        result = manager._build_match_map(session, xmltv, provider_id="prov-feed")
    finally:
        session.close()

    assert "ch.rte1" in result, "Active cross-provider alternative must match"
    assert result["ch.rte1"] == ch_active, (
        f"Active provider channel must win; got {result.get('ch.rte1')}"
    )
