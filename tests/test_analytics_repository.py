"""Behavioral tests for AnalyticsRepository — the Sources editor's Analytics tab data:
title overlap by content_key, guide coverage, server addresses, prefix worklist.
"""

import tempfile
from pathlib import Path

import pytest

from metatv.core.database import Database, ChannelDB, ProviderDB
from metatv.core.repositories import RepositoryFactory


@pytest.fixture
def file_db():
    """File-backed SQLite Database for testing (required for connection pooling)."""
    tmpfile = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmpfile.close()
    db_path = tmpfile.name

    db = Database(f"sqlite:///{db_path}")
    db.create_tables()
    yield db
    db.close()

    # Clean up
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def session(file_db):
    """Fresh session for each test."""
    session = file_db.get_session()
    yield session
    session.close()


def _make_provider(session, provider_id: str, name: str) -> ProviderDB:
    """Create a test provider."""
    prov = ProviderDB(
        id=provider_id,
        name=name,
        type="xtream",
        url="http://example.com",
        username="test",
        password="test",
    )
    session.add(prov)
    session.flush()
    return prov


def _make_channel(
    session,
    provider_id: str,
    name: str,
    detected_title: str | None = None,
    detected_quality: str | None = None,
    detected_region: str | None = None,
    detected_prefix: str | None = None,
    media_type: str = "live",
    is_hidden: bool = False,
    is_adult: bool = False,
) -> ChannelDB:
    """Create a test channel."""
    import uuid
    ch = ChannelDB(
        id=str(uuid.uuid4()),
        source_id=str(uuid.uuid4()),
        provider_id=provider_id,
        name=name,
        detected_title=detected_title,
        detected_quality=detected_quality,
        detected_region=detected_region,
        detected_prefix=detected_prefix,
        media_type=media_type,
        is_hidden=is_hidden,
        is_adult=is_adult,
        stream_url="http://example.com/stream",
    )
    session.add(ch)
    session.flush()
    return ch


def _titled(session, provider_id, key, media_type="movie", name=None):
    """A channel carrying a content_key — the identity every collapse uses."""
    ch = _make_channel(session, provider_id, name or f"{key}@{provider_id}", media_type=media_type)
    ch.content_key = key
    session.flush()
    return ch


class TestTitleOverlap:
    """Same title = stored content_key, every media type, every source at once."""

    def test_totals_only_here_and_shared(self, session):
        for pid in ("a", "b", "c"):
            _make_provider(session, pid, pid.upper())
        # a: alpha beta gamma (+ a second copy of alpha); b: beta gamma delta; c: gamma
        for key in ("alpha", "beta", "gamma"):
            _titled(session, "a", key)
        _titled(session, "a", "alpha", name="alpha 4K@a")
        for key in ("beta", "gamma", "delta"):
            _titled(session, "b", key)
        _titled(session, "c", "gamma")
        _titled(session, "a", "news", media_type="live")
        _titled(session, "b", "news", media_type="live")
        session.commit()

        o = RepositoryFactory(session).analytics.title_overlap()

        assert o.totals[("a", "movie")] == 3, "two copies of alpha are one title"
        assert o.only[("a", "movie")] == 1          # alpha
        assert o.only[("b", "movie")] == 1          # delta
        assert ("c", "movie") not in o.only         # gamma is everywhere
        assert o.shared[("a", "b", "movie")] == 2   # beta, gamma
        assert o.shared[("a", "c", "movie")] == 1   # gamma
        assert o.shared[("a", "b", "live")] == 1, "live channels compare by title too"
        assert len(o.only_ids["a"]) == 2, "both copies of the only-here title are browsable"

    def test_a_row_without_a_key_is_its_own_title(self, session):
        _make_provider(session, "a", "A")
        _make_provider(session, "b", "B")
        _make_channel(session, "a", "untitled", media_type="movie")
        _make_channel(session, "b", "untitled", media_type="movie")
        session.commit()
        o = RepositoryFactory(session).analytics.title_overlap()
        assert o.only[("a", "movie")] == 1 and o.only[("b", "movie")] == 1

    def test_disabled_and_expired_sources_stay_in(self, session):
        from datetime import datetime, timedelta
        _make_provider(session, "a", "A")
        off = _make_provider(session, "b", "B")
        off.is_active = False
        off.account_exp_date = datetime.now() - timedelta(days=1)
        _titled(session, "a", "alpha")
        _titled(session, "b", "alpha")
        session.commit()
        o = RepositoryFactory(session).analytics.title_overlap()
        b = next(s for s in o.sources if s.id == "b")
        assert b.is_expired and not b.is_active
        assert o.shared[("a", "b", "movie")] == 1

    def test_channels_of_a_deleted_source_are_ignored(self, session):
        _make_provider(session, "a", "A")
        _titled(session, "a", "alpha")
        _titled(session, "gone", "alpha")   # ledger F60: provider row no longer exists
        session.commit()
        o = RepositoryFactory(session).analytics.title_overlap()
        assert o.only[("a", "movie")] == 1
        assert [s.id for s in o.sources] == ["a"]


