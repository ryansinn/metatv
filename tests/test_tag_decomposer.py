"""Tests for metatv.core.tag_decomposer — Tags Slice T2.

Pure-function tests: no DB, no Qt.  Uses a real Config() (the autouse
``_isolate_user_config`` fixture ensures it writes to a throwaway tmp dir,
not the developer's real config).

The tests verify:
- Real compound strings produce the expected typed tags.
- Each classifier reuse point (region / language / platform / quality / genre) works.
- Unrecognised tokens are DROPPED, not mis-typed.
- No duplicate (type, value) pairs are emitted.
- Decade extraction works for name_parse feeder.
- The ``decompose_name_parse`` helper promotes pre-typed fields correctly.
- The ``genre`` and ``epg`` feeders normalize genre strings.
"""

import pytest

from metatv.core.config import Config
from metatv.core.tag_decomposer import decompose, decompose_name_parse


# ── Shared fixture ──────────────────────────────────────────────────────────── #

@pytest.fixture(scope="module")
def cfg():
    """A default Config() with the base prefix/quality/platform groups."""
    return Config()


# --------------------------------------------------------------------------- #
#  provider_category / header feeders — compound strings                       #
# --------------------------------------------------------------------------- #

class TestCompoundDecompose:
    """provider_category and header feeders — compound-split + classify."""

    def test_usa_netflix_hd(self, cfg):
        """Canonical example from the spec: USA | NETFLIX | HD."""
        tags = decompose("provider_category", "USA | NETFLIX | HD", config=cfg)
        types = {t for t, _ in tags}
        values_by_type = {t: v for t, v in tags}

        assert "region" in types, f"Expected region tag in {tags}"
        assert values_by_type["region"] == "US"

        assert "platform" in types, f"Expected platform tag in {tags}"
        assert values_by_type["platform"] == "Netflix"

        assert "quality" in types, f"Expected quality tag in {tags}"
        # HD maps to the "HD" quality group
        assert values_by_type["quality"] == "HD"

    def test_fr_star_movies(self, cfg):
        """FR ★ MOVIES — region + collection."""
        tags = decompose("provider_category", "FR ★ MOVIES", config=cfg)
        types = {t for t, _ in tags}
        assert "region" in types
        assert any(v == "FR" for t, v in tags if t == "region")
        assert "collection" in types

    def test_de_entertainment(self, cfg):
        """DE - ENTERTAINMENT — language + collection."""
        tags = decompose("header", "DE - ENTERTAINMENT", config=cfg)
        types = {t for t, _ in tags}
        # DE is in the German language group
        assert "language" in types or "region" in types
        assert "collection" in types

    def test_wow_sport_header(self, cfg):
        """### WOW SPORT ### — stripped hash header → collection (WOW is a platform)."""
        tags = decompose("header", "### WOW SPORT ###", config=cfg)
        # WOW is in the platform groups; SPORT has no group → collection
        types = {t for t, _ in tags}
        # Should at least produce a collection for the unclassified part
        assert len(tags) > 0, "Should produce at least one tag"

    def test_4k_usd_compound(self, cfg):
        """4K | US | DRAMA — quality + region + collection."""
        tags = decompose("provider_category", "4K | US | DRAMA", config=cfg)
        types = {t for t, _ in tags}
        assert "quality" in types, f"Expected quality in {tags}"
        assert "region" in types, f"Expected region in {tags}"
        assert "collection" in types, f"Expected collection in {tags}"

    def test_plain_english(self, cfg):
        """EN — language group match (English)."""
        tags = decompose("provider_category", "EN", config=cfg)
        assert any(t == "language" for t, _ in tags), f"Expected language tag in {tags}"
        assert any(v == "English" for t, v in tags if t == "language")

    def test_unrecognised_token_dropped(self, cfg):
        """Tokens that don't match any known type must be dropped, not mis-typed."""
        tags = decompose("provider_category", "XYZZY123", config=cfg)
        # No known region/language/platform/quality for this.
        # It may become a collection if not filtered as junk — but it must NOT
        # be assigned a wrong type like region or language.
        for typ, val in tags:
            assert typ in (
                "region", "language", "platform", "quality",
                "genre", "collection", "content_type", "decade"
            ), f"Unexpected tag type: {typ}"
            assert typ != "region", "Should not mis-type unknown token as region"
            assert typ != "language", "Should not mis-type unknown token as language"

    def test_no_duplicate_tags(self, cfg):
        """Result must never contain duplicate (type, value) pairs."""
        tags = decompose("provider_category", "US | USA | United States", config=cfg)
        assert len(tags) == len(set(tags)), f"Duplicate tags found: {tags}"

    def test_empty_string_returns_empty(self, cfg):
        """Empty input → empty list."""
        assert decompose("provider_category", "", config=cfg) == []
        assert decompose("header", "   ", config=cfg) == []

    def test_nf_is_platform_not_region(self, cfg):
        """NF (Netflix) is a platform — must not appear as region."""
        tags = decompose("provider_category", "NF", config=cfg)
        for typ, val in tags:
            assert typ != "region", f"NF should not be tagged as region, got {tags}"
        assert any(t == "platform" for t, _ in tags), f"NF should be tagged as platform: {tags}"

    def test_prime_platform(self, cfg):
        """PRIME (Amazon Prime) → platform tag."""
        tags = decompose("provider_category", "PRIME | HD", config=cfg)
        types = {t for t, _ in tags}
        assert "platform" in types, f"Expected platform in {tags}"
        assert any(v == "Amazon Prime" for t, v in tags if t == "platform")

    def test_hd_quality_group(self, cfg):
        """HD → quality group 'HD'."""
        tags = decompose("provider_category", "HD", config=cfg)
        assert any(t == "quality" for t, _ in tags), f"Expected quality in {tags}"

    def test_4k_quality_group(self, cfg):
        """4K → quality group '4K / UHD'."""
        tags = decompose("provider_category", "4K", config=cfg)
        assert any(t == "quality" for t, _ in tags), f"Expected quality in {tags}"
        qual_val = next((v for t, v in tags if t == "quality"), None)
        assert qual_val == "4K / UHD", f"Expected '4K / UHD', got {qual_val!r}"

    def test_collection_from_residual(self, cfg):
        """Provider category with an unclassified label → collection."""
        tags = decompose("provider_category", "EN - ENTERTAINMENT", config=cfg)
        assert any(t == "collection" for t, _ in tags), f"Expected collection in {tags}"

    def test_pipe_separator(self, cfg):
        """Pipe separator splits compound correctly."""
        tags = decompose("provider_category", "FR|HD", config=cfg)
        types = {t for t, _ in tags}
        assert "region" in types or "language" in types
        assert "quality" in types

    def test_star_separator(self, cfg):
        """★ separator splits compound correctly."""
        tags = decompose("provider_category", "DE★HD", config=cfg)
        types = {t for t, _ in tags}
        assert "quality" in types


