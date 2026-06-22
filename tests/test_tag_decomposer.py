"""Tests for metatv.core.tag_decomposer — Tags Slice T2 (DR-0005/DR-0006).

Pure-function tests: no DB, no Qt.  Uses a real Config() (the autouse
``_isolate_user_config`` fixture ensures it writes to a throwaway tmp dir,
not the developer's real config).

The tests verify:
- Real compound strings produce the expected typed (type, value, confidence) triples.
- Each classifier reuse point (region / language / platform / quality / genre) works.
- Unrecognised tokens are DROPPED, not mis-typed.
- No duplicate (type, value) pairs are emitted.
- Decade extraction works for name_parse feeder.
- The ``decompose_name_parse`` helper promotes pre-typed fields correctly.
- The ``genre`` and ``epg`` feeders normalize genre strings.

DR-0006 confidence rules verified:
- EN → exactly one tag (language:English); no region tag is emitted.
- FR → language:French (high confidence) + region:FR (lower confidence),
  with conf(language) > conf(region).
- US → region:US (high) + language:English (lower).
- ES → language:Spanish (high) + region:ES (very low, CONF_WEAK_PRIOR).
- LAT → (language, "Latin American Spanish", …) — distinct value, NOT "Spanish".
- AR → language:Arabic — NOT region:Argentina.
- ARG → region:ARG (Argentina).
"""

import pytest

from metatv.core.channel_name_utils import CONF_DENOTED, CONF_STRONG_PRIOR, CONF_WEAK_PRIOR
from metatv.core.config import Config
from metatv.core.tag_decomposer import decompose, decompose_name_parse


# ── Shared fixture ──────────────────────────────────────────────────────────── #

@pytest.fixture(scope="module")
def cfg():
    """A default Config() with the base prefix/quality/platform groups."""
    return Config()


# --------------------------------------------------------------------------- #
#  DR-0006 confidence + dual-facet rules — the new tests                       #
# --------------------------------------------------------------------------- #

