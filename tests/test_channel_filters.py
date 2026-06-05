"""SQL-layer regression tests for ChannelRepository.get_all() filter logic.

Channel taxonomy seeded for each test:

  name                  prefix   quality  type
  ─────────────────── ──────── ──────── ───────
  EN - BBC News         EN       None     live
  EN - CNN HD           EN       HD       live
  FR - TF1              FR       None     live
  DE - Das Erste        DE       SD       live
  EAR - Dan Da Dan      EAR      None     series
  EAR - One Piece       EAR      None     series
  NF - Squid Game       NF       4K       series
  GO - Channel          GO       None     live    (unidentified)
  AS - Channel          AS       None     live    (unidentified)
  US - CNN              US       None     live    (region)
  Untagged Channel      None     None     live    (no prefix at all)

Identity pool axes (OR logic):
  Language  — EN, FR, DE
  Platform  — EAR, NF
  Region    — US
  Unident.  — GO, AS

Quality axis (restrictive):
  HD, SD, 4K, or None (untagged)
"""

import pytest
from tests.conftest import make_channel


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def channels(db_session):
    """Seed the standard 11-channel set and return a dict keyed by short name."""
    rows = {
        "en_bbc":    make_channel(db_session, "EN - BBC News",      detected_prefix="EN"),
        "en_cnn":    make_channel(db_session, "EN - CNN HD",         detected_prefix="EN",  detected_quality="HD"),
        "fr_tf1":    make_channel(db_session, "FR - TF1",            detected_prefix="FR"),
        "de_das":    make_channel(db_session, "DE - Das Erste",      detected_prefix="DE",  detected_quality="SD"),
        "ear_dan":   make_channel(db_session, "EAR - Dan Da Dan",    detected_prefix="EAR", media_type="series"),
        "ear_one":   make_channel(db_session, "EAR - One Piece",     detected_prefix="EAR", media_type="series"),
        "nf_squid":  make_channel(db_session, "NF - Squid Game",     detected_prefix="NF",  detected_quality="4K", media_type="series"),
        "go_ch":     make_channel(db_session, "GO - Channel",        detected_prefix="GO"),
        "as_ch":     make_channel(db_session, "AS - Channel",        detected_prefix="AS"),
        "us_cnn":    make_channel(db_session, "US - CNN",            detected_prefix="US"),
        "untagged":  make_channel(db_session, "Untagged Channel"),
    }
    db_session.commit()
    return rows


def names(channels_list) -> set[str]:
    return {c.name for c in channels_list}


# ── Baseline ──────────────────────────────────────────────────────────────────

def test_no_filter_returns_all(repo, channels):
    result = repo.get_all()
    assert len(result) == 11


def test_hidden_excluded_by_default(db_session, repo, channels):
    make_channel(db_session, "Hidden Ch", detected_prefix="EN", is_hidden=True)
    db_session.commit()
    result = repo.get_all()
    assert len(result) == 11  # 12 total, 1 hidden


# ── Language axis ─────────────────────────────────────────────────────────────

def test_language_filter_shows_only_that_language(repo, channels):
    result = repo.get_all(language_prefixes=["EN"], include_untagged=False)
    assert names(result) == {"EN - BBC News", "EN - CNN HD"}


def test_language_filter_includes_untagged_when_flag_true(repo, channels):
    result = repo.get_all(language_prefixes=["EN"], include_untagged=True)
    assert "Untagged Channel" in names(result)
    assert "EN - BBC News" in names(result)
    # non-language, non-untagged channels excluded
    assert "EAR - Dan Da Dan" not in names(result)


def test_language_filter_excludes_untagged_when_flag_false(repo, channels):
    result = repo.get_all(language_prefixes=["EN"], include_untagged=False)
    assert "Untagged Channel" not in names(result)


def test_multiple_language_prefixes_union(repo, channels):
    result = repo.get_all(language_prefixes=["EN", "FR", "DE"], include_untagged=False)
    assert names(result) == {"EN - BBC News", "EN - CNN HD", "FR - TF1", "DE - Das Erste"}


# ── Platform axis ─────────────────────────────────────────────────────────────

def test_platform_filter_shows_only_that_platform(repo, channels):
    result = repo.get_all(platform_prefixes=["EAR"], include_untagged=False)
    assert names(result) == {"EAR - Dan Da Dan", "EAR - One Piece"}


def test_platform_and_language_union(repo, channels):
    result = repo.get_all(
        language_prefixes=["EN"],
        platform_prefixes=["EAR"],
        include_untagged=False,
    )
    assert names(result) == {"EN - BBC News", "EN - CNN HD", "EAR - Dan Da Dan", "EAR - One Piece"}


