"""Behavioral tests for AnalyticsRepository.

Tests the core analytics business logic: overlap matrix set math, fingerprint
histograms, unique content filtering, and prefix recognition.
"""

import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from metatv.core.database import Base, Database, ChannelDB, ProviderDB
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


class TestOverlapMatrix:
    """Test overlap matrix computation."""

    def test_overlap_matrix_basic(self, session):
        """Basic set math: A={alpha,beta,gamma}, B={beta,gamma,delta}."""
        # Setup
        _make_provider(session, "a", "Provider A")
        _make_provider(session, "b", "Provider B")

        _make_channel(session, "a", "alpha")
        _make_channel(session, "a", "beta")
        _make_channel(session, "a", "gamma")

        _make_channel(session, "b", "beta")
        _make_channel(session, "b", "gamma")
        _make_channel(session, "b", "delta")

        session.commit()

        # Test
        repos = RepositoryFactory(session)
        matrix = repos.analytics.overlap_matrix(["a", "b"], "live")

        # Find A→B pair
        a_to_b = next((m for m in matrix if m.provider_a_id == "a" and m.provider_b_id == "b"), None)
        assert a_to_b is not None
        assert a_to_b.shared == 2  # beta, gamma
        assert a_to_b.a_only == 1  # alpha
        assert a_to_b.b_only == 1  # delta
        assert abs(a_to_b.jaccard - 0.5) < 0.001  # 2/4 = 0.5

    def test_overlap_matrix_three_providers(self, session):
        """Test N×N matrix with 3 providers (9 pairs)."""
        _make_provider(session, "p1", "Provider 1")
        _make_provider(session, "p2", "Provider 2")
        _make_provider(session, "p3", "Provider 3")

        # Each provider has 2 channels
        _make_channel(session, "p1", "title1")
        _make_channel(session, "p1", "title2")
        _make_channel(session, "p2", "title1")
        _make_channel(session, "p2", "title3")
        _make_channel(session, "p3", "title3")
        _make_channel(session, "p3", "title4")

        session.commit()

        repos = RepositoryFactory(session)
        matrix = repos.analytics.overlap_matrix(["p1", "p2", "p3"], "live")

        # Should have 9 pairs (3×3)
        assert len(matrix) == 9

        # Identity pairs should have 100% overlap
        for provider_id in ["p1", "p2", "p3"]:
            identity = next(
                (m for m in matrix if m.provider_a_id == provider_id and m.provider_b_id == provider_id),
                None
            )
            assert identity is not None
            assert abs(identity.jaccard - 1.0) < 0.001  # 100%


class TestSourceFingerprint:
    """Test source fingerprint computation."""

    def test_source_fingerprint_counts(self, session):
        """Verify counts and visible counts."""
        _make_provider(session, "p1", "Test Provider")

        # Create 100 live, 50 movie, 25 series
        for i in range(100):
            _make_channel(session, "p1", f"live_{i}", media_type="live")
        for i in range(50):
            _make_channel(session, "p1", f"movie_{i}", media_type="movie")
        for i in range(25):
            _make_channel(session, "p1", f"series_{i}", media_type="series")

        # Hide 10 live and 5 movie
        live_rows = session.query(ChannelDB).filter_by(provider_id="p1", media_type="live").limit(10).all()
        for row in live_rows:
            row.is_hidden = True
        movie_rows = session.query(ChannelDB).filter_by(provider_id="p1", media_type="movie").limit(5).all()
        for row in movie_rows:
            row.is_hidden = True

        session.commit()

        repos = RepositoryFactory(session)
        fp = repos.analytics.source_fingerprint("p1")

        # Verify counts
        assert fp.live_count == 100
        assert fp.movie_count == 50
        assert fp.series_count == 25
        assert fp.total_count == 175

        # Verify visible counts
        assert fp.live_visible == 90
        assert fp.movie_visible == 45
        assert fp.series_visible == 25
        assert fp.total_visible == 160

    def test_source_fingerprint_quality_histogram(self, session):
        """Verify quality histogram computation."""
        _make_provider(session, "p1", "Test Provider")

        # Create channels with different qualities
        _make_channel(session, "p1", "hd_1", detected_quality="HD")
        _make_channel(session, "p1", "hd_2", detected_quality="HD")
        _make_channel(session, "p1", "fhd_1", detected_quality="FHD")
        _make_channel(session, "p1", "4k_1", detected_quality="4K")
        _make_channel(session, "p1", "none")  # No quality

        session.commit()

        repos = RepositoryFactory(session)
        fp = repos.analytics.source_fingerprint("p1")

        assert fp.quality_histogram["HD"] == 2
        assert fp.quality_histogram["FHD"] == 1
        assert fp.quality_histogram["4K"] == 1
        assert "none" not in fp.quality_histogram  # Should not have empty string key

    def test_source_fingerprint_region_histogram(self, session):
        """Verify region histogram computation."""
        _make_provider(session, "p1", "Test Provider")

        _make_channel(session, "p1", "en_1", detected_region="EN")
        _make_channel(session, "p1", "en_2", detected_region="EN")
        _make_channel(session, "p1", "fr_1", detected_region="FR")
        _make_channel(session, "p1", "none")  # No region

        session.commit()

        repos = RepositoryFactory(session)
        fp = repos.analytics.source_fingerprint("p1")

        assert fp.region_histogram["EN"] == 2
        assert fp.region_histogram["FR"] == 1

    def test_source_fingerprint_prefix_recognition(self, session):
        """Verify recognized vs unrecognized prefix counting."""
        _make_provider(session, "p1", "Test Provider")

        # EN is recognized (in lexicon)
        _make_channel(session, "p1", "recognized", detected_prefix="EN")
        # XX is not recognized
        _make_channel(session, "p1", "unrecognized", detected_prefix="XX")
        # No prefix
        _make_channel(session, "p1", "no_prefix")

        session.commit()

        repos = RepositoryFactory(session)
        fp = repos.analytics.source_fingerprint("p1")

        assert fp.recognized_count == 1
        assert fp.unrecognized_count == 1
        # recognized_pct = 1/3 = 33.3%
        assert 33.0 < fp.recognized_pct < 34.0


class TestUniqueTitles:
    """Test unique content drill-down."""

    def test_unique_titles_basic(self, session):
        """Provider A={alpha,beta,gamma}, B={beta,gamma,delta}; A-only={alpha}."""
        _make_provider(session, "a", "Provider A")
        _make_provider(session, "b", "Provider B")

        _make_channel(session, "a", "alpha")
        _make_channel(session, "a", "beta")
        _make_channel(session, "a", "gamma")

        _make_channel(session, "b", "beta")
        _make_channel(session, "b", "gamma")
        _make_channel(session, "b", "delta")

        session.commit()

        repos = RepositoryFactory(session)
        unique = repos.analytics.unique_titles("a", "live")

        # Should have exactly 1 unique title
        assert len(unique) == 1
        assert unique[0].name == "alpha"

    def test_unique_titles_ignores_hidden(self, session):
        """Hidden channels don't participate in overlap computation."""
        _make_provider(session, "a", "Provider A")
        _make_provider(session, "b", "Provider B")

        _make_channel(session, "a", "visible_a")
        _make_channel(session, "a", "hidden_a", is_hidden=True)

        _make_channel(session, "b", "visible_b")

        session.commit()

        repos = RepositoryFactory(session)
        unique_a = repos.analytics.unique_titles("a", "live")

        # Only visible channels are returned (hidden=False filter)
        assert len(unique_a) == 1
        assert unique_a[0].name == "visible_a"


class TestUnrecognizedPrefixes:
    """Test unrecognized prefix detection."""

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