class TestDR006ConfidenceRules:
    """Verify the DR-0006 capture-more + confidence rules exactly."""

    # ── EN: language only, NO region (no place called "EN") ─────────────────

    def test_en_exactly_one_tag(self, cfg):
        """EN → exactly one tag (language:English); no region."""
        tags = decompose("provider_category", "EN", config=cfg)
        assert len(tags) == 1, f"EN should produce exactly one tag, got {tags}"

    def test_en_is_language_english(self, cfg):
        """EN → (language, English, …)."""
        tags = decompose("provider_category", "EN", config=cfg)
        assert tags[0][0] == "language"
        assert tags[0][1] == "English"

    def test_en_no_region_tag(self, cfg):
        """EN must not produce a region tag — no place is called 'EN'."""
        tags = decompose("provider_category", "EN", config=cfg)
        assert not any(t == "region" for t, _, _ in tags), (
            f"EN emitted a region tag — bug: {tags}"
        )

    # ── FR: language (high) + region:France (lower) ─────────────────────────

    def test_fr_has_language_and_region(self, cfg):
        """FR → both language:French and region:FR."""
        tags = decompose("provider_category", "FR", config=cfg)
        types = {t for t, _, _ in tags}
        assert "language" in types, f"FR missing language tag: {tags}"
        assert "region" in types, f"FR missing region prior: {tags}"

    def test_fr_language_value_is_french(self, cfg):
        """FR language tag value must be 'French'."""
        tags = decompose("provider_category", "FR", config=cfg)
        lang_val = next((v for t, v, _ in tags if t == "language"), None)
        assert lang_val == "French", f"Expected French, got {lang_val!r}"

    def test_fr_region_value_is_fr(self, cfg):
        """FR region tag value must be 'FR' (the code, not a full name)."""
        tags = decompose("provider_category", "FR", config=cfg)
        region_val = next((v for t, v, _ in tags if t == "region"), None)
        assert region_val == "FR", f"Expected FR, got {region_val!r}"

    def test_fr_language_confidence_higher_than_region(self, cfg):
        """FR: language confidence must exceed region confidence."""
        tags = decompose("provider_category", "FR", config=cfg)
        lang_conf = next((c for t, _, c in tags if t == "language"), None)
        region_conf = next((c for t, _, c in tags if t == "region"), None)
        assert lang_conf is not None and region_conf is not None
        assert lang_conf > region_conf, (
            f"FR language conf ({lang_conf}) should exceed region conf ({region_conf})"
        )

    def test_fr_language_is_denoted(self, cfg):
        """FR language confidence must be CONF_DENOTED (~0.9)."""
        tags = decompose("provider_category", "FR", config=cfg)
        lang_conf = next((c for t, _, c in tags if t == "language"), None)
        assert lang_conf == CONF_DENOTED

    def test_fr_region_is_strong_prior(self, cfg):
        """FR region confidence must be CONF_STRONG_PRIOR (~0.3)."""
        tags = decompose("provider_category", "FR", config=cfg)
        region_conf = next((c for t, _, c in tags if t == "region"), None)
        assert region_conf == CONF_STRONG_PRIOR

    # ── US: region (high) + language:English (lower) ────────────────────────

    def test_us_has_region_and_language(self, cfg):
        """US → both region:US and language:English."""
        tags = decompose("provider_category", "US", config=cfg)
        types = {t for t, _, _ in tags}
        assert "region" in types, f"US missing region tag: {tags}"
        assert "language" in types, f"US missing language prior: {tags}"

    def test_us_region_is_us(self, cfg):
        """US region tag value must be 'US'."""
        tags = decompose("provider_category", "US", config=cfg)
        region_val = next((v for t, v, _ in tags if t == "region"), None)
        assert region_val == "US"

    def test_us_language_is_english(self, cfg):
        """US language tag value must be 'English'."""
        tags = decompose("provider_category", "US", config=cfg)
        lang_val = next((v for t, v, _ in tags if t == "language"), None)
        assert lang_val == "English"

    def test_us_region_confidence_higher_than_language(self, cfg):
        """US: region confidence must exceed language confidence."""
        tags = decompose("provider_category", "US", config=cfg)
        region_conf = next((c for t, _, c in tags if t == "region"), None)
        lang_conf = next((c for t, _, c in tags if t == "language"), None)
        assert region_conf is not None and lang_conf is not None
        assert region_conf > lang_conf, (
            f"US region conf ({region_conf}) should exceed language conf ({lang_conf})"
        )

    # ── ES: language:Spanish (high) + region:ES (very low) ──────────────────

    def test_es_has_language_spanish(self, cfg):
        """ES → language:Spanish."""
        tags = decompose("provider_category", "ES", config=cfg)
        assert any(t == "language" and v == "Spanish" for t, v, _ in tags), (
            f"ES missing language:Spanish: {tags}"
        )

    def test_es_has_region_spain(self, cfg):
        """ES → region:ES (Spain as a very-low-confidence prior)."""
        tags = decompose("provider_category", "ES", config=cfg)
        assert any(t == "region" and v == "ES" for t, v, _ in tags), (
            f"ES missing region:ES: {tags}"
        )

    def test_es_region_is_weak_prior(self, cfg):
        """ES region confidence must be CONF_WEAK_PRIOR (very low — Latin America dwarfs Spain)."""
        tags = decompose("provider_category", "ES", config=cfg)
        region_conf = next((c for t, _, c in tags if t == "region"), None)
        assert region_conf == CONF_WEAK_PRIOR, (
            f"ES region should be CONF_WEAK_PRIOR ({CONF_WEAK_PRIOR}), got {region_conf}"
        )

    def test_es_language_confidence_higher_than_region(self, cfg):
        """ES: language confidence must be higher than the very-low region confidence."""
        tags = decompose("provider_category", "ES", config=cfg)
        lang_conf = next((c for t, _, c in tags if t == "language"), None)
        region_conf = next((c for t, _, c in tags if t == "region"), None)
        assert lang_conf > region_conf

    # ── LAT: distinct "Latin American Spanish" value, NOT "Spanish" ──────────

    def test_lat_language_value_is_distinct(self, cfg):
        """LAT → (language, 'Latin American Spanish', …) — distinct value."""
        tags = decompose("provider_category", "LAT", config=cfg)
        lang_val = next((v for t, v, _ in tags if t == "language"), None)
        assert lang_val == "Latin American Spanish", (
            f"LAT should emit 'Latin American Spanish', got {lang_val!r}"
        )

    def test_lat_not_merged_into_spanish(self, cfg):
        """LAT must NOT produce a 'Spanish' value — distinct dialect."""
        tags = decompose("provider_category", "LAT", config=cfg)
        assert not any(v == "Spanish" for _, v, _ in tags), (
            f"LAT must not emit 'Spanish': {tags}"
        )

    def test_lat_no_region_tag(self, cfg):
        """LAT has no single meaningful region — no region tag expected."""
        tags = decompose("provider_category", "LAT", config=cfg)
        assert not any(t == "region" for t, _, _ in tags), (
            f"LAT should not emit a region tag: {tags}"
        )

    # ── AR: Arabic language — NOT region:Argentina ───────────────────────────

    def test_ar_is_arabic_language(self, cfg):
        """AR → language:Arabic (IPTV convention)."""
        tags = decompose("provider_category", "AR", config=cfg)
        lang_val = next((v for t, v, _ in tags if t == "language"), None)
        assert lang_val == "Arabic", f"AR should be Arabic, got {lang_val!r}"

    def test_ar_not_argentina_region(self, cfg):
        """AR must NOT emit region:Argentina — that is ARG."""
        tags = decompose("provider_category", "AR", config=cfg)
        assert not any(t == "region" and v == "Argentina" for t, v, _ in tags), (
            f"AR emitted region:Argentina — bug: {tags}"
        )

    def test_ar_not_any_region(self, cfg):
        """AR should emit no region tag (just language:Arabic)."""
        tags = decompose("provider_category", "AR", config=cfg)
        assert not any(t == "region" for t, _, _ in tags), (
            f"AR emitted a region tag — bug: {tags}"
        )

    # ── ARG: region:Argentina (three-letter code) ────────────────────────────

    def test_arg_is_argentina_region(self, cfg):
        """ARG → region:ARG (Argentina)."""
        tags = decompose("provider_category", "ARG", config=cfg)
        assert any(t == "region" and v == "ARG" for t, v, _ in tags), (
            f"ARG should emit region:ARG, got {tags}"
        )