# ── Cross-axis isolation (the historical bug class) ───────────────────────────

def test_unid_filter_does_not_hide_platform_channels(repo, channels):
    """Deselecting GO (unid) must not exclude EAR (platform) channels.

    Simulates get_filter_state() output when:
      lang_all=True, region_all=True, plat_all=True, unid=[AS only, GO deselected]
    After cross-axis expansion the params are:
      language_prefixes = all_lang_codes + selected_unid = [EN, FR, DE, AS]
      region_prefixes   = all_region_codes = [US]
      platform_prefixes = all_platform_codes = [EAR, NF]
    """
    result = repo.get_all(
        language_prefixes=["EN", "FR", "DE", "AS"],
        region_prefixes=["US"],
        platform_prefixes=["EAR", "NF"],
        include_untagged=True,
    )
    result_names = names(result)
    assert "EAR - Dan Da Dan" in result_names, "EAR channels must survive unid filter"
    assert "EAR - One Piece"  in result_names, "EAR channels must survive unid filter"
    assert "GO - Channel"    not in result_names, "GO must be excluded (deselected)"
    assert "EN - BBC News"   in result_names
    assert "NF - Squid Game" in result_names


def test_language_filter_does_not_hide_platform_channels(repo, channels):
    """Deselecting English must not hide EAR platform channels.

    Simulates: lang=[FR, DE], plat=all (expanded), region=all (expanded).
    """
    result = repo.get_all(
        language_prefixes=["FR", "DE"],
        region_prefixes=["US"],
        platform_prefixes=["EAR", "NF"],
        include_untagged=False,
    )
    result_names = names(result)
    assert "EAR - Dan Da Dan" in result_names, "EAR must survive language-only filter"
    assert "EAR - One Piece"  in result_names
    assert "EN - BBC News"   not in result_names, "EN excluded — English deselected"
    assert "EN - CNN HD"     not in result_names


def test_platform_filter_does_not_hide_language_channels(repo, channels):
    """Deselecting EAR must not hide EN/FR language channels."""
    result = repo.get_all(
        language_prefixes=["EN", "FR", "DE"],
        region_prefixes=["US"],
        platform_prefixes=["NF"],  # EAR excluded
        include_untagged=False,
    )
    result_names = names(result)
    assert "EN - BBC News"    in result_names
    assert "FR - TF1"         in result_names
    assert "EAR - Dan Da Dan" not in result_names, "EAR excluded — platform deselected"


def test_region_filter_does_not_hide_platform_channels(repo, channels):
    """Deselecting a region code must not hide EAR (platform) channels."""
    # No regions selected (empty) — with expansion, platform still in pool
    result = repo.get_all(
        language_prefixes=["EN", "FR", "DE"],
        platform_prefixes=["EAR", "NF"],
        # region_prefixes=None means no region restriction
        include_untagged=False,
    )
    assert "EAR - Dan Da Dan" in names(result)
    assert "US - CNN" not in names(result)  # no region axis, US excluded


def test_all_deselected_in_one_section_others_still_show(repo, channels):
    """All language codes deselected but platform+region all-selected: platform channels show.

    OR model: empty language axis contributes nothing, but platform axis still
    shows its channels.  This is correct OR-pool behaviour.
    """
    # language_prefixes=None (none selected → no lang restriction at all via or None)
    result = repo.get_all(
        platform_prefixes=["EAR", "NF"],
        include_untagged=True,
    )
    result_names = names(result)
    assert "EAR - Dan Da Dan" in result_names
    assert "NF - Squid Game"  in result_names
    # EN/FR channels excluded because only platform axis is active
    assert "EN - BBC News"   not in result_names


# ── Quality axis ──────────────────────────────────────────────────────────────

def test_quality_filter_passes_null_quality_channels(repo, channels):
    """Deselecting SD must hide SD channels but keep null-quality channels.

    The Includes model: deselecting a tier hides that tier, not untagged content.
    """
    result = repo.get_all(quality_prefixes=["HD", "4K"])
    result_names = names(result)
    # SD channel excluded
    assert "DE - Das Erste" not in result_names, "SD channel must be excluded"
    # Null-quality channels pass through
    assert "EN - BBC News"     in result_names, "null-quality channel must survive"
    assert "EAR - Dan Da Dan"  in result_names, "null-quality channel must survive"
    assert "Untagged Channel"  in result_names, "null-quality channel must survive"
    # HD/4K channels pass
    assert "EN - CNN HD"       in result_names
    assert "NF - Squid Game"   in result_names


