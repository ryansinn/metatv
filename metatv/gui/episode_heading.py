"""The two text lines above an episode's title in the details pane.

    SEASON 2 · EPISODE 1 OF 12            AIRED 5 JUN 2025

Kept as plain functions so the wording is testable without building the pane.
The pane upper-cases both; they are written here in sentence case.
"""

from __future__ import annotations

from metatv.core.time_display import iso_date_text


def episode_eyebrow(episode, season_episode_count: int | None = None) -> str:
    """"Season 2 · Episode 1 of 12" — where this episode sits in its series.

    Season 0 is the provider's specials bucket, so it reads "Specials". The
    total is the source's own count for the season; it is left off when it is
    unknown or smaller than the episode number (a source listing part of a
    season must not claim "Episode 9 of 6").

    Args:
        episode: An ``EpisodeDTO`` (reads ``season_num`` and ``episode_num``).
        season_episode_count: Episodes the source lists for this season.

    Returns:
        The eyebrow text; empty when the episode carries no numbers at all.
    """
    season = getattr(episode, "season_num", None)
    number = getattr(episode, "episode_num", None)
    parts = []
    if season == 0:
        parts.append("Specials")
    elif season:
        parts.append(f"Season {season}")
    if number:
        of = (f" of {season_episode_count}"
              if season_episode_count and season_episode_count >= number else "")
        parts.append(f"Episode {number}{of}")
    return " · ".join(parts)


def aired_text(air_date: str | None) -> str:
    """"Aired 5 Jun 2025" in the user's date style, from the stored ISO date.

    The provider's value is stored verbatim; one that is not an ISO date is
    shown as it came rather than dropped.

    Args:
        air_date: ``EpisodeDTO.air_date`` (e.g. ``"2025-06-05"``) or ``None``.

    Returns:
        The caption, or ``""`` when there is no date.
    """
    text = iso_date_text(air_date)
    return f"Aired {text}" if text else ""