# --------------------------------------------------------------------------- #
#  provider_category / header feeders — compound strings                       #
# --------------------------------------------------------------------------- #

class TestCompoundDecompose:
    """provider_category and header feeders — compound-split + classify."""

    def test_usa_netflix_hd(self, cfg):
        """Canonical example from the spec: USA | NETFLIX | HD."""
        tags = decompose("provider_category", "USA | NETFLIX | HD", config=cfg)
        types = {t for t, _, _ in tags}
        values_by_type = {t: v for t, v, _ in tags}

        assert "region" in types, f"Expected region tag in {tags}"
        assert values_by_type["region"] == "US"

        assert "platform" in types, f"Expected platform tag in {tags}"
        assert values_by_type["platform"] == "Netflix"

        assert "quality" in types, f"Expected quality tag in {tags}"
        assert values_by_type["quality"] == "HD"

    def test_fr_star_movies(self, cfg):
        """FR ★ MOVIES — language + region prior + collection."""
        tags = decompose("provider_category", "FR ★ MOVIES", config=cfg)
        types = {t for t, _, _ in tags}
        assert "language" in types
        assert any(v == "French" for t, v, _ in tags if t == "language")
        # DR-0006: FR also emits a region prior
        assert "region" in types
        assert "collection" in types

    def test_de_entertainment(self, cfg):
        """DE - ENTERTAINMENT — language + region prior + collection."""
        tags = decompose("header", "DE - ENTERTAINMENT", config=cfg)
        types = {t for t, _, _ in tags}
        # DE is in CODE_FACETS → language:German + region:DE prior
        assert "language" in types
        assert "collection" in types

    def test_wow_sport_header(self, cfg):
        """### WOW SPORT ### — stripped hash header → some tags."""
        tags = decompose("header", "### WOW SPORT ###", config=cfg)
        assert len(tags) > 0, "Should produce at least one tag"

    def test_4k_usd_compound(self, cfg):
        """4K | US | DRAMA — quality + region + collection."""
        tags = decompose("provider_category", "4K | US | DRAMA", config=cfg)
        types = {t for t, _, _ in tags}
        assert "quality" in types, f"Expected quality in {tags}"
        assert "region" in types, f"Expected region in {tags}"
        # US also gives language prior (DR-0006)
        assert "collection" in types, f"Expected collection in {tags}"

    def test_plain_english(self, cfg):
        """EN — language group match (English), no region."""
        tags = decompose("provider_category", "EN", config=cfg)
        assert any(t == "language" for t, _, _ in tags), f"Expected language tag in {tags}"
        assert any(v == "English" for t, v, _ in tags if t == "language")
        assert not any(t == "region" for t, _, _ in tags), (
            f"EN must not emit region: {tags}"
        )

    def test_unrecognised_token_dropped_or_collection(self, cfg):
        """Tokens that don't match any known type become collection, not mis-typed."""
        tags = decompose("provider_category", "XYZZY123", config=cfg)
        for typ, val, conf in tags:
            assert typ in (
                "region", "language", "platform", "quality",
                "genre", "collection", "content_type", "decade"
            ), f"Unexpected tag type: {typ}"
            assert typ != "region", "Should not mis-type unknown token as region"
            assert typ != "language", "Should not mis-type unknown token as language"

    def test_no_duplicate_tags(self, cfg):
        """Result must never contain duplicate (type, value) pairs."""
        tags = decompose("provider_category", "US | USA | United States", config=cfg)
        keys = [(t, v) for t, v, _ in tags]
        assert len(keys) == len(set(keys)), f"Duplicate tags found: {tags}"

    def test_empty_string_returns_empty(self, cfg):
        """Empty input → empty list."""
        assert decompose("provider_category", "", config=cfg) == []
        assert decompose("header", "   ", config=cfg) == []

    def test_nf_is_platform_not_region(self, cfg):
        """NF (Netflix) is a platform — must not appear as region."""
        tags = decompose("provider_category", "NF", config=cfg)
        for typ, val, conf in tags:
            assert typ != "region", f"NF should not be tagged as region, got {tags}"
        assert any(t == "platform" for t, _, _ in tags), f"NF should be tagged as platform: {tags}"

    def test_prime_platform(self, cfg):
        """PRIME (Amazon Prime) → platform tag."""
        tags = decompose("provider_category", "PRIME | HD", config=cfg)
        types = {t for t, _, _ in tags}
        assert "platform" in types, f"Expected platform in {tags}"
        assert any(v == "Amazon Prime" for t, v, _ in tags if t == "platform")

    def test_hd_quality_group(self, cfg):
        """HD → quality group 'HD'."""
        tags = decompose("provider_category", "HD", config=cfg)
        assert any(t == "quality" for t, _, _ in tags), f"Expected quality in {tags}"

    def test_4k_quality_group(self, cfg):
        """4K → quality group '4K / UHD'."""
        tags = decompose("provider_category", "4K", config=cfg)
        assert any(t == "quality" for t, _, _ in tags), f"Expected quality in {tags}"
        qual_val = next((v for t, v, _ in tags if t == "quality"), None)
        assert qual_val == "4K / UHD", f"Expected '4K / UHD', got {qual_val!r}"

    def test_collection_from_residual(self, cfg):
        """Provider category with an unclassified label → collection."""
        tags = decompose("provider_category", "EN - ENTERTAINMENT", config=cfg)
        assert any(t == "collection" for t, _, _ in tags), f"Expected collection in {tags}"

    def test_pipe_separator(self, cfg):
        """Pipe separator splits compound correctly."""
        tags = decompose("provider_category", "FR|HD", config=cfg)
        types = {t for t, _, _ in tags}
        # FR → language (+ region prior)
        assert "language" in types
        assert "quality" in types

    def test_star_separator(self, cfg):
        """★ separator splits compound correctly."""
        tags = decompose("provider_category", "DE★HD", config=cfg)
        types = {t for t, _, _ in tags}
        assert "quality" in types