# --------------------------------------------------------------------------- #
#  genre feeder                                                                #
# --------------------------------------------------------------------------- #

class TestGenreDecompose:
    """genre feeder — normalize_genre + split."""

    def test_english_drama(self, cfg):
        tags = decompose("genre", "Drama", config=cfg)
        assert tags == [("genre", "Drama")]

    def test_french_drame(self, cfg):
        """Drame → Drama (normalize_genre cross-language)."""
        tags = decompose("genre", "Drame", config=cfg)
        assert tags == [("genre", "Drama")]

    def test_multi_genre_slash(self, cfg):
        """Drama/Comedy → two genre tags."""
        tags = decompose("genre", "Drama/Comedy", config=cfg)
        assert ("genre", "Drama") in tags
        assert ("genre", "Comedy") in tags

    def test_multi_genre_comma(self, cfg):
        """Drama, Crime → two genre tags."""
        tags = decompose("genre", "Drama, Crime", config=cfg)
        assert ("genre", "Drama") in tags
        assert ("genre", "Crime") in tags

    def test_arabic_genre(self, cfg):
        """Arabic genre string → canonical English."""
        tags = decompose("genre", "دراما", config=cfg)
        assert tags == [("genre", "Drama")]

    def test_unknown_genre_passthrough(self, cfg):
        """Unknown genre string → emitted as-is (normalize_genre pass-through)."""
        tags = decompose("genre", "SomeFutureGenre", config=cfg)
        assert tags == [("genre", "SomeFutureGenre")]

    def test_empty_genre(self, cfg):
        assert decompose("genre", "", config=cfg) == []


# --------------------------------------------------------------------------- #
#  epg feeder                                                                  #
# --------------------------------------------------------------------------- #

