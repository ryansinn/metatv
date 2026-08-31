"""414 rows of one show, because the episode number was in the title.

The owner's providers file some series as loose VOD entries — one "movie" per
episode, named ``Konusanlar S01E57 1080p EXXEN WEB-DL [TR] AAC H264-TURG``.
Measured across the library, **960 rows are 48 shows**: 414 Konusanlar, 62
Sihirli Annem, 56 Leyla ile Mecnun. Browse showed 960 separate cards.

The marker is what made them look distinct. ``content_key`` is derived from
``detected_title``, so lifting ``S01E57`` out of the title collapses them the
same way it already collapses every other cross-source duplicate — 960 → 48.

Only the ``SxxExx`` form, and that is a measurement rather than a preference:

    SxxExx ............. 960 rows, every one a series episode
    1x05 ................ 14 rows, every one a REAL FILM TITLE
                          "10x10 (2018)", "8x10 Tasveer", "12x12"
    Season N Episode N ... 0 rows

Implementing the second pattern for symmetry would have renamed 14 films and
given them season and episode numbers. The tests below pin that.
"""

import pytest

from metatv.core.channel_name_utils import _extract_episode_marker, parse_channel_name


# --------------------------------------------------------------------------
# The marker comes out
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name, title, season, episode", [
    ("Konusanlar S01E57 1080p EXXEN WEB-DL [TR] AAC H264-TURG",
     "Konusanlar", "01", "57"),
    ("Mahsun.J.S02E01.1080p.GAiN.WEB-DL.AAC2.0.H.264-TR.SUBS.GAIN.XT",
     "Mahsun J", "02", "01"),
    ("Sekizinci Aile S01E04", "Sekizinci Aile", "01", "04"),
    ("Strife MMA 15 - S01E04", "Strife MMA 15", "01", "04"),
    # Separator variants the providers actually use.
    ("Leyla ile Mecnun S2 E4", "Leyla ile Mecnun", "2", "4"),
    ("Gibi S01.E05", "Gibi", "01", "05"),
    ("Atiye s01e02", "Atiye", "01", "02"),
    # Three-digit episode numbers.
    ("Bir Zamanlar S01E120", "Bir Zamanlar", "01", "120"),
])
def test_the_marker_leaves_the_title_and_is_kept(name, title, season, episode):
    parsed = parse_channel_name(name)
    assert parsed.bare_name == title
    assert parsed.season == season
    assert parsed.episode == episode


def test_the_numbers_are_kept_as_written():
    """"01" and "1" are the same episode, but a provider is consistent within a
    show and the zero-padding is what a display wants. Callers that need to
    sort call int() at that point."""
    parsed = parse_channel_name("Konusanlar S01E04")
    assert parsed.season == "01" and parsed.episode == "04"
    assert isinstance(parsed.season, str) and isinstance(parsed.episode, str)


def test_every_episode_of_a_show_yields_one_title():
    """The whole point: 414 rows collapsing to one card.

    ``content_key`` is derived from ``detected_title``, so identical titles are
    what makes the collapse happen — asserted here as the property rather than
    trusting that the individual parses "look right".
    """
    names = [f"Konusanlar S01E{n:02d} 1080p EXXEN WEB-DL [TR] AAC H264-TURG"
             for n in range(1, 40)]
    titles = {parse_channel_name(n).bare_name for n in names}
    assert titles == {"Konusanlar"}
    episodes = {parse_channel_name(n).episode for n in names}
    assert len(episodes) == 39, "each episode must keep its own number"


# --------------------------------------------------------------------------
# The patterns NOT implemented, and why
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name, title", [
    # Every one of these is a real film in the owner's library. A "NxNN"
    # pattern would rename them AND stamp them with a season and episode.
    ("DE - 10x10 (2018)", "10x10"),
    ("ES - 10x10 (2018)", "10x10"),
    ("AR - 8x10 Tasveer  (2009)", "8x10 Tasveer"),
    ("IN - 12x12", "12x12"),
    ("IT - 10x10", "10x10"),
])
def test_the_1x05_form_is_not_an_episode_marker(name, title):
    """14 rows matched it and all 14 are films. Symmetry would be a bug."""
    parsed = parse_channel_name(name)
    assert parsed.bare_name == title
    assert parsed.season == "" and parsed.episode == ""


@pytest.mark.parametrize("name", [
    "EN - WWE Raw (2023)",
    "EN - Se7en (1995)",
    "EN - Ocean's Eleven (2001)",
    "US| ESPN2",
    "EN - The Godfather (1972)",
])
def test_ordinary_titles_gain_nothing(name):
    parsed = parse_channel_name(name)
    assert parsed.season == "" and parsed.episode == ""


def test_the_extractor_returns_the_name_untouched_when_there_is_no_marker():
    """Explicit, so the caller can fall through without a special case."""
    assert _extract_episode_marker("10x10") == ("10x10", "", "")
    assert _extract_episode_marker("Konusanlar S01E57") == ("Konusanlar", "01", "57")


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------

def test_the_columns_exist_on_the_channel_model():
    """Render code reads the stored field and never re-parses (CLAUDE.md)."""
    from metatv.core.database import ChannelDB

    assert hasattr(ChannelDB, "detected_season")
    assert hasattr(ChannelDB, "detected_episode")


def test_existing_databases_get_the_columns_added():
    """A new column is useless if only fresh databases have it.

    ``database.py`` carries an explicit ALTER list for exactly this; a column
    added to the model and not to that list leaves every existing install
    raising ``no such column`` on the next query.
    """
    from pathlib import Path

    import metatv.core.database as mod

    source = Path(mod.__file__).read_text()
    for column in ("detected_season", "detected_episode"):
        assert f'"{column}"' in source, f"{column} missing from the ALTER list"


def test_ingestion_stores_both(tmp_path):
    """The write path, executed — not asserted by reading the source."""
    from metatv.core.database import ChannelDB, Database
    from metatv.core.repositories import RepositoryFactory

    db = Database(f"sqlite:///{tmp_path / 'ep.db'}")
    db.create_tables()
    with db.session_scope() as session:
        for i, name in enumerate([
            "Konusanlar S01E57 1080p EXXEN WEB-DL [TR] AAC H264-TURG",
            "DE - 10x10 (2018)",
        ]):
            session.add(ChannelDB(id=f"c{i}", source_id=str(i), provider_id="p",
                                  name=name, media_type="movie",
                                  stream_url=f"http://x/{i}"))
    with db.session_scope() as session:
        RepositoryFactory(session).channels.update_detected_prefixes(provider_id=None)
    with db.session_scope() as session:
        rows = {c.id: (c.detected_title, c.detected_season, c.detected_episode)
                for c in session.query(ChannelDB).all()}
    assert rows["c0"] == ("Konusanlar", "01", "57")
    assert rows["c1"] == ("10x10", None, None), (
        "a film must gain neither a season nor an episode")


def test_the_reparse_migration_was_bumped():
    """Existing rows are only re-derived when the version moves — without this
    the fix reaches nothing already in the library."""
    from metatv.core.migrations.detected_title_reparse import CURRENT_VERSION

    assert CURRENT_VERSION >= 12