def test_quality_filter_only_sd_selected(repo, channels):
    """Only SD selected — hides HD/4K channels but keeps null-quality."""
    result = repo.get_all(quality_prefixes=["SD"])
    result_names = names(result)
    assert "DE - Das Erste"   in result_names, "SD channel passes"
    assert "EN - CNN HD"      not in result_names, "HD excluded"
    assert "NF - Squid Game"  not in result_names, "4K excluded"
    assert "EN - BBC News"    in result_names, "null-quality passes through"


def test_quality_filter_with_include_untagged_quality_false(repo, channels):
    """Explicit opt-out of null-quality: only explicitly-tagged channels pass."""
    result = repo.get_all(quality_prefixes=["HD"], include_untagged_quality=False)
    result_names = names(result)
    assert "EN - CNN HD"      in result_names, "HD passes"
    assert "EN - BBC News"    not in result_names, "null-quality excluded when opted out"
    assert "EAR - Dan Da Dan" not in result_names, "null-quality excluded when opted out"
    assert "DE - Das Erste"   not in result_names, "SD excluded"


def test_no_quality_filter_shows_all_qualities(repo, channels):
    result = repo.get_all(quality_prefixes=None)
    assert len(result) == 11


# ── Combined axes ─────────────────────────────────────────────────────────────

def test_language_and_quality_combined(repo, channels):
    """EN language + HD quality: keeps EN+HD, EN+null-quality, and untagged.

    The OR identity pool isolates language; quality is AND-restrictive but
    passes null-quality channels.
    """
    result = repo.get_all(
        language_prefixes=["EN"],
        quality_prefixes=["HD"],
        include_untagged=True,
    )
    result_names = names(result)
    assert "EN - CNN HD"     in result_names   # EN + HD — both pass
    assert "EN - BBC News"   in result_names   # EN + null-quality — quality passes through
    assert "Untagged Channel" in result_names  # null-prefix (include_untagged) + null-quality
    assert "DE - Das Erste"  not in result_names  # DE excluded by language filter
    assert "NF - Squid Game" not in result_names  # NF excluded by language filter


def test_full_expansion_minus_one_unid(repo, channels):
    """All axes all-selected except GO deselected in unidentified.

    This is the exact real-world case that triggered the EAR regression.
    After expansion:
      language_prefixes = [EN, FR, DE, AS]  (lang codes + selected unid)
      region_prefixes   = [US]
      platform_prefixes = [EAR, NF]
    """
    result = repo.get_all(
        language_prefixes=["EN", "FR", "DE", "AS"],
        region_prefixes=["US"],
        platform_prefixes=["EAR", "NF"],
        include_untagged=True,
    )
    result_names = names(result)
    expected = {
        "EN - BBC News", "EN - CNN HD",
        "FR - TF1", "DE - Das Erste",
        "EAR - Dan Da Dan", "EAR - One Piece",
        "NF - Squid Game",
        "AS - Channel",
        "US - CNN",
        "Untagged Channel",
    }
    assert result_names == expected, f"Unexpected: {result_names ^ expected}"
    assert "GO - Channel" not in result_names


def test_media_type_filter(repo, channels):
    result = repo.get_all(media_types=["series"])
    result_names = names(result)
    assert "EAR - Dan Da Dan" in result_names
    assert "NF - Squid Game"  in result_names
    assert "EN - BBC News"   not in result_names


def test_search_query_pushdown(repo, channels):
    result = repo.get_all(search_query="Dan Da Dan")
    assert len(result) == 1
    assert result[0].name == "EAR - Dan Da Dan"


def test_search_with_active_filter_returns_filtered_subset(repo, channels):
    """Search within a filtered set — EAR channels should survive."""
    result = repo.get_all(
        platform_prefixes=["EAR"],
        search_query="One Piece",
        include_untagged=False,
    )
    assert len(result) == 1
    assert result[0].name == "EAR - One Piece"


# ── Context filter chips ───────────────────────────────────────────────────────
# strict_genre_filter and person_filter are activated from details-pane clicks.
# They use strict SQL (no passthrough for missing data) unlike the filter panel.

@pytest.fixture
def genre_channels(db_session):
    """Seed channels with various raw_data genre tags for context filter tests."""
    rows = {
        "drama_movie": make_channel(
            db_session, "EN - The Crown", media_type="movie",
            raw_data={"genre": "Drama", "cast": ""},
        ),
        "drama_series": make_channel(
            db_session, "EN - Suits", media_type="series",
            raw_data={"genre": "Drama", "cast": ""},
        ),
        "comedy_movie": make_channel(
            db_session, "EN - Airplane", media_type="movie",
            raw_data={"genre": "Comedy", "cast": ""},
        ),
        "no_genre_movie": make_channel(
            db_session, "EN - Unknown Film", media_type="movie",
            raw_data={"cast": ""},
        ),
        "live_drama": make_channel(
            db_session, "EN - Drama Live", media_type="live",
            raw_data={"genre": "Drama"},
        ),
    }
    db_session.commit()
    return rows