# --------------------------------------------------------------------------- #
#  genre feeder                                                                #
# --------------------------------------------------------------------------- #

class TestGenreDecompose:
    """genre feeder — normalize_genre + split."""

    def test_english_drama(self, cfg):
        tags = decompose("genre", "Drama", config=cfg)
        assert tags == [("genre", "Drama", CONF_DENOTED)]

    def test_french_drame(self, cfg):
        """Drame → Drama (normalize_genre cross-language)."""
        tags = decompose("genre", "Drame", config=cfg)
        assert tags == [("genre", "Drama", CONF_DENOTED)]

    def test_multi_genre_slash(self, cfg):
        """Drama/Comedy → two genre tags."""
        tags = decompose("genre", "Drama/Comedy", config=cfg)
        assert ("genre", "Drama", CONF_DENOTED) in tags
        assert ("genre", "Comedy", CONF_DENOTED) in tags

    def test_multi_genre_comma(self, cfg):
        """Drama, Crime → two genre tags."""
        tags = decompose("genre", "Drama, Crime", config=cfg)
        assert ("genre", "Drama", CONF_DENOTED) in tags
        assert ("genre", "Crime", CONF_DENOTED) in tags

    def test_arabic_genre(self, cfg):
        """Arabic genre string → canonical English."""
        tags = decompose("genre", "دراما", config=cfg)
        assert tags == [("genre", "Drama", CONF_DENOTED)]

    def test_unknown_genre_passthrough(self, cfg):
        """Unknown genre string → emitted as-is (normalize_genre pass-through)."""
        tags = decompose("genre", "SomeFutureGenre", config=cfg)
        assert tags == [("genre", "SomeFutureGenre", CONF_DENOTED)]

    def test_empty_genre(self, cfg):
        assert decompose("genre", "", config=cfg) == []

    def test_sci_fi_abbreviation_normalizes(self, cfg):
        """'Sci-Fi' collapses to the same canonical as 'Science Fiction'."""
        tags_abbr = decompose("genre", "Sci-Fi", config=cfg)
        tags_full = decompose("genre", "Science Fiction", config=cfg)
        assert tags_abbr == [("genre", "Science Fiction", CONF_DENOTED)]
        assert tags_full == [("genre", "Science Fiction", CONF_DENOTED)]
        # Both spellings must yield the identical canonical value.
        assert tags_abbr == tags_full

    def test_html_entity_genre_collapses(self, cfg):
        """'Action &amp; Adventure' (HTML-encoded) → same canonical as 'Action & Adventure'."""
        tags_encoded = decompose("genre", "Action &amp; Adventure", config=cfg)
        tags_plain = decompose("genre", "Action & Adventure", config=cfg)
        assert tags_encoded == tags_plain, (
            f"HTML-encoded genre should collapse to same canonical; "
            f"got {tags_encoded!r} vs {tags_plain!r}"
        )

    def test_backfill_version_is_bumped(self):
        """CURRENT_TAG_BACKFILL_VERSION must be > 1 (genre normalization rerun)."""
        from metatv.core.migrations.tag_backfill import CURRENT_TAG_BACKFILL_VERSION
        assert CURRENT_TAG_BACKFILL_VERSION >= 2, (
            "Bump CURRENT_TAG_BACKFILL_VERSION to at least 2 so genre "
            "normalization is re-derived for all channels on next launch."
        )


