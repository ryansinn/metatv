"""Single source of truth for the derived-field coverage census population (W-0).

Both the guard test (``tests/test_derived_field_coverage.py``, one
representative fixture row per media_type) and the measurement script
(``scripts/derived_field_coverage.py``, a real database's non-null RATE per
field per media_type) census the exact same fields — a single list here
keeps the two from drifting apart the way GUARD-4's plumbing/production
readers would have if each guard hand-listed its own copy.

See ``tests/test_derived_field_coverage.py``'s module docstring for WHY this
particular field set and not the rest of ``ChannelDB``/``MetadataDB`` — the
scoping reasoning lives there since it's about the guard's design, not a fact
about the schema.
"""

from __future__ import annotations

#: ChannelDB columns computed by ingestion (XtreamAPI.convert_to_channel +
#: ChannelRepository.update_detected_prefixes), censused for all three
#: media types.
CHANNEL_FIELDS: tuple[str, ...] = (
    "detected_tmdb_id",
    "detected_rating",
    "detected_added",
    "detected_year",
    "content_key",
    "detected_genre",
    "detected_genres",
)

#: MetadataDB columns computed by metadata_from_raw (offline_metadata_backfill
#: + raw_field_backfill), censused for movie/series only — live channels never
#: get a MetadataDB row from this path (OfflineMetadataBackfillTask scopes its
#: candidate query to media_type IN ('movie', 'series')).
METADATA_FIELDS: tuple[str, ...] = (
    "title",
    "plot",
    "genres",
    "cast",
    "director",
    "rating",
    "release_date",
    "poster_url",
    "backdrop_url",
    "trailer_url",
    "runtime",
    "tagline",
    "content_rating",
    "tmdb_id",
)

#: Populations MetadataDB is censused for. ChannelDB is censused for all
#: three media types — see the module each field list documents above.
METADATA_MEDIA_TYPES: tuple[str, ...] = ("movie", "series")
CHANNEL_MEDIA_TYPES: tuple[str, ...] = ("live", "movie", "series")


def is_empty(value: object) -> bool:
    """Same sentinel set ``offline_metadata_backfill._fill`` treats as
    "nothing to store" — reused rather than re-derived (CLAUDE.md: one
    definition, not a parallel heuristic).
    """
    return value in (None, "", [], {})
