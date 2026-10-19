"""The words above an episode title: ``gui/episode_heading.py``."""

from datetime import datetime
from types import SimpleNamespace

from metatv.core.time_display import date_text
from metatv.gui.episode_heading import aired_text, episode_eyebrow


def _ep(season, number):
    return SimpleNamespace(season_num=season, episode_num=number)


def test_season_episode_and_total():
    assert episode_eyebrow(_ep(2, 1), 12) == "Season 2 · Episode 1 of 12"


def test_total_left_off_when_unknown_or_too_small():
    assert episode_eyebrow(_ep(2, 1), None) == "Season 2 · Episode 1"
    # A source that lists only part of a season must not claim "9 of 6".
    assert episode_eyebrow(_ep(2, 9), 6) == "Season 2 · Episode 9"


def test_season_zero_reads_as_specials():
    assert episode_eyebrow(_ep(0, 3), 4) == "Specials · Episode 3 of 4"


def test_aired_uses_the_date_style_and_keeps_a_non_iso_value():
    assert aired_text("2025-06-05") == f"Aired {date_text(datetime(2025, 6, 5))}"
    assert aired_text("June 2025") == "Aired June 2025"
    assert aired_text(None) == ""