# --------------------------------------------------------------------------- #
#  epg feeder                                                                  #
# --------------------------------------------------------------------------- #

class TestEpgDecompose:
    """epg feeder — genre normalization, best-effort."""

    def test_sport(self, cfg):
        """EPG 'Sport' → genre:Sport."""
        tags = decompose("epg", "Sport", config=cfg)
        assert any(t == "genre" and v == "Sport" for t, v, _ in tags)

    def test_documentary(self, cfg):
        tags = decompose("epg", "Documentary", config=cfg)
        assert any(t == "genre" and v == "Documentary" for t, v, _ in tags)

    def test_news_passthrough(self, cfg):
        tags = decompose("epg", "News", config=cfg)
        assert any(t == "genre" and v == "News" for t, v, _ in tags)


# --------------------------------------------------------------------------- #
#  decompose_name_parse — pre-typed fields                                     #
# --------------------------------------------------------------------------- #

class TestDecomposeNameParse:
    """decompose_name_parse: already-typed detected_* fields → tags."""

    def test_en_prefix_to_language_only(self, cfg):
        """EN prefix → language:English, and no region tag (DR-0006)."""
        tags = decompose_name_parse(
            detected_prefix="EN",
            detected_quality=None,
            detected_region=None,
            detected_year=None,
            config=cfg,
        )
        assert any(t == "language" and v == "English" for t, v, _ in tags)
        assert not any(t == "region" for t, _, _ in tags), (
            f"EN must not produce a region tag: {tags}"
        )

    def test_quality_field(self, cfg):
        """detected_quality='HD' → quality group tag."""
        tags = decompose_name_parse(
            detected_prefix=None,
            detected_quality="HD",
            detected_region=None,
            detected_year=None,
            config=cfg,
        )
        assert any(t == "quality" for t, _, _ in tags), f"Expected quality in {tags}"

    def test_region_field_us(self, cfg):
        """detected_region='US' → region:US."""
        tags = decompose_name_parse(
            detected_prefix=None,
            detected_quality=None,
            detected_region="US",
            detected_year=None,
            config=cfg,
        )
        assert any(t == "region" and v == "US" for t, v, _ in tags), (
            f"Expected region:US in {tags}"
        )

    def test_year_to_decade(self, cfg):
        """detected_year='1994' → decade:1990s."""
        tags = decompose_name_parse(
            detected_prefix=None,
            detected_quality=None,
            detected_region=None,
            detected_year="1994",
            config=cfg,
        )
        assert ("decade", "1990s", CONF_DENOTED) in tags, (
            f"Expected decade:1990s in {tags}"
        )

    def test_year_range_to_decade(self, cfg):
        """Year range '1993-2002' → decade:1990s (start year)."""
        tags = decompose_name_parse(
            detected_prefix=None,
            detected_quality=None,
            detected_region=None,
            detected_year="1993-2002",
            config=cfg,
        )
        assert ("decade", "1990s", CONF_DENOTED) in tags, (
            f"Expected decade:1990s in {tags}"
        )

    def test_2024_decade(self, cfg):
        """Year 2024 → decade:2020s."""
        tags = decompose_name_parse(
            detected_prefix=None,
            detected_quality=None,
            detected_region=None,
            detected_year="2024",
            config=cfg,
        )
        assert ("decade", "2020s", CONF_DENOTED) in tags, (
            f"Expected decade:2020s in {tags}"
        )

    def test_all_none_returns_empty(self, cfg):
        """All None fields → empty list."""
        tags = decompose_name_parse(
            detected_prefix=None,
            detected_quality=None,
            detected_region=None,
            detected_year=None,
            config=cfg,
        )
        assert tags == []

    def test_no_duplicates(self, cfg):
        """No duplicate (type, value) pairs when prefix and region are same code."""
        tags = decompose_name_parse(
            detected_prefix="EN",
            detected_quality=None,
            detected_region="EN",  # same code in both fields
            detected_year=None,
            config=cfg,
        )
        keys = [(t, v) for t, v, _ in tags]
        assert len(keys) == len(set(keys)), f"Duplicates in {tags}"

    def test_nf_prefix_is_platform(self, cfg):
        """NF as detected_prefix → platform:Netflix, NOT region."""
        tags = decompose_name_parse(
            detected_prefix="NF",
            detected_quality=None,
            detected_region=None,
            detected_year=None,
            config=cfg,
        )
        for typ, val, conf in tags:
            assert typ != "region", f"NF should not become region, got {tags}"
        assert any(t == "platform" for t, _, _ in tags), f"Expected platform in {tags}"

    def test_arg_region(self, cfg):
        """ARG prefix → region:ARG (Argentina)."""
        tags = decompose_name_parse(
            detected_prefix="ARG",
            detected_quality=None,
            detected_region=None,
            detected_year=None,
            config=cfg,
        )
        assert any(t == "region" and v == "ARG" for t, v, _ in tags), (
            f"Expected region:ARG in {tags}"
        )

    def test_lat_prefix_distinct_value(self, cfg):
        """LAT as detected_prefix → 'Latin American Spanish', not 'Spanish'."""
        tags = decompose_name_parse(
            detected_prefix="LAT",
            detected_quality=None,
            detected_region=None,
            detected_year=None,
            config=cfg,
        )
        lang_val = next((v for t, v, _ in tags if t == "language"), None)
        assert lang_val == "Latin American Spanish", (
            f"LAT should give 'Latin American Spanish', got {lang_val!r}"
        )

    def test_ar_prefix_arabic(self, cfg):
        """AR as detected_prefix → language:Arabic, not region:Argentina."""
        tags = decompose_name_parse(
            detected_prefix="AR",
            detected_quality=None,
            detected_region=None,
            detected_year=None,
            config=cfg,
        )
        assert any(t == "language" and v == "Arabic" for t, v, _ in tags), (
            f"AR should give language:Arabic, got {tags}"
        )
        assert not any(t == "region" for t, _, _ in tags), (
            f"AR must not produce a region tag: {tags}"
        )


