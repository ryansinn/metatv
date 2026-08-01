"""Shared parsing of Xtream VOD/series detail blobs — single source of truth.

Two callers turn the same Xtream ``info`` shape into structured metadata:

* :class:`~metatv.metadata_providers.provider_metadata.ProviderMetadataProvider`
  reads a channel's cached **list** ``raw_data`` (sparse for movies — no genre).
* :class:`~metatv.core.tmdb_enrichment_manager.TmdbEnrichmentManager` fetches the
  per-title **detail** endpoint (``get_vod_info`` / ``get_series_info``), whose
  response *does* carry the movie's genre / plot / cast / director.

Keeping the genre and cast parsing here means there is exactly one genre parser
and one cast parser in the codebase (Governing Principle: single chokepoint).
"""

from __future__ import annotations

import re
from typing import Any


def parse_genres(genre_str: Any) -> list[str]:
    """Split a provider genre string into a clean list.

    Some providers use ``" / "`` (Xtream/TREX style), others use ``","`` — both are
    handled.  ``"&"`` is deliberately NOT a separator (``"Action & Adventure"`` is a
    single genre).

    Args:
        genre_str: Raw ``genre`` value from the provider blob (string or anything).

    Returns:
        List of trimmed, non-empty genre names (empty list when absent).
    """
    if not genre_str:
        return []
    return [g.strip() for g in re.split(r"\s*/\s*|,\s*", str(genre_str)) if g.strip()]


def parse_cast_string(cast_str: Any) -> list[dict[str, Any]]:
    """Parse a comma-separated cast string into the structured TMDb-shaped list.

    Args:
        cast_str: ``"Actor1, Actor2, Actor3"`` style string (or anything falsy).

    Returns:
        List of ``{"name", "character", "photo_url"}`` dicts (empty list when absent).
    """
    if not cast_str:
        return []
    names = [name.strip() for name in str(cast_str).split(",") if name.strip()]
    return [{"name": name, "character": None, "photo_url": None} for name in names]


def extract_info(raw: Any) -> dict:
    """Return the Xtream ``info`` dict from a detail/list blob (nested or flat).

    Mirrors :meth:`ProviderMetadataProvider.get_details`'s structure handling:
    prefer a nested ``info`` dict; otherwise treat the blob itself as the info dict
    and drop the stream-API placeholder ratings (always ``'10'`` / ``'5'``).

    Args:
        raw: The parsed detail/list response (dict, or anything defensively).

    Returns:
        The info dict, or an empty dict when *raw* is not a usable mapping.
    """
    if not isinstance(raw, dict):
        return {}
    info = raw.get("info")
    if isinstance(info, dict) and info:
        return info
    flat = dict(raw)
    flat.pop("rating", None)
    flat.pop("rating_5based", None)
    return flat


def harvest_detail_metadata(data: Any) -> dict:
    """Pull genre/plot/cast/director out of a ``get_vod_info``/``get_series_info`` blob.

    Used by the enrichment sweep to salvage the metadata the sparse list ``raw_data``
    omits for movies.  Every field comes back empty (``[]`` / ``None``) when absent,
    so a caller can safely fill-only-empty without a presence check per field.

    Args:
        data: The parsed detail-endpoint response (dict, ``None``, or anything).

    Returns:
        ``{"genres": list[str], "plot": str|None, "cast": list[dict],
        "director": str|None}``.
    """
    info = extract_info(data)
    return {
        "genres": parse_genres(info.get("genre", "")),
        "plot": info.get("plot") or info.get("description"),
        "cast": parse_cast_string(info.get("cast", "")),
        "director": info.get("director"),
    }