class TestGuideCoverage:
    def test_counts_this_sources_channels_from_any_feed(self, session):
        from datetime import datetime, timedelta
        from metatv.core.database import EpgProgramDB
        _make_provider(session, "a", "A")
        _make_provider(session, "b", "B")
        mine = [_make_channel(session, "a", f"live {i}") for i in range(4)]
        theirs = _make_channel(session, "b", "other live")
        start = datetime(2026, 11, 1, 20, 0)
        rows = [("b", mine[0].id), ("a", mine[1].id), ("a", theirs.id)]   # a's feed also matches b
        for feed, cid in rows:
            session.add(EpgProgramDB(provider_id=feed, channel_epg_id="x", channel_db_id=cid,
                                     channel_name="x", title="Show", start_time=start,
                                     stop_time=start + timedelta(hours=1)))
        session.commit()
        g = RepositoryFactory(session).analytics.guide_coverage("a")
        assert (g.live_channels, g.with_guide) == (4, 2)
        assert g.guide_until == start + timedelta(hours=1)


class TestServerAddresses:
    def test_recent_attempts_rank_best_first(self, session):
        prov = _make_provider(session, "a", "A")
        attempt = lambda ok, ms=None: {"timestamp": "2026-10-30T10:00:00", "success": ok,
                                       "response_time_ms": ms, "host_at_fault": True}
        prov.urls = [
            {"url": "http://slow.example:80", "success_count": 9, "failure_count": 1,
             "recent_attempts": [attempt(True, 3000), attempt(False)]},
            {"url": "http://fast.example:80", "success_count": 5, "failure_count": 0,
             "recent_attempts": [attempt(True, 900), attempt(True, 1100)]},
            {"url": "http://never.example:80", "success_count": 0, "failure_count": 0},
        ]
        session.commit()
        out = RepositoryFactory(session).analytics.server_addresses("a")
        assert [a.url for a in out][:2] == ["http://fast.example:80", "http://slow.example:80"]
        assert (out[0].tried, out[0].worked, out[0].median_latency_ms) == (2, 2, 1000)
        assert (out[1].tried, out[1].worked) == (2, 1), "recent history, not the lifetime 9 of 10"
        assert out[2].tried == 0


class TestUnrecognizedPrefixes:
    """Test unrecognized prefix detection."""

    def test_samples_come_from_this_source(self, session):
        """The samples used to come from any source carrying the prefix."""
        _make_provider(session, "p1", "One")
        _make_provider(session, "p2", "Two")
        _make_channel(session, "p2", "XX| from two", detected_prefix="XX")
        _make_channel(session, "p1", "XX| from one", detected_prefix="XX")
        session.commit()
        stats = RepositoryFactory(session).analytics.unrecognized_prefixes("p1")
        assert [(s.prefix, s.count, s.sample_names) for s in stats] == [("XX", 1, ["XX| from one"])]

    def test_unrecognized_prefixes_filters_recognized(self, session):
        """Prefixes in lexicon should not be returned."""
        _make_provider(session, "p1", "Provider")

        # EN is recognized
        _make_channel(session, "p1", "recognized", detected_prefix="EN")
        # XX is not recognized
        _make_channel(session, "p1", "unrecognized_1", detected_prefix="XX")
        _make_channel(session, "p1", "unrecognized_2", detected_prefix="XX")
        _make_channel(session, "p1", "unrecognized_3", detected_prefix="XX")

        session.commit()

        repos = RepositoryFactory(session)
        prefixes = repos.analytics.unrecognized_prefixes("p1")

        # Should only have XX, not EN
        assert len(prefixes) == 1
        assert prefixes[0].prefix == "XX"
        assert prefixes[0].count == 3
        assert prefixes[0].is_recognized == False

    def test_unrecognized_prefixes_sample_names(self, session):
        """Verify sample names are extracted correctly."""
        _make_provider(session, "p1", "Provider")

        # Create 5 channels with same unrecognized prefix
        for i in range(5):
            _make_channel(session, "p1", f"channel_name_{i}", detected_prefix="UNKNOWN")

        session.commit()

        repos = RepositoryFactory(session)
        prefixes = repos.analytics.unrecognized_prefixes("p1")

        assert len(prefixes) == 1
        assert len(prefixes[0].sample_names) == 5
        assert all("channel_name_" in name for name in prefixes[0].sample_names)

    def test_unrecognized_prefixes_global(self, session):
        """Test global unrecognized prefixes across all providers."""
        _make_provider(session, "p1", "Provider 1")
        _make_provider(session, "p2", "Provider 2")

        _make_channel(session, "p1", "ch1", detected_prefix="XX")
        _make_channel(session, "p1", "ch2", detected_prefix="XX")
        _make_channel(session, "p2", "ch3", detected_prefix="YY")

        session.commit()

        repos = RepositoryFactory(session)
        prefixes = repos.analytics.unrecognized_prefixes(provider_id=None)

        # Should have both XX and YY
        prefix_dict = {p.prefix: p.count for p in prefixes}
        assert prefix_dict["XX"] == 2
        assert prefix_dict["YY"] == 1