# --------------------------------------------------------------------------- #
#  Confidence scale integrity                                                  #
# --------------------------------------------------------------------------- #

class TestConfidenceScale:
    """Verify the documented confidence constants hold the right ordering."""

    def test_denoted_beats_strong_prior(self):
        assert CONF_DENOTED > CONF_STRONG_PRIOR

    def test_strong_prior_beats_weak_prior(self):
        assert CONF_STRONG_PRIOR > CONF_WEAK_PRIOR

    def test_confidence_values_in_range(self):
        for c in (CONF_DENOTED, CONF_STRONG_PRIOR, CONF_WEAK_PRIOR):
            assert 0.0 <= c <= 1.0, f"Confidence {c} out of [0, 1]"

    def test_all_tags_have_valid_confidence(self, cfg):
        """Every emitted tag must have a confidence in [0, 1]."""
        test_inputs = [
            ("provider_category", "USA | NETFLIX | HD"),
            ("provider_category", "FR"),
            ("provider_category", "EN"),
            ("provider_category", "ES"),
            ("provider_category", "LAT"),
            ("provider_category", "AR"),
            ("provider_category", "ARG"),
            ("provider_category", "US"),
            ("genre", "Drama"),
            ("epg", "Sport"),
        ]
        for feeder, raw in test_inputs:
            tags = decompose(feeder, raw, config=cfg)
            for typ, val, conf in tags:
                assert 0.0 <= conf <= 1.0, (
                    f"Invalid confidence {conf} for ({typ}, {val}) "
                    f"from feeder={feeder!r} raw={raw!r}"
                )