def test_strict_genre_filter_returns_only_matching_movies_series(repo, genre_channels):
    result = repo.get_all(strict_genre_filter="Drama")
    result_names = names(result)
    assert "EN - The Crown"  in result_names, "Drama movie must match"
    assert "EN - Suits"      in result_names, "Drama series must match"
    assert "EN - Airplane"  not in result_names, "Comedy must not match Drama"
    assert "EN - Unknown Film" not in result_names, "No-genre channel must not pass through"


def test_strict_genre_filter_excludes_live_channels(repo, genre_channels):
    result = repo.get_all(strict_genre_filter="Drama")
    assert "EN - Drama Live" not in names(result), "Live channels excluded even with matching genre"


def test_strict_genre_filter_no_passthrough_for_missing_genre(repo, genre_channels):
    result = repo.get_all(strict_genre_filter="Drama")
    assert "EN - Unknown Film" not in names(result), "Missing genre must not pass through (strict)"


def test_strict_genre_filter_returns_empty_when_no_match(repo, genre_channels):
    result = repo.get_all(strict_genre_filter="Horror")
    assert result == [], "No Horror-tagged channels should return empty list"


def test_strict_genre_filter_combined_with_search_query(repo, genre_channels):
    result = repo.get_all(strict_genre_filter="Drama", search_query="Crown")
    result_names = names(result)
    assert "EN - The Crown" in result_names
    assert "EN - Suits"    not in result_names, "Search narrows within genre"


@pytest.fixture
def person_channels(db_session):
    """Seed channels with cast/director raw_data for person filter tests."""
    rows = {
        "hanks_cast": make_channel(
            db_session, "EN - Forrest Gump", media_type="movie",
            raw_data={"cast": "Tom Hanks, Robin Wright, Gary Sinise", "director": "Robert Zemeckis"},
        ),
        "hanks_no_match": make_channel(
            db_session, "EN - Saving Private Ryan", media_type="movie",
            raw_data={"cast": "Tom Hanks, Matt Damon", "director": "Steven Spielberg"},
        ),
        "zemeckis_dir": make_channel(
            db_session, "EN - Back to the Future", media_type="movie",
            raw_data={"cast": "Michael J. Fox, Christopher Lloyd", "director": "Robert Zemeckis"},
        ),
        "no_cast": make_channel(
            db_session, "EN - Mystery Film", media_type="movie",
            raw_data={},
        ),
        "live_ch": make_channel(
            db_session, "EN - Tom Hanks Channel", media_type="live",
        ),
    }
    db_session.commit()
    return rows


def test_person_filter_matches_cast_field(repo, person_channels):
    result = repo.get_all(person_filter="Tom Hanks")
    result_names = names(result)
    assert "EN - Forrest Gump"      in result_names, "Tom Hanks in cast must match"
    assert "EN - Saving Private Ryan" in result_names, "Tom Hanks in cast must match"
    assert "EN - Back to the Future" not in result_names, "Tom Hanks not in cast here"


def test_person_filter_matches_director_field(repo, person_channels):
    result = repo.get_all(person_filter="Robert Zemeckis")
    result_names = names(result)
    assert "EN - Forrest Gump"       in result_names, "Zemeckis is director of Forrest Gump"
    assert "EN - Back to the Future" in result_names, "Zemeckis is director of BttF"
    assert "EN - Saving Private Ryan" not in result_names, "Spielberg != Zemeckis"


def test_person_filter_no_results_for_missing_cast(repo, person_channels):
    result = repo.get_all(person_filter="Tom Hanks")
    assert "EN - Mystery Film" not in names(result), "Channel with empty raw_data excluded"


def test_person_filter_excludes_channels_by_name_match_only(repo, person_channels):
    """Channel name containing person's name should NOT match — only raw_data.cast/director."""
    result = repo.get_all(person_filter="Tom Hanks")
    assert "EN - Tom Hanks Channel" not in names(result), "Live channel name match must not count"


def test_person_filter_combined_with_search_query(repo, person_channels):
    result = repo.get_all(person_filter="Tom Hanks", search_query="Gump")
    result_names = names(result)
    assert "EN - Forrest Gump"         in result_names
    assert "EN - Saving Private Ryan" not in result_names, "Search narrows within person filter"
