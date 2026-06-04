"""Tests for compound prefix decomposition (4K-DE, SE-4K, PL 4K, etc.).

These patterns encode both a quality token and a language/platform code in the
channel-name prefix. update_detected_prefixes() must split them into
detected_prefix (language/platform) and detected_quality (quality token).
"""

import pytest
from tests.conftest import make_channel


@pytest.fixture
def repo(db_session):
    from metatv.core.repositories.channel import ChannelRepository
    return ChannelRepository(db_session)


def _prefixes(db_session, repo, name: str, api_quality: str = "") -> tuple:
    """Create a channel, run update_detected_prefixes, return (prefix, quality, region)."""
    ch = make_channel(db_session, name, quality=api_quality)
    db_session.commit()
    repo.update_detected_prefixes()
    db_session.refresh(ch)
    return ch.detected_prefix, ch.detected_quality, ch.detected_region


# ── QUALITY-LANG form (e.g. 4K-DE) ──────────────────────────────────────────

def test_4k_de_sets_lang_and_quality(db_session, repo):
    prefix, quality, region = _prefixes(db_session, repo, "4K-DE - Hanna (2019)")
    assert prefix == "DE"
    assert quality == "4K"


def test_4k_sc_sets_platform_and_quality(db_session, repo):
    prefix, quality, region = _prefixes(db_session, repo, "4K-SC - Movie Title")
    assert prefix == "SC"
    assert quality == "4K"


def test_4k_dk_sets_lang_and_quality(db_session, repo):
    prefix, quality, region = _prefixes(db_session, repo, "4K-DK - Nordic Show")
    assert prefix == "DK"
    assert quality == "4K"


def test_4k_de_with_parenthetical_region(db_session, repo):
    """Parenthetical (US) content origin lands in detected_region."""
    prefix, quality, region = _prefixes(db_session, repo, "4K-DE - Hanna (2019) (US)")
    assert prefix == "DE"
    assert quality == "4K"
    assert region == "US"


# ── LANG-QUALITY form (e.g. SE-4K) ──────────────────────────────────────────

def test_se_4k_sets_lang_and_quality(db_session, repo):
    prefix, quality, region = _prefixes(db_session, repo, "SE-4K - Breaking Bad")
    assert prefix == "SE"
    assert quality == "4K"


def test_sc_4k_sets_platform_and_quality(db_session, repo):
    prefix, quality, region = _prefixes(db_session, repo, "SC-4K - Another Title")
    assert prefix == "SC"
    assert quality == "4K"


def test_pl_4k_dash_form(db_session, repo):
    prefix, quality, region = _prefixes(db_session, repo, "PL-4K - Wiedźmin")
    assert prefix == "PL"
    assert quality == "4K"


# ── LANG QUALITY space form (e.g. PL 4K) ────────────────────────────────────

def test_pl_4k_space_form(db_session, repo):
    prefix, quality, region = _prefixes(db_session, repo, "PL 4K - Wiedźmin")
    assert prefix == "PL"
    assert quality == "4K"


# ── Bracket-before-compound form (e.g. [US] 4K-DE) ──────────────────────────

def test_bracket_before_compound_lang_wins(db_session, repo):
    """Compound lang overrides bracket — compound wins, bracket → detected_region."""
    prefix, quality, region = _prefixes(
        db_session, repo, "[US] 4K-DE - Chief of War [UHD]"
    )
    assert prefix == "DE"
    assert region == "US"


def test_bracket_before_compound_quality_from_compound(db_session, repo):
    """Quality comes from compound prefix (4K), not solely from suffix."""
    prefix, quality, _ = _prefixes(
        db_session, repo, "[US] 4K-DE - Chief of War"
    )
    assert quality == "4K"


def test_bracket_before_compound_suffix_quality_wins(db_session, repo):
    """Suffix quality ([UHD] → parsed.quality) takes priority over compound quality (4K)."""
    # parsed.quality is populated from bracket suffix when the name parser catches it.
    # For [UHD] in brackets, the name parser currently only catches it via API quality.
    # If the suffix IS parsed (e.g. bare UHD suffix without brackets), it wins.
    prefix, quality, _ = _prefixes(
        db_session, repo, "[US] 4K-DE - Chief of War UHD"  # bare UHD suffix
    )
    assert quality == "UHD"  # name suffix (tier 1) beats compound (tier 2)


# ── Guard: double quality tokens should NOT be treated as compound ────────────

def test_double_quality_tokens_not_compound(db_session, repo):
    """4K-HD: both parts are quality tokens — should NOT parse as compound."""
    prefix, quality, region = _prefixes(db_session, repo, "4K-HD - DoubleQuality")
    # Neither part should become the prefix via compound logic
    assert prefix != "HD"   # HD should not be stored as the language prefix
    # quality may come from API or be None — the important thing is the guard fired


# ── Normal channels unaffected ───────────────────────────────────────────────

def test_normal_en_channel_unaffected(db_session, repo):
    prefix, quality, region = _prefixes(db_session, repo, "EN - Breaking Bad")
    assert prefix == "EN"
    assert quality is None


def test_bracket_channel_without_compound_unaffected(db_session, repo):
    """[US] with no compound following: detected_prefix stays US."""
    prefix, quality, region = _prefixes(db_session, repo, "[US] CNN - Breaking News")
    assert prefix == "US"
    assert quality is None


def test_pure_quality_prefix_unaffected(db_session, repo):
    """4K - Movie (standalone quality prefix, no lang): stays as quality prefix."""
    prefix, quality, _ = _prefixes(db_session, repo, "4K - The Movie")
    # detected_prefix for a pure quality prefix should be "4K" (from extract_prefix)
    # and detected_quality should be "4K" (from the quality-as-prefix tier)
    assert quality == "4K"
