"""Tests for compound prefix decomposition and bracket classification.

Covers _classify_bracket() directly (so the helper is independently tested,
not only via the full parse_channel_name() pipeline), plus compound prefix
patterns (4K-DE, SE-4K, PL 4K) and all known bracket-suffix variants.
"""

import pytest
from tests.conftest import make_channel
from metatv.core.channel_name_utils import _classify_bracket


# ── _classify_bracket() unit tests ───────────────────────────────────────────
# Test the helper directly so drift between the two call sites is caught here,
# not only discovered through pipeline tests.

@pytest.mark.parametrize("content,exp_kind,exp_value", [
    # Audio
    ("MULTI",        "audio",   "Multi"),
    ("MUTI",         "audio",   "Multi"),   # common typo for "Multi" (missing L)
    ("MUTI-SUB",     "audio",   "Multi"),
    ("DUB",          "audio",   "Dub"),
    ("SUB",          "audio",   "Sub"),
    # Quality aliases
    ("SD/CAM",       "quality", "CAM"),
    ("CAM-VERSION",  "quality", "CAM"),
    # Bare quality tokens
    ("4K",           "quality", "4K"),
    ("UHD",          "quality", "UHD"),
    ("CAM",          "quality", "CAM"),
    # Full language names
    ("SPANISH",      "origin",  "ES"),
    ("HINDI",        "origin",  "HI"),
    ("FRENCH",       "origin",  "FR"),
    ("KOREAN",       "origin",  "KR"),
    # Platform codes
    ("ASTRO",        "origin",  "ASTRO"),
    ("F1TV",         "origin",  "F1TV"),
    # Short origin codes (2-3 alpha)
    ("UK",           "origin",  "UK"),
    ("US",           "origin",  "US"),
    ("DE",           "origin",  "DE"),
    # Unknown — stays unclassified
    ("RACE",         "unknown", "RACE"),
    ("FP1",          "unknown", "FP1"),
    ("MAIN CARD",    "unknown", "MAIN CARD"),
])
def test_classify_bracket(content, exp_kind, exp_value):
    bc = _classify_bracket(content)
    assert bc.kind == exp_kind, f"_classify_bracket({content!r}): kind={bc.kind!r}, want {exp_kind!r}"
    assert bc.value == exp_value, f"_classify_bracket({content!r}): value={bc.value!r}, want {exp_value!r}"


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


def _all_fields(db_session, repo, name: str, api_quality: str = "") -> tuple:
    """Like _prefixes but also returns detected_title and detected_year."""
    ch = make_channel(db_session, name, quality=api_quality)
    db_session.commit()
    repo.update_detected_prefixes()
    db_session.refresh(ch)
    return ch.detected_prefix, ch.detected_quality, ch.detected_region, ch.detected_title, ch.detected_year


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
    """4K - Movie (standalone quality prefix, no lang): quality captured, prefix cleared."""
    prefix, quality, _ = _prefixes(db_session, repo, "4K - The Movie")
    assert quality == "4K"
    assert prefix is None  # Guard #3 clears quality tokens from detected_prefix


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
    # CAM source indicator — must be bracketed, not bare
    # (B0 fix: bare CAM/LIVE/RAW no longer stripped from names)
    ("EN ★ Movie [CAM]",                "CAM", "EN"),
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


# ── Full language name bracket → detected_region ─────────────────────────────

@pytest.mark.parametrize("channel_name,exp_region", [
    ("EN ★ 27 Nights - 2025 [SPANISH]",                   "ES"),
    ("EN ★ A Place to Fight For - 2023 [FRENCH] [4k]",    "FR"),
    ("EN ★ Bison Kaalamaadan - 2025 [HINDI]",             "HI"),
    ("EN ★ Attack 13 - 2025 [KOREAN]",                    "KR"),
    ("EN ★ 10 Days of a Bad Man - 2023 [Turkish] [4k]",   "TR"),
    ("EN - Movie [ARABIC]",                               "AR"),
    ("EN - Film [GERMAN]",                                "DE"),
    ("EN - Title [PORTUGUESE]",                           "PT"),
])
def test_full_language_name_bracket_sets_region(db_session, repo, channel_name, exp_region):
    """Full language name in bracket suffix maps to 2-letter code in detected_region."""
    prefix, _, region = _prefixes(db_session, repo, channel_name)
    assert region == exp_region, f"{channel_name!r}: expected region={exp_region!r}, got {region!r}"
    assert prefix == "EN", f"{channel_name!r}: prefix should still be EN, got {prefix!r}"


def test_language_bracket_plus_quality_both_captured(db_session, repo):
    """[FRENCH] [4k] — both language and quality captured correctly."""
    prefix, quality, region = _prefixes(
        db_session, repo, "EN ★ A Place to Fight For - 2023 [FRENCH] [4k]"
    )
    assert region == "FR"
    assert quality == "4K"


