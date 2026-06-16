"""Behavioral tests for EPG channel-provider scoping (fix/epg-onnow-channel-scoping).

All tests execute the real changed code paths against a file-backed Database
(NOT :memory: — pooled connections each get an empty schema there).

Bug being fixed (two parts):

  #9 — EPG "On Now" / watchlist queries filter by *feed* provider but not by the
       *channel's* provider.  When a cross-provider EPG match links an active feed to
       a disabled-source channel, that channel appeared in On Now.  The fix adds
       ``excluded_channel_provider_ids`` to get_current_programs,
       get_live_for_watchlist, get_upcoming_for_watchlist, and get_recommendations.

  #2 — ``_render_on_now`` built its global exclusion set from only
       ``global_filter_excluded_prefixes``, ignoring ``global_filter_excluded_categories``.
       The fix unions both fields, mirroring what the main channel list does.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from metatv.core.database import (
    ChannelDB,
    Database,
    EpgProgramDB,
    ProviderDB,
)
from metatv.core.epg_utils import now_utc
from metatv.core.repositories.epg import EpgRepository


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    """File-backed Database with tables created (avoids :memory: pool isolation)."""
    path = tmp_path / "test.db"
    database = Database(f"sqlite:///{path}")
    database.create_tables()
    yield database
    database.engine.dispose()


@pytest.fixture
def session(db):
    s = db.get_session()
    yield s
    s.close()


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _add_provider(session, pid, *, is_active=True, epg_url="http://e/xmltv.php",
                  epg_enabled=True):
    session.add(ProviderDB(
        id=pid, name=pid, type="xtream", url="http://e.com",
        username="u", password="p",
        is_active=is_active,
        epg_url=epg_url,
        epg_enabled=epg_enabled,
    ))
    session.flush()


def _add_channel(session, cid, provider_id, *, name="Test Channel"):
    session.add(ChannelDB(
        id=cid,
        source_id=f"src_{cid}",
        provider_id=provider_id,
        name=name,
    ))
    session.flush()


def _add_programme(session, feed_provider_id, channel_db_id, *,
                   title="Test Show", offset_start_minutes=-5,
                   offset_stop_minutes=55, upcoming=False):
    """Seed an EpgProgramDB row.

    By default the programme is currently airing (started 5m ago, ends 55m from now).
    Pass upcoming=True to make it a future programme (starts 10m from now).
    Returns the inserted EpgProgramDB object (with auto-assigned integer id).
    """
    now = now_utc()
    if upcoming:
        start = now + timedelta(minutes=10)
        stop = now + timedelta(minutes=70)
    else:
        start = now + timedelta(minutes=offset_start_minutes)
        stop = now + timedelta(minutes=offset_stop_minutes)

    prog = EpgProgramDB(
        provider_id=feed_provider_id,
        channel_epg_id=f"epg.{channel_db_id}" if channel_db_id else "epg.unmatched",
        channel_db_id=channel_db_id,
        title=title,
        start_time=start,
        stop_time=stop,
    )
    session.add(prog)
    session.flush()
    return prog


# ===========================================================================
# Part 1 / Part 2  — channel-provider scoping in repo queries
# ===========================================================================

class TestGetCurrentProgramsChannelScoping:
    """get_current_programs must respect excluded_channel_provider_ids."""

    def test_excluded_channel_provider_drops_its_programme(self, session):
        """A programme whose channel belongs to a hidden provider is excluded
        when excluded_channel_provider_ids contains that provider id."""
        _add_provider(session, "active-feed")
        _add_provider(session, "hidden-src", is_active=False)
        _add_channel(session, "ch-active", "active-feed")
        _add_channel(session, "ch-hidden", "hidden-src")

        # Both programmes come from the same active feed (cross-provider EPG match
        # is the scenario being fixed: feed "active-feed" matched a channel on
        # the now-disabled "hidden-src").
        prog_a = _add_programme(session, "active-feed", "ch-active")
        prog_h = _add_programme(session, "active-feed", "ch-hidden")

        repo = EpgRepository(session)

        # Without scoping — both come back (current behaviour, preserved when kwarg omitted)
        all_progs = repo.get_current_programs(provider_ids=["active-feed"])
        all_channel_ids = {p.channel_db_id for p in all_progs}
        assert {"ch-active", "ch-hidden"} == all_channel_ids, (
            "Without excluded_channel_provider_ids both programmes should appear"
        )

        # With scoping — only the active-channel programme survives
        scoped = repo.get_current_programs(
            provider_ids=["active-feed"],
            excluded_channel_provider_ids={"hidden-src"},
        )
        scoped_channel_ids = {p.channel_db_id for p in scoped}
        assert "ch-active" in scoped_channel_ids, "Active-channel programme must still appear"
        assert "ch-hidden" not in scoped_channel_ids, (
            "Programme matched to a hidden-source channel must be excluded"
        )

    def test_empty_excluded_set_is_noop(self, session):
        """An empty set for excluded_channel_provider_ids behaves the same as None."""
        _add_provider(session, "feed-p")
        _add_channel(session, "ch1", "feed-p")
        _add_programme(session, "feed-p", "ch1")

        repo = EpgRepository(session)
        with_none = repo.get_current_programs(provider_ids=["feed-p"])
        with_empty = repo.get_current_programs(
            provider_ids=["feed-p"],
            excluded_channel_provider_ids=set(),
        )
        assert len(with_none) == 1
        assert len(with_empty) == 1
        assert [p.channel_db_id for p in with_none] == [p.channel_db_id for p in with_empty]

    def test_null_channel_db_id_rows_already_excluded_by_existing_filter(self, session):
        """Programmes with channel_db_id IS NULL are already excluded by the existing
        isnot(None) guard; adding the JOIN filter does not regress this."""
        _add_provider(session, "feed-q")
        # No channel row — programme is unmatched (NULL channel_db_id), seeded directly
        # via the helper that accepts None for channel_db_id
        _add_programme(session, "feed-q", None)

        repo = EpgRepository(session)
        result = repo.get_current_programs(
            provider_ids=["feed-q"],
            excluded_channel_provider_ids={"feed-q"},
        )
        assert result == [], "Unmatched (NULL channel_db_id) programmes must never appear"


class TestGetLiveForWatchlistChannelScoping:
    """get_live_for_watchlist must respect excluded_channel_provider_ids."""

    def test_live_watchlist_excludes_hidden_source_channel(self, session):
        _add_provider(session, "live-feed")
        _add_provider(session, "disabled-src", is_active=False)
        _add_channel(session, "ch-ok", "live-feed")
        _add_channel(session, "ch-gone", "disabled-src")

        _add_programme(session, "live-feed", "ch-ok",   title="Watched Show")
        _add_programme(session, "live-feed", "ch-gone", title="Watched Show")

        repo = EpgRepository(session)
        scoped = repo.get_live_for_watchlist(
            patterns=["Watched Show"],
            provider_ids=["live-feed"],
            excluded_channel_provider_ids={"disabled-src"},
        )
        assert "Watched Show" in [p.title for p in scoped.get("Watched Show", [])]
        hidden_channel_ids = {p.channel_db_id for p in scoped.get("Watched Show", [])}
        assert "ch-gone" not in hidden_channel_ids, (
            "Programme on disabled-source channel must not appear in live watchlist"
        )
        assert "ch-ok" in hidden_channel_ids, "Active-source programme must remain"


class TestGetUpcomingForWatchlistChannelScoping:
    """get_upcoming_for_watchlist must respect excluded_channel_provider_ids."""

    def test_upcoming_excludes_hidden_source_channel(self, session):
        _add_provider(session, "epg-feed")
        _add_provider(session, "dead-src", is_active=False)
        _add_channel(session, "ch-future-ok",   "epg-feed")
        _add_channel(session, "ch-future-gone", "dead-src")

        _add_programme(session, "epg-feed", "ch-future-ok",   title="Upcoming Hit", upcoming=True)
        _add_programme(session, "epg-feed", "ch-future-gone", title="Upcoming Hit", upcoming=True)

        repo = EpgRepository(session)
        scoped = repo.get_upcoming_for_watchlist(
            patterns=["Upcoming Hit"],
            provider_ids=["epg-feed"],
            excluded_channel_provider_ids={"dead-src"},
        )
        channel_ids = {p.channel_db_id for p in scoped.get("Upcoming Hit", [])}
        assert "ch-future-ok"   in channel_ids, "Active-source upcoming programme must appear"
        assert "ch-future-gone" not in channel_ids, (
            "Upcoming programme on dead-source channel must be excluded"
        )

    def test_without_kwarg_both_programmes_returned(self, session):
        """Omitting excluded_channel_provider_ids preserves existing behaviour."""
        _add_provider(session, "feed-r")
        _add_provider(session, "src-r")
        _add_channel(session, "ch-r1", "feed-r")
        _add_channel(session, "ch-r2", "src-r")
        _add_programme(session, "feed-r", "ch-r1", title="Show R", upcoming=True)
        _add_programme(session, "feed-r", "ch-r2", title="Show R", upcoming=True)

        repo = EpgRepository(session)
        result = repo.get_upcoming_for_watchlist(
            patterns=["Show R"],
            provider_ids=["feed-r"],
        )
        channel_ids = {p.channel_db_id for p in result.get("Show R", [])}
        assert {"ch-r1", "ch-r2"} == channel_ids, (
            "Without scoping kwarg both programmes must be returned"
        )


class TestGetRecommendationsChannelScoping:
    """get_recommendations must respect excluded_channel_provider_ids."""

    def test_recommendations_excludes_hidden_source_channel(self, session):
        _add_provider(session, "rec-feed")
        _add_provider(session, "rec-disabled", is_active=False)
        _add_channel(session, "rec-ch-ok",   "rec-feed")
        _add_channel(session, "rec-ch-gone", "rec-disabled")

        # Seed several upcoming programmes so the channel appears in recommendations
        for i in range(3):
            _add_programme(session, "rec-feed", "rec-ch-ok",   title="Rec Series", upcoming=True)
            _add_programme(session, "rec-feed", "rec-ch-gone", title="Rec Series", upcoming=True)

        repo = EpgRepository(session)
        results = repo.get_recommendations(
            patterns=["Rec Series"],
            dismissed_ids=set(),
            provider_ids=["rec-feed"],
            excluded_channel_provider_ids={"rec-disabled"},
        )
        returned_channel_ids = {r[0] for r in results}
        assert "rec-ch-ok"   in returned_channel_ids, "Active-source channel must appear in recommendations"
        assert "rec-ch-gone" not in returned_channel_ids, (
            "Disabled-source channel must not appear in recommendations"
        )


# ===========================================================================
# Part 3  — _render_on_now must union both global exclusion config fields
# ===========================================================================

class TestRenderOnNowGlobalExclusionSet:
    """The On Now renderer must build its exclusion set from the union of
    global_filter_excluded_categories AND global_filter_excluded_prefixes,
    not just the latter.

    We test the set-construction logic directly without constructing the full
    EpgView widget (which requires a running Qt event loop and a real Database
    object in construction).
    """

    def _make_config(self, *, paused=False, categories=None, prefixes=None,
                     epg_hidden=None):
        cfg = MagicMock()
        cfg.global_filter_paused = paused
        cfg.global_filter_excluded_categories = categories or []
        cfg.global_filter_excluded_prefixes = prefixes or []
        cfg.epg_hidden_prefixes = epg_hidden or []
        return cfg

    def _compute_hidden_prefixes(self, config) -> set[str]:
        """Call the REAL production helper so a revert of the fix fails these tests."""
        from metatv.gui.epg_view import EpgView
        return EpgView._on_now_hidden_prefixes(config)

    def test_excluded_categories_included_when_filter_active(self):
        """global_filter_excluded_categories entries appear in hidden_prefixes."""
        config = self._make_config(categories=["AFR", "AR"], prefixes=["XX"])
        result = self._compute_hidden_prefixes(config)
        assert "AFR" in result, "Excluded category AFR must be in hidden_prefixes"
        assert "AR"  in result, "Excluded category AR must be in hidden_prefixes"
        assert "XX"  in result, "Excluded prefix XX must still be in hidden_prefixes"

    def test_paused_filter_clears_both_fields(self):
        """When global_filter_paused=True, neither categories nor prefixes are excluded."""
        config = self._make_config(paused=True, categories=["AFR"], prefixes=["EN"])
        result = self._compute_hidden_prefixes(config)
        # EPG-specific hidden prefixes still apply (not gated by global_filter_paused)
        assert "AFR" not in result, "Paused filter must not exclude categories"
        assert "EN"  not in result, "Paused filter must not exclude prefixes"

    def test_epg_specific_hidden_not_paused_by_global_filter(self):
        """EPG-specific epg_hidden_prefixes survive regardless of global_filter_paused."""
        config = self._make_config(paused=True, epg_hidden=["EPG_ONLY"])
        result = self._compute_hidden_prefixes(config)
        assert "EPG_ONLY" in result, (
            "EPG-specific hidden prefix must survive even when global filter is paused"
        )

    def test_only_prefixes_without_categories_bug_reproduction(self):
        """Regression: before the fix, categories were ignored and only prefixes applied.

        This test demonstrates the fixed behaviour: a category 'HI' that is in
        global_filter_excluded_categories but NOT in global_filter_excluded_prefixes
        now correctly appears in the exclusion set.
        """
        config = self._make_config(categories=["HI"], prefixes=[])  # 'HI' in cats only
        result = self._compute_hidden_prefixes(config)
        assert "HI" in result, (
            "Category 'HI' must be in hidden_prefixes even if it's not in excluded_prefixes"
        )

    def test_empty_categories_and_prefixes(self):
        """Empty lists produce an empty global exclusion set (no crash)."""
        config = self._make_config(categories=[], prefixes=[])
        result = self._compute_hidden_prefixes(config)
        assert result == set()