# --------------------------------------------------------------------------- #
#  Type safety — all output types must be in the defined namespace             #
# --------------------------------------------------------------------------- #

_VALID_TYPES = frozenset({
    "region", "language", "platform", "quality",
    "genre", "collection", "content_type", "decade"
})


@pytest.mark.parametrize("feeder,raw", [
    ("provider_category", "USA | NETFLIX | HD"),
    ("provider_category", "DE | ENTERTAINMENT"),
    ("provider_category", "4K | US"),
    ("provider_category", "FR"),
    ("provider_category", "EN"),
    ("provider_category", "ES"),
    ("provider_category", "LAT"),
    ("provider_category", "AR"),
    ("provider_category", "ARG"),
    ("header", "### WOW SPORT ###"),
    ("header", "FRENCH MOVIES"),
    ("genre", "Drama"),
    ("genre", "Drame/Comedy"),
    ("epg", "Sport"),
    ("epg", "Documentary"),
])
def test_output_types_always_valid(feeder, raw, cfg):
    """Every (type, value, confidence) triple must use a known tag type namespace."""
    tags = decompose(feeder, raw, config=cfg)
    for typ, val, conf in tags:
        assert typ in _VALID_TYPES, (
            f"Unknown tag type {typ!r} from feeder={feeder!r} raw={raw!r}"
        )
        assert val, f"Empty value for type={typ!r} from feeder={feeder!r} raw={raw!r}"