# ── Platform code brackets → detected_region ─────────────────────────────────

def test_astro_bracket_sets_region(db_session, repo):
    """[ASTRO] platform bracket → detected_region = 'ASTRO'."""
    _, _, region = _prefixes(db_session, repo, "MY| AOD 351 [ASTRO]")
    assert region == "ASTRO"


def test_f1tv_bracket_sets_region(db_session, repo):
    """[F1TV] platform bracket → detected_region = 'F1TV'."""
    _, _, region = _prefixes(db_session, repo, "ES - Carrera F1 GP Monaco 2024 [F1TV]")
    assert region == "F1TV"


# ── Regression: numeric prefix guard ─────────────────────────────────────────
# extract_prefix() splits on separators and can yield numeric codes like "300"
# from "300  - 2007". These are provider-internal category numbers and must NOT
# be stored as detected_prefix (they were previously hidden by the old render-time
# parse_channel_name() call which uses a stricter [A-Z]-first regex).

def test_numeric_prefix_not_stored(db_session, repo):
    """'300  - 2007': purely-numeric extract_prefix result must not land in detected_prefix."""
    prefix, quality, region, title, year = _all_fields(db_session, repo, "300  - 2007")
    assert prefix is None, f"numeric prefix should be None, got {prefix!r}"
    assert title == "300", f"title should be '300', got {title!r}"
    assert year == "2007", f"year should be '2007', got {year!r}"


# ── Regression: Guard-3 must clear prefix for quality tokens ─────────────────
# Before the fix, "4K" extracted by extract_prefix was moved to quality by Guard #3
# but not cleared from prefix → detected_prefix="4K" AND detected_quality="4K".

def test_quality_pipe_prefix_not_stored_as_display_prefix(db_session, repo):
    """'4K| Title': quality token as separator prefix must clear detected_prefix."""
    prefix, quality, _, title, _ = _all_fields(db_session, repo, "4K| SKY SPORTS UHD")
    assert prefix is None, f"quality-as-prefix should clear detected_prefix, got {prefix!r}"
    assert quality is not None, "quality should be captured"


# ── New: [4K] [REGION] bracket format ────────────────────────────────────────
# Providers send "[4K] [US] Title [4K] 2026" — two bracket groups at start,
# first is quality, second is region. Previously both stayed in detected_title.

def test_quality_bracket_then_region_bracket(db_session, repo):
    """'[4K] [US] A Knight... [4K] (2026)': prefix=US, quality=4K, title stripped."""
    prefix, quality, _, title, year = _all_fields(
        db_session, repo, "[4K] [US] A Knight of the Seven Kingdoms [4K] (2026)"
    )
    assert prefix == "US", f"expected prefix='US', got {prefix!r}"
    assert quality == "4K", f"expected quality='4K', got {quality!r}"
    assert title == "A Knight of the Seven Kingdoms", f"title wrong: {title!r}"
    assert year == "2026", f"year wrong: {year!r}"


def test_uhd_bracket_then_region_bracket(db_session, repo):
    """'[UHD] [SC] Movie Title': alpha quality bracket + region bracket."""
    prefix, quality, _, title, _ = _all_fields(
        db_session, repo, "[UHD] [SC] Movie Title"
    )
    assert prefix == "SC", f"expected prefix='SC', got {prefix!r}"
    assert quality == "UHD", f"expected quality='UHD', got {quality!r}"
    assert title == "Movie Title", f"title wrong: {title!r}"


# ── New: digit-starting prefix title stripping ───────────────────────────────
# "24/7 ★ Trust Me": extract_prefix correctly extracts "24/7" as a platform prefix,
# but parse_channel_name's _SEPARATOR_RE (requires [A-Z] first char) can't strip it.
# update_detected_prefixes must strip it manually so detected_title = "Trust Me".

def test_247_platform_prefix_title_stripped(db_session, repo):
    """'24/7 ★ Trust Me': platform prefix detected, title stripped to 'Trust Me'."""
    prefix, _, _, title, _ = _all_fields(db_session, repo, "24/7 ★ Trust Me")
    assert prefix == "24/7", f"expected prefix='24/7', got {prefix!r}"
    assert title == "Trust Me", f"title should be 'Trust Me' (not '24/7 ★ Trust Me'), got {title!r}"


def test_unrecognised_sports_session_stays_in_title(db_session, repo):
    """[RACE] is not a known bracket type — stays in the bare title, not stored."""
    prefix, quality, region = _prefixes(
        db_session, repo, "ES - Formula 1 - 2024 - Austria [RACE]"
    )
    assert region is None
    assert quality is None