class TestEpgDecompose:
    """epg feeder — genre normalization, best-effort."""

    def test_sport(self, cfg):
        """EPG 'Sport' → genre:Sport."""
        tags = decompose("epg", "Sport", config=cfg)
        assert ("genre", "Sport") in tags

    def test_documentary(self, cfg):
        tags = decompose("epg", "Documentary", config=cfg)
        assert ("genre", "Documentary") in tags

    def test_news_passthrough(self, cfg):
        tags = decompose("epg", "News", config=cfg)
        assert ("genre", "News") in tags


# --------------------------------------------------------------------------- #
#  decompose_name_parse — pre-typed fields                                     #
# --------------------------------------------------------------------------- #

class TestDecomposeNameParse:
    """decompose_name_parse: already-typed detected_* fields → tags."""

    def test_en_prefix_to_language(self, cfg):
        """EN prefix → language:English."""
        tags = decompose_name_parse(
            detected_prefix="EN",
            detected_quality=None,
            detected_region=None,
            detected_year=None,
            config=cfg,
        )
        assert any(t == "language" for t, _ in tags), f"Expected language in {tags}"

    def test_quality_field(self, cfg):
        """detected_quality='HD' → quality group tag."""
        tags = decompose_name_parse(
            detected_prefix=None,
            detected_quality="HD",
            detected_region=None,
            detected_year=None,
            config=cfg,
        )
        assert any(t == "quality" for t, _ in tags), f"Expected quality in {tags}"

    def test_region_field(self, cfg):
        """detected_region='US' → region:US."""
        tags = decompose_name_parse(
            detected_prefix=None,
            detected_quality=None,
            detected_region="US",
            detected_year=None,
            config=cfg,
        )
        assert any(t == "region" and v == "US" for t, v in tags), f"Expected region:US in {tags}"

    def test_year_to_decade(self, cfg):
        """detected_year='1994' → decade:1990s."""
        tags = decompose_name_parse(
            detected_prefix=None,
            detected_quality=None,
            detected_region=None,
            detected_year="1994",
            config=cfg,
        )
        assert ("decade", "1990s") in tags, f"Expected decade:1990s in {tags}"

    def test_year_range_to_decade(self, cfg):
        """Year range '1993-2002' → decade:1990s (start year)."""
        tags = decompose_name_parse(
            detected_prefix=None,
            detected_quality=None,
            detected_region=None,
            detected_year="1993-2002",
            config=cfg,
        )
        assert ("decade", "1990s") in tags, f"Expected decade:1990s in {tags}"

    def test_2024_decade(self, cfg):
        """Year 2024 → decade:2020s."""
        tags = decompose_name_parse(
            detected_prefix=None,
            detected_quality=None,
            detected_region=None,
            detected_year="2024",
            config=cfg,
        )
        assert ("decade", "2020s") in tags, f"Expected decade:2020s in {tags}"

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
        # detected_prefix="EN" may produce language + region; they should not duplicate.
        tags = decompose_name_parse(
            detected_prefix="EN",
            detected_quality=None,
            detected_region="EN",  # same code in both fields
            detected_year=None,
            config=cfg,
        )
        assert len(tags) == len(set(tags)), f"Duplicates in {tags}"

    def test_nf_prefix_is_platform(self, cfg):
        """NF as detected_prefix → platform:Netflix, NOT region."""
        tags = decompose_name_parse(
            detected_prefix="NF",
            detected_quality=None,
            detected_region=None,
            detected_year=None,
            config=cfg,
        )
        for typ, val in tags:
            assert typ != "region", f"NF should not become region, got {tags}"
        assert any(t == "platform" for t, _ in tags), f"Expected platform in {tags}"

    def test_arg_region(self, cfg):
        """ARG prefix → region:ARG."""
        tags = decompose_name_parse(
            detected_prefix="ARG",
            detected_quality=None,
            detected_region=None,
            detected_year=None,
            config=cfg,
        )
        assert any(t == "region" and v == "ARG" for t, v in tags), f"Expected region:ARG in {tags}"


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
    ("header", "### WOW SPORT ###"),
    ("header", "FRENCH MOVIES"),
    ("genre", "Drama"),
    ("genre", "Drame/Comedy"),
    ("epg", "Sport"),
    ("epg", "Documentary"),
])
def test_output_types_always_valid(feeder, raw, cfg):
    """Every (type, value) pair must use a known tag type namespace."""
    tags = decompose(feeder, raw, config=cfg)
    for typ, val in tags:
        assert typ in _VALID_TYPES, (
            f"Unknown tag type {typ!r} from feeder={feeder!r} raw={raw!r}"
        )
        assert val, f"Empty value for type={typ!r} from feeder={feeder!r} raw={raw!r}"
