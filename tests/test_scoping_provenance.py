"""Behavioral tests for the three scoping/provenance correctness fixes.

Fix 1 — Watch Alerts sidebar missing channel-provider scoping:
  _load_rows must pass excluded_channel_provider_ids to get_live_for_watchlist
  and get_upcoming_for_watchlist so alerts on disabled/expired-source channels
  are suppressed, mirroring the EPG Watchlist tab.

Fix 2 — Details pane always renders Source line with fallback for orphaned
  providers: load_basic must show the source_label whenever provider_id is
  present, including when the provider is absent from provider_map.

Fix 3 — ChannelRepository.search() missing excluded_provider_ids:
  search() must respect the excluded_provider_ids kwarg and filter matching
  channels from excluded providers, mirroring get_all().

All DB tests use file-backed SQLite (NOT :memory: — pooled connections each
get an empty schema there).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from metatv.core.database import (
    ChannelDB,
    Database,
    EpgProgramDB,
    ProviderDB,
)
from metatv.core.epg_utils import now_utc


# ===========================================================================
# Shared fixtures / helpers
# ===========================================================================

@pytest.fixture(scope="module")
def qapp():
    """Process-wide QApplication for headless Qt widget tests."""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _make_db(tmp_path: Path) -> Database:
    db = Database(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_tables()
    return db


def _add_provider(session, pid, *, is_active=True,
                  epg_url="http://e/xmltv.php", exp=None):
    session.add(ProviderDB(
        id=pid, name=pid, type="xtream", url="http://e.com",
        username="u", password="p", is_active=is_active,
        epg_url=epg_url, account_exp_date=exp,
    ))
    session.flush()


def _add_channel(session, cid, name, provider_id):
    session.add(ChannelDB(
        id=cid, source_id=cid, provider_id=provider_id, name=name,
    ))
    session.flush()


def _add_programme(session, provider_id, title, channel_db_id, *,
                   minutes_ago: int = 5, duration_minutes: int = 60):
    now = now_utc()
    session.add(EpgProgramDB(
        provider_id=provider_id,
        channel_epg_id=f"ch.{channel_db_id}",
        channel_db_id=channel_db_id,
        title=title,
        start_time=now - timedelta(minutes=minutes_ago),
        stop_time=now + timedelta(minutes=duration_minutes - minutes_ago),
    ))
    session.flush()


def _add_upcoming(session, provider_id, title, channel_db_id, *,
                  minutes_ahead: int = 30):
    now = now_utc()
    session.add(EpgProgramDB(
        provider_id=provider_id,
        channel_epg_id=f"ch.{channel_db_id}",
        channel_db_id=channel_db_id,
        title=title,
        start_time=now + timedelta(minutes=minutes_ahead),
        stop_time=now + timedelta(minutes=minutes_ahead + 60),
    ))
    session.flush()


def _fake_config(**overrides):
    defaults = dict(
        epg_watchlist_patterns=[],
        watch_alerts_icon="🔔",
        collapse_icon="▼",
        expand_icon="▶",
        play_icon="▷",
        info_icon="ℹ",
        sidebar_section_states={},
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ===========================================================================
# Fix 1 — Watch Alerts sidebar channel-provider scoping
# ===========================================================================

class TestAlertsChannelProviderScoping:
    """_load_rows must exclude channels on hidden providers from live and upcoming."""

    def test_live_alert_hidden_source_channel_excluded(self, tmp_path):
        """A live watchlist match on a disabled-source channel must NOT appear in
        the alerts _load_rows result, even when the EPG feed itself is active.

        Cross-provider EPG scenario: active feed "feed-p" matched a programme to
        channel "ch-hidden" which lives on the now-disabled "disabled-src" provider.
        The fix computes get_hidden_provider_ids() and passes it as
        excluded_channel_provider_ids to get_live_for_watchlist.
        """
        from metatv.gui.sidebar.alerts import WatchAlertsSection

        db = _make_db(tmp_path)
        with db.session_scope() as session:
            _add_provider(session, "feed-p", is_active=True, epg_url="http://e/xmltv.php")
            _add_provider(session, "disabled-src", is_active=False, epg_url="http://e/xmltv.php")
            _add_provider(session, "active-src",   is_active=True,  epg_url="http://e/xmltv.php")
            _add_channel(session, "ch-ok",     "Good Channel", "active-src")
            _add_channel(session, "ch-hidden", "Dead Channel", "disabled-src")
            # Both channels have a live matching programme on the active feed
            _add_programme(session, "feed-p", "Breaking Bad", "ch-ok")
            _add_programme(session, "feed-p", "Breaking Bad", "ch-hidden")

        obj = WatchAlertsSection.__new__(WatchAlertsSection)
        obj.db = db
        obj.config = _fake_config(epg_watchlist_patterns=["Breaking Bad"])

        result = obj._load_rows()

        live_groups = result["live_groups"]
        all_cids = {
            a[3]
            for grp in live_groups.values()
            for a in grp["live"]
        }
        assert "ch-ok"     in all_cids, "Active-source channel must appear in live alerts"
        assert "ch-hidden" not in all_cids, (
            "Disabled-source channel must be excluded from live alerts "
            "(EPG feed is active, but the channel's source is not)"
        )
        db.close()

    def test_upcoming_alert_hidden_source_channel_excluded(self, tmp_path):
        """An upcoming watchlist match on a disabled-source channel must not appear."""
        from metatv.gui.sidebar.alerts import WatchAlertsSection

        db = _make_db(tmp_path)
        with db.session_scope() as session:
            _add_provider(session, "feed-q",     is_active=True,  epg_url="http://e/xmltv.php")
            _add_provider(session, "gone-src",   is_active=False, epg_url="http://e/xmltv.php")
            _add_provider(session, "live-src",   is_active=True,  epg_url="http://e/xmltv.php")
            _add_channel(session, "ch-live",  "Live Channel", "live-src")
            _add_channel(session, "ch-gone",  "Gone Channel", "gone-src")
            _add_upcoming(session, "feed-q", "The Wire", "ch-live")
            _add_upcoming(session, "feed-q", "The Wire", "ch-gone")

        obj = WatchAlertsSection.__new__(WatchAlertsSection)
        obj.db = db
        obj.config = _fake_config(epg_watchlist_patterns=["The Wire"])

        result = obj._load_rows()

        upcoming_only = result["upcoming_only"]
        all_cids = {
            a[3]
            for grp in upcoming_only.values()
            for a in grp["airings"]
        }
        assert "ch-live" in all_cids,  "Active-source upcoming alert must appear"
        assert "ch-gone" not in all_cids, (
            "Disabled-source channel must be excluded from upcoming alerts"
        )
        db.close()

    def test_expired_source_channel_excluded_from_live_alerts(self, tmp_path):
        """An alert on a channel whose provider is expired (not just inactive) is excluded."""
        from metatv.gui.sidebar.alerts import WatchAlertsSection

        past = datetime.now() - timedelta(days=1)
        db = _make_db(tmp_path)
        with db.session_scope() as session:
            _add_provider(session, "feed-r",    is_active=True, epg_url="http://e/xmltv.php")
            _add_provider(session, "fresh-src", is_active=True, epg_url="http://e/xmltv.php")
            _add_provider(session, "exp-src",   is_active=True, epg_url="http://e/xmltv.php",
                          exp=past)
            _add_channel(session, "ch-fresh", "Fresh Channel",   "fresh-src")
            _add_channel(session, "ch-exp",   "Expired Channel", "exp-src")
            _add_programme(session, "feed-r", "Sopranos", "ch-fresh")
            _add_programme(session, "feed-r", "Sopranos", "ch-exp")

        obj = WatchAlertsSection.__new__(WatchAlertsSection)
        obj.db = db
        obj.config = _fake_config(epg_watchlist_patterns=["Sopranos"])

        result = obj._load_rows()

        live_groups = result["live_groups"]
        all_cids = {
            a[3]
            for grp in live_groups.values()
            for a in grp["live"]
        }
        assert "ch-fresh" in all_cids,   "Active-source channel must appear"
        assert "ch-exp"   not in all_cids, "Expired-source channel must be excluded"
        db.close()


# ===========================================================================
# Fix 2 — Details pane Source line with fallback for orphaned providers
# ===========================================================================

class TestDetailsSourceLineFallback:
    """load_basic must always render source_label when provider_id is present."""

    def _make_channel(self, provider_id="prov-123", channel_id="ch-abc"):
        """Minimal fake channel object."""
        ch = SimpleNamespace(
            id=channel_id,
            name="Test Channel",
            media_type="live",
            provider_id=provider_id,
            detected_prefix=None,
            detected_quality=None,
            detected_region=None,
            is_adult=False,
            raw_data=None,
        )
        return ch

    def _make_section(self, qapp):
        """Build a real _MetadataSection with a minimal fake config.

        The section is fully constructed (not __new__) because load_basic touches
        many attributes (_rating_row, genres_label, rec_reason_label, etc.) that
        are set up in _setup(). The config only needs the attributes load_basic
        reads at the code paths that will execute (no raw_data → rating branch skipped).
        """
        from metatv.gui.details_sections import _MetadataSection

        config = SimpleNamespace(
            rating_star_icon="★",
            preferences_icon="⚙",
            collapse_icon="▼",
            expand_icon="▶",
        )
        return _MetadataSection(config)

    def test_source_label_shown_when_provider_in_map(self, qapp):
        """Normal case: provider_id present in provider_map → shows icon+name badge."""
        section = self._make_section(qapp)
        ch = self._make_channel(provider_id="prov-1")
        provider_map = {
            "prov-1": {"icon": "🔵", "name": "Provider One"},
        }

        section.load_basic(ch, provider_map=provider_map)

        assert not section.source_label.isHidden(), (
            "source_label must be visible when provider is in map"
        )
        text = section.source_label.text()
        assert "Provider One" in text, f"Expected provider name in label, got: {text!r}"
        assert section.source_label.channel_id == ch.id, (
            "channel_id must be set for click-to-copy even in normal case"
        )

    def test_source_label_shown_with_fallback_when_provider_not_in_map(self, qapp):
        """Orphan/unknown case: provider_id not in provider_map → fallback label shown.

        This is the regression fix: previously the source_label stayed hidden
        for orphaned channels, preventing users from copying the channel ID.
        """
        section = self._make_section(qapp)
        ch = self._make_channel(provider_id="orphan-prov-xyz")
        provider_map = {}  # provider absent from map

        section.load_basic(ch, provider_map=provider_map)

        assert not section.source_label.isHidden(), (
            "source_label must be visible even when provider is NOT in map (orphan regression)"
        )
        text = section.source_label.text()
        assert "orphan-prov-xyz" in text, (
            f"Fallback label must include the provider_id so user can identify the source; got: {text!r}"
        )
        assert section.source_label.channel_id == ch.id, (
            "channel_id must be set so orphan channels are still copyable"
        )
        tooltip = section.source_label.toolTip()
        assert ch.id in tooltip, (
            f"Tooltip must include channel id for copy hint; got: {tooltip!r}"
        )

    def test_source_label_shown_when_provider_map_is_none(self, qapp):
        """provider_map=None (no map passed at all) → fallback label still shown."""
        section = self._make_section(qapp)
        ch = self._make_channel(provider_id="prov-no-map")

        section.load_basic(ch, provider_map=None)

        assert not section.source_label.isHidden(), (
            "source_label must be visible even when provider_map is None"
        )
        text = section.source_label.text()
        assert "prov-no-map" in text, (
            f"Fallback must include provider_id when map is None; got: {text!r}"
        )

    def test_source_label_hidden_when_no_provider_id(self, qapp):
        """Channel with no provider_id → source_label stays hidden (no source to report)."""
        section = self._make_section(qapp)
        ch = self._make_channel(provider_id=None)

        section.load_basic(ch, provider_map={})

        assert section.source_label.isHidden(), (
            "source_label must remain hidden when channel has no provider_id"
        )


# ===========================================================================
# Fix 3 — ChannelRepository.search() excluded_provider_ids
# ===========================================================================

class TestSearchExcludedProviderIds:
    """search() must filter channels from excluded providers when the kwarg is passed."""

    @pytest.fixture
    def db(self, tmp_path):
        database = _make_db(tmp_path)
        yield database
        database.close()

    @pytest.fixture
    def session(self, db):
        s = db.get_session()
        yield s
        s.close()

    def _seed(self, session):
        """Seed two providers each with a matching channel named 'Test Show'."""
        session.add(ProviderDB(
            id="prov-a", name="Provider A", type="xtream", url="http://a.com",
            username="u", password="p",
        ))
        session.add(ProviderDB(
            id="prov-b", name="Provider B", type="xtream", url="http://b.com",
            username="u", password="p",
        ))
        session.add(ChannelDB(
            id="ch-a", source_id="ch-a", provider_id="prov-a",
            name="Test Show A", is_hidden=False,
        ))
        session.add(ChannelDB(
            id="ch-b", source_id="ch-b", provider_id="prov-b",
            name="Test Show B", is_hidden=False,
        ))
        session.flush()

    def test_search_without_exclusion_returns_all_matches(self, session):
        """Without excluded_provider_ids, search returns channels from all providers."""
        from metatv.core.repositories.channel import ChannelRepository

        self._seed(session)
        repo = ChannelRepository(session)
        results = repo.search("Test Show")
        ids = {ch.id for ch in results}
        assert {"ch-a", "ch-b"} == ids, (
            "Without exclusion both matching channels must be returned"
        )

    def test_search_with_excluded_provider_omits_those_channels(self, session):
        """Passing excluded_provider_ids=["prov-b"] must drop prov-b's channels."""
        from metatv.core.repositories.channel import ChannelRepository

        self._seed(session)
        repo = ChannelRepository(session)
        results = repo.search("Test Show", excluded_provider_ids=["prov-b"])
        ids = {ch.id for ch in results}
        assert "ch-a" in ids,  "prov-a channel must still appear"
        assert "ch-b" not in ids, "prov-b channel must be excluded"

    def test_search_empty_exclusion_list_is_noop(self, session):
        """An empty list for excluded_provider_ids must behave identically to None."""
        from metatv.core.repositories.channel import ChannelRepository

        self._seed(session)
        repo = ChannelRepository(session)
        results_none  = repo.search("Test Show")
        results_empty = repo.search("Test Show", excluded_provider_ids=[])
        assert {ch.id for ch in results_none} == {ch.id for ch in results_empty}, (
            "Empty excluded_provider_ids must not change results"
        )

    def test_search_excludes_both_providers_returns_empty(self, session):
        """Excluding all providers that have matching channels returns an empty result."""
        from metatv.core.repositories.channel import ChannelRepository

        self._seed(session)
        repo = ChannelRepository(session)
        results = repo.search("Test Show", excluded_provider_ids=["prov-a", "prov-b"])
        assert results == [], (
            "Excluding both providers must return no results"
        )

    def test_search_excluded_provider_ids_does_not_affect_other_params(self, session):
        """excluded_provider_ids combines correctly with other filters (media_type)."""
        from metatv.core.repositories.channel import ChannelRepository

        session.add(ChannelDB(
            id="ch-movie", source_id="ch-movie", provider_id="prov-a",
            name="Test Show Movie", media_type="movie", is_hidden=False,
        ))
        session.flush()

        repo = ChannelRepository(session)
        # Exclude prov-b; filter to movies; only ch-movie from prov-a should appear
        results = repo.search("Test Show", media_type="movie",
                              excluded_provider_ids=["prov-b"])
        ids = {ch.id for ch in results}
        assert "ch-movie" in ids,  "Movie channel from non-excluded provider must appear"
        assert "ch-b"     not in ids, "prov-b channel must be excluded"
