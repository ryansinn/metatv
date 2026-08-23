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
from typing import Any, Optional


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


def first_or_none(value: Any) -> Optional[str]:
    """First element of a list, the value itself if it is a string, else None.

    Xtream returns ``backdrop_path`` as a LIST of urls while every other image
    field is a bare string, so a caller that assumes either shape is wrong half
    the time.
    """
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return value if isinstance(value, str) and value else None


def extract_artwork(info: dict) -> tuple[Optional[str], Optional[str]]:
    """``(poster_url, backdrop_url)`` from an Xtream ``info`` dict.

    The ONE place the artwork keys and their precedence are written down.
    ``cover`` before ``movie_image`` because a detail blob that carries both
    puts the poster in ``cover`` and a smaller list-grade image in
    ``movie_image``.

    No fallback to the channel's own ``logo_url`` here — that is a decision
    about a CHANNEL, not about a detail blob, and it belongs to the caller that
    has one (see ``ProviderMetadataProvider.get_details``).

    Args:
        info: The blob's info dict (see :func:`extract_info`).

    Returns:
        ``(poster, backdrop)``, either of which may be ``None``.
    """
    poster = info.get("cover") or info.get("movie_image")
    return (poster if isinstance(poster, str) and poster else None,
            first_or_none(info.get("backdrop_path")))


#: The keys :func:`harvest_detail_metadata` returns, owned by the function that
#: PRODUCES them rather than by the writer that consumes them — so adding a
#: field is one edit here, and no consumer can drift from the contract.
#: ``genres`` leads because ``apply_metadata_harvest`` counts only that one.
HARVEST_FIELDS = ("genres", "plot", "cast", "director", "poster_url", "backdrop_url")


def harvest_detail_metadata(data: Any) -> dict:
    """Pull genre/plot/cast/director/ARTWORK out of a ``get_vod_info`` /
    ``get_series_info`` blob.

    Used by the enrichment sweep to salvage the metadata the sparse list
    ``raw_data`` omits for movies.  Every field comes back empty (``[]`` /
    ``None``) when absent, so a caller can safely fill-only-empty without a
    presence check per field.

    **Artwork was missing from this harvest until 2026-08-23**, and its absence
    had teeth. The bulk catalog frequently carries ``stream_icon: null``, so for
    those titles the ONLY place a poster ever appears is this blob — yet the
    sweep read the blob, took four fields, and dropped the image on the floor.
    When the pre-#438 cache clobber then emptied a stored ``poster_url``, there
    was nothing left in the tree that could put it back: 60 of the owner's 70
    damaged rows were unrecoverable for exactly this reason.

    Args:
        data: The parsed detail-endpoint response (dict, ``None``, or anything).

    Returns:
        ``{"genres": list[str], "plot": str|None, "cast": list[dict],
        "director": str|None, "poster_url": str|None,
        "backdrop_url": str|None}``.
    """
    info = extract_info(data)
    poster, backdrop = extract_artwork(info)
    return {
        "genres": parse_genres(info.get("genre", "")),
        "plot": info.get("plot") or info.get("description"),
        "cast": parse_cast_string(info.get("cast", "")),
        "director": info.get("director"),
        "poster_url": poster,
        "backdrop_url": backdrop,
    }
