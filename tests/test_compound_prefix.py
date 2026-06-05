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


# ── Trailing [UK]/[US] bracket suffix as content origin ──────────────────────

def test_trailing_bracket_uk_captured_as_region(db_session, repo):
    """[UK] at the END of a compound-prefix name lands in detected_region."""
    prefix, quality, region = _prefixes(
        db_session, repo, "4K-DE - Alex Rider 2020 [UK]"
    )
    assert prefix == "DE"
    assert quality == "4K"
    assert region == "UK"


def test_trailing_bracket_us_captured_as_region(db_session, repo):
    prefix, quality, region = _prefixes(
        db_session, repo, "4K-DE - Citadel Honey Bunny · 2024 [US]"
    )
    assert prefix == "DE"
    assert quality == "4K"
    assert region == "US"


def test_trailing_bracket_does_not_affect_audio_suffix(db_session, repo):
    """[Dub] stays as audio — it is NOT treated as a region code."""
    prefix, quality, region = _prefixes(db_session, repo, "EN - Movie [Dub]")
    assert prefix == "EN"
    assert region is None  # [Dub] must not be captured as region


def test_trailing_quality_bracket_not_captured_as_region(db_session, repo):
    """[UHD] is a quality token — must NOT be captured as region."""
    prefix, quality, region = _prefixes(db_session, repo, "4K-DE - Chief of War [UHD]")
    assert region is None  # UHD is in QUALITY_TOKENS, skip


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


# ── [4K] bracket suffix quality detection ───────────────────────────────────

def test_bracket_4k_suffix_lowercase(db_session, repo):
    """EN ★ Title [4k] — lowercase bracket must set quality=4K."""
    prefix, quality, region = _prefixes(db_session, repo, "EN ★ Bambi The Reckoning - 2025 [4k]")
    assert prefix == "EN"
    assert quality == "4K"
    assert region is None


def test_bracket_4k_suffix_uppercase(db_session, repo):
    """[4K] uppercase bracket — quality=4K."""
    prefix, quality, _ = _prefixes(db_session, repo, "EN - The Movie [4K]")
    assert quality == "4K"


def test_bracket_uhd_suffix(db_session, repo):
    """[UHD] bracket suffix — quality=UHD."""
    prefix, quality, _ = _prefixes(db_session, repo, "DE - Film [UHD]")
    assert quality == "UHD"


def test_bracket_hd_suffix(db_session, repo):
    """[HD] bracket suffix — quality=HD."""
    prefix, quality, _ = _prefixes(db_session, repo, "FR - Film [HD]")
    assert quality == "HD"


def test_bracket_quality_does_not_land_in_region(db_session, repo):
    """[4K] must NOT be captured as detected_region."""
    _, quality, region = _prefixes(db_session, repo, "EN - Movie [4K]")
    assert quality == "4K"
    assert region is None


# ── Exhaustive 4K-variant coverage ──────────────────────────────────────────
# These parametrized cases ensure every real-world 4K encoding we know about
# is caught. Add new rows here when new variants are discovered in the DB.

import pytest

@pytest.mark.parametrize("channel_name,exp_quality,exp_prefix", [
    # 4K-XX prefix (compound: quality then lang)
    ("4K-SC - Anniversary (2025)",      "4K",  "SC"),
    ("4K-DE - Hanna (2019)",            "4K",  "DE"),
    ("4K-DK - Nordic Show",             "4K",  "DK"),
    ("4K-SE - Movie",                   "4K",  "SE"),
    ("4K-NO - Film",                    "4K",  "NO"),
    ("4K-PL - Film",                    "4K",  "PL"),
    ("4K-US - Title",                   "4K",  "US"),
    ("4K-UK - Title",                   "4K",  "UK"),
    # XX-4K prefix (compound: lang then quality)
    ("SC-4K - Another Title",           "4K",  "SC"),
    ("SE-4K - Breaking Bad",            "4K",  "SE"),
    ("PL-4K - Wiedźmin",               "4K",  "PL"),
    # XX 4K space form
    ("PL 4K - Wiedźmin",               "4K",  "PL"),
    # [4K] bracket suffix (bare name, various casings)
    ("EN - Movie [4K]",                 "4K",  "EN"),
    ("EN ★ Bambi [4k]",                "4K",  "EN"),
    ("EN - Title [4K] (2025)",          "4K",  "EN"),
    # Bare suffix (no brackets)
    ("EN - Movie 4K",                   "4K",  "EN"),
    ("DE - Film UHD",                   "UHD", "DE"),
    # Standalone 4K prefix (no lang code)
    ("4K - The Movie",                  "4K",  None),
    # CAM source indicator — bare suffix
    ("EN ★ Movie CAM",                  "CAM", "EN"),
])
def test_4k_variants_exhaustive(db_session, repo, channel_name, exp_quality, exp_prefix):
    """Every known 4K-encoding variant must produce the expected detected_quality."""
    prefix, quality, _ = _prefixes(db_session, repo, channel_name)
    assert quality == exp_quality, f"{channel_name!r}: expected quality={exp_quality!r}, got {quality!r}"
    if exp_prefix is not None:
        assert prefix == exp_prefix, f"{channel_name!r}: expected prefix={exp_prefix!r}, got {prefix!r}"


# ── CAM / camera-rip bracket variants ────────────────────────────────────────

@pytest.mark.parametrize("channel_name", [
    "FR ★ Nuremberg - 2025 [Cam]",
    "EN ★ Movie [CAM]",
    "EN - Movie [SD/CAM]",
    "EN - Movie [sd/cam]",
    "EN ★ Michael - 2026 [CAM-VERSION]",
    "EN ★ Avatar - 2025 [CAM-VERSON]",
    "FR ★ Zootopie 2 - 2025 [Version CAM]",
    "DE ★ Film - 2025 [V.Cam]",
    "EN ★ Title - 2025 [CAM VERSION]",
])
def test_cam_variants_all_yield_cam_quality(db_session, repo, channel_name):
    """Every cam-rip bracket variant must produce detected_quality='CAM'."""
    _, quality, region = _prefixes(db_session, repo, channel_name)
    assert quality == "CAM", f"{channel_name!r}: expected quality='CAM', got {quality!r}"
    assert region is None, f"{channel_name!r}: cam bracket must not land in detected_region, got {region!r}"
