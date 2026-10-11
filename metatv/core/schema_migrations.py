"""Columns added to tables after they first shipped — the ALTER TABLE list.

``Base.metadata.create_all()`` creates missing TABLES but never adds a column to
one that exists, so every column added later needs an entry here; ``Database
._migrate()`` applies each one an existing database lacks (CLAUDE.md, "A new DB
column needs an ALTER TABLE entry"; guard: tests/test_schema_upgrade_adds_every_column.py).
Split out of ``database.py``: it is data, and the longest thing in that module.
"""
from __future__ import annotations

COLUMN_MIGRATIONS: list[tuple[str, str, str]] = [
    ("providers", "account_status",      "TEXT"),
    ("providers", "account_exp_date",    "DATETIME"),
    ("providers", "account_created_at",  "DATETIME"),
    ("providers", "account_active_cons", "INTEGER DEFAULT 0"),
    ("providers", "icon",                "TEXT DEFAULT ''"),
    ("providers", "color",               "TEXT DEFAULT ''"),
    ("providers", "epg_url",             "TEXT DEFAULT ''"),
    ("providers", "force_adult",          "INTEGER DEFAULT 0"),
    ("channels",  "is_adult",             "INTEGER DEFAULT 0"),
    ("providers",    "epg_last_fetched",         "DATETIME"),
    ("providers",    "epg_data_start",           "DATETIME"),
    ("providers",    "epg_data_end",             "DATETIME"),
    ("providers",    "epg_refresh_hours_before", "INTEGER DEFAULT 48"),
    ("watch_queue",  "channel_name",             "TEXT NOT NULL DEFAULT ''"),
    ("watch_queue",  "media_type",               "TEXT NOT NULL DEFAULT ''"),
    ("watch_queue",  "source_id",                "TEXT NOT NULL DEFAULT ''"),
    ("epg_programmes", "channel_name",           "TEXT NOT NULL DEFAULT ''"),
    ("channels",     "is_rec_suppressed",        "INTEGER DEFAULT 0"),
    ("channels",     "rec_shown_count",           "INTEGER DEFAULT 0"),
    ("channels",     "rec_last_shown",            "DATETIME"),
    ("channels",     "source_num",                "INTEGER"),
    ("channels",     "source_category",           "TEXT"),
    ("channels",     "source_quality_flags",      "TEXT"),
    ("channels",     "detected_quality",           "TEXT"),
    ("channels",     "detected_region",            "TEXT"),
    ("channels",     "detected_title",             "TEXT"),
    ("channels",     "detected_year",              "TEXT"),
    ("channels",     "user_category",              "TEXT"),
    ("channels",     "category_mood",              "TEXT"),
    ("providers",    "epg_enabled",                "INTEGER DEFAULT 1"),
    ("providers",    "epg_refresh_interval",       "TEXT DEFAULT 'default'"),
    ("providers",    "epg_url_override",           "TEXT"),
    # Host that last served a parseable guide; see the column comment.
    ("providers",    "epg_last_good_base_url",     "TEXT"),
    ("providers",    "epg_unnamed_refetch_attempted", "INTEGER DEFAULT 0"),
    ("providers",    "epg_last_fetch_error",       "TEXT"),      # EPGF-1
    ("providers",    "epg_last_fetch_error_at",    "DATETIME"),  # EPGF-1
    ("channels",     "watch_progress",             "INTEGER DEFAULT 0"),
    ("channels",     "watch_completed",            "INTEGER DEFAULT 0"),
    ("channels",     "last_played_via",            "TEXT"),
    ("episodes",     "last_played_via",            "TEXT"),
    ("episodes",     "watch_progress",             "INTEGER DEFAULT 0"),
    ("episodes",     "watch_completed",            "INTEGER DEFAULT 0"),
    ("channels",     "watch_percent",              "INTEGER DEFAULT 0"),
    ("episodes",     "watch_percent",              "INTEGER DEFAULT 0"),
    ("channels",     "tag_fingerprint",            "TEXT"),
    ("channels",     "content_key",                "TEXT"),
    ("channels",     "detected_audio",             "TEXT"),
    ("channels",     "detected_tmdb_id",           "TEXT"),
    ("channels",     "tmdb_enrich_state",          "TEXT"),
    ("channels",     "genre_enrich_state",         "TEXT"),
    # Wave 2 Slice 2B — episode-grain watch queue + episode/season favorites.
    ("episodes",     "is_favorite",                "INTEGER DEFAULT 0"),
    ("seasons",      "is_favorite",                "INTEGER DEFAULT 0"),
    ("watch_queue",  "episode_id",                 "TEXT"),
    ("watch_queue",  "season_num",                 "INTEGER"),
    ("watch_queue",  "episode_num",                "INTEGER"),
    ("watch_queue",  "episode_title",              "TEXT"),
    # Discover genre-shelf perf (#genre-perf) — stored canonical genre(s),
    # computed at ingestion; see ChannelDB.detected_genre(s) above.
    ("channels",     "detected_genre",             "TEXT"),
    ("channels",     "detected_genres",            "TEXT"),
    # Wave 5 — graduated play-failure ledger (roadmap S3, #227).
    ("stream_retry", "play_fail_count",             "INTEGER DEFAULT 0"),
    ("stream_retry", "last_play_error",             "TEXT"),
    ("stream_retry", "reliability_state",           "TEXT DEFAULT 'ok'"),
    # Wave 6 — restricted-content name/prefix detection (owner-reported
    # gap); computed at ingestion, see ChannelDB.detected_restricted above.
    ("channels",     "detected_restricted",         "INTEGER DEFAULT 0"),
    # Wave 7 — category-marker cleanup (owner-reported gap); computed at
    # ingestion, see ChannelDB.detected_collection(_language|_subdub) above.
    ("channels",     "detected_collection",          "TEXT"),
    ("channels",     "detected_collection_language", "TEXT"),
    ("channels",     "detected_collection_subdub",   "TEXT"),
    # Trailing credits lifted from the name at ingestion (#278) — an
    # inference, see ChannelDB.detected_name_cast above.
    ("channels",     "detected_name_cast",           "TEXT"),
    # Collection lifted from the name after a mid-year marker; an
    # inference, see ChannelDB.detected_name_collection above.
    ("channels",     "detected_name_collection",      "TEXT"),
    ("channels",     "detected_season",               "TEXT"),
    ("channels",     "detected_episode",              "TEXT"),
    # Wave 4 — episode-grain metadata lifted from raw_data at ingestion
    # (#247); computed at ingestion, see EpisodeDB.plot/air_date/rating/
    # still_url above. Pre-existing rows backfilled by
    # EpisodeMetadataBackfillTask (no network access — reads stored raw_data).
    ("episodes",     "plot",                         "TEXT"),
    ("episodes",     "air_date",                     "TEXT"),
    ("episodes",     "rating",                       "FLOAT"),
    ("episodes",     "still_url",                    "TEXT"),
    # Wave 4 — background metadata enrichment queue (#249); bounded-retry
    # bookkeeping, see ChannelDB.metadata_enrich_state(_attempts) above.
    ("channels",     "metadata_enrich_state",         "TEXT"),
    ("channels",     "metadata_enrich_attempts",      "INTEGER DEFAULT 0"),
    # Signal checking (#617) and vanished-row pruning (#648) — BOTH
    # shipped without an entry here; see the guard below for why twice.
    ("channels",     "signal_verdict",                "TEXT"),
    ("channels",     "signal_dead_streak",            "INTEGER DEFAULT 0"),
    ("channels",     "signal_checked_at",             "DATETIME"),
    ("channels",     "last_seen_at",                  "DATETIME"),
    # The provider's own event end time (SPORT-1).
    ("channels",     "event_stop_time",               "DATETIME"),
    # Fixture opponents (SPORT-4) — see ChannelDB.event_team_a above.
    ("channels",     "event_team_a",                  "TEXT"),
    ("channels",     "event_team_b",                  "TEXT"),
    # WL-1 watch-rule fields; the UPDATE below stamps NULLs.
    ("alert_patterns", "whole_word",                  "INTEGER DEFAULT 1"),
    ("alert_patterns", "exclude_terms",               "TEXT"),
    ("alert_patterns", "match_mode",                  "TEXT DEFAULT 'phrase'"),
    ("alert_patterns", "search_description",           "INTEGER DEFAULT 0"),
    ("alert_patterns", "live_only",                    "INTEGER DEFAULT 0"),
    ("alert_patterns", "action",                       "TEXT DEFAULT 'notify'"),
    ("providers",     "last_catalog_refresh_at",         "DATETIME"),  # SPORT-7
    ("providers",     "last_live_refresh_at",            "DATETIME"),  # LIVE-1
    ("downloads",     "history_cleared",                 "INTEGER NOT NULL DEFAULT 0"),
    ("channels", "detected_rating", "FLOAT"), ("channels", "detected_added", "INTEGER"),  # DB-4
    # SCHEMA-1: twelve columns that predate this list but postdate their own
    # table's CREATE — the #617/#648 defect, found by widening the guard in
    # tests/test_schema_upgrade_adds_every_column.py to every table.
    ("providers",    "max_connections",               "INTEGER DEFAULT 1"),
    ("channels",     "special_view",                  "TEXT"),
    ("channels",     "event_start_time",              "DATETIME"),
    ("channels",     "sport_type",                    "TEXT"),
    ("channels",     "league_name",                   "TEXT"),
    ("channels",     "team_name",                     "TEXT"),
    ("channels",     "event_metadata",                "TEXT"),  # JSONEncoded -> Text
    ("metadata",     "cast",                          "TEXT"),  # JSONEncoded -> Text
    ("metadata",     "crew",                          "TEXT"),  # JSONEncoded -> Text
    ("metadata",     "trailer_url",                   "TEXT"),
    ("metadata",     "original_language",             "TEXT"),   # LANG-2
    ("metadata",     "alt_titles",                    "TEXT"),   # JSONEncoded -> Text
    ("stream_info",  "fingerprint",                   "TEXT"),   # recycled-id guard
    ("content_tags", "detail",                        "TEXT"),   # per-channel tag detail
    ("content_tags", "ord",                           "INTEGER"),
    ("content_tags", "qualifier",                     "INTEGER"),  # role bits
    ("metadata",     "content_rating",                "TEXT"),
    ("metadata",     "release_date",                  "TEXT"),
    ("channels",     "channel_key",                   "INTEGER"),  # DB-9
]
