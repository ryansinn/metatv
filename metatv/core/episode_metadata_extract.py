"""Shared chokepoint: extract episode-grain metadata from a raw Xtream episode dict.

Xtream/provider episode payloads carry per-episode plot/air-date/rating/still-image
data, but key spellings vary by provider (``overview`` vs ``plot``, ``air_date`` vs
``releaseDate`` vs ``release_date``, ``still_path`` vs ``movie_image``) and some
fields live at the top level while others live under ``info``. This module is the
ONE place that variance is resolved (single-chokepoint principle, CLAUDE.md) —
both live ingestion (:mod:`metatv.core.provider_loader`, at write time) and the
one-time :class:`~metatv.core.migrations.episode_metadata_backfill.EpisodeMetadataBackfillTask`
(reading the already-stored ``raw_data`` blob) call :func:`extract_episode_metadata_fields`
so the parsing logic never drifts between the two call sites. Render code must
never call this at read time — it reads the stored ``EpisodeDB`` columns this
function populates (compute-once-at-ingestion, CLAUDE.md).
"""

from __future__ import annotations

from typing import Any


def coerce_episode_rating(value: Any) -> float | None:
    """Safely coerce a provider-supplied rating value to ``float``, or ``None``.

    Never raises — junk input (``""``, ``"N/A"``, ``None``, garbage strings,
    ``NaN``) all coerce to ``None`` rather than propagating an exception up
    through ingestion or the backfill migration.

    Args:
        value: The raw rating value from ``info["rating"]`` / ``episode_data["rating"]``
            — may be a float, int, numeric string, junk string, or ``None``.

    Returns:
        A finite ``float``, or ``None`` when the value is absent/unparseable/NaN.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        # bool is a subclass of int in Python — reject it explicitly so a stray
        # True/False provider value never becomes a nonsensical 1.0/0.0 rating.
        return None
    if isinstance(value, (int, float)):
        try:
            f = float(value)
        except (TypeError, ValueError):
            return None
        return f if f == f else None  # f == f is False only for NaN
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            f = float(stripped)
        except ValueError:
            return None
        return f if f == f else None
    return None


def extract_episode_metadata_fields(episode_data: dict | None) -> dict[str, Any]:
    """Extract ``plot``/``air_date``/``rating``/``still_url`` from a raw episode dict.

    Reads both the top level of *episode_data* and its ``info`` sub-dict (key
    spellings vary by provider — see module docstring) and always returns a
    dict with all four keys present, mapping to ``None`` when the source data
    doesn't carry that field. Never guesses/synthesizes a value.

    Args:
        episode_data: The raw provider episode dict (the exact shape stored
            verbatim as ``EpisodeDB.raw_data``) — or ``None``/non-dict, tolerated.

    Returns:
        ``{"plot": str | None, "air_date": str | None, "rating": float | None,
        "still_url": str | None}``.
    """
    if not isinstance(episode_data, dict):
        return {"plot": None, "air_date": None, "rating": None, "still_url": None}

    info = episode_data.get("info")
    if not isinstance(info, dict):
        info = {}

    plot = (
        info.get("overview")
        or info.get("plot")
        or episode_data.get("overview")
        or episode_data.get("plot")
        or None
    )

    air_date = (
        info.get("air_date")
        or info.get("releaseDate")
        or info.get("release_date")
        or episode_data.get("air_date")
        or episode_data.get("releaseDate")
        or episode_data.get("release_date")
        or None
    )

    rating_raw = info.get("rating")
    if rating_raw is None:
        rating_raw = episode_data.get("rating")
    rating = coerce_episode_rating(rating_raw)

    still_url = (
        info.get("still_path")
        or info.get("movie_image")
        or episode_data.get("still_path")
        or episode_data.get("movie_image")
        or None
    )

    return {"plot": plot, "air_date": air_date, "rating": rating, "still_url": still_url}
