# MetaTV — Architecture Map

Directory layout and per-file responsibilities. Moved out of `CLAUDE.md` to keep the always-loaded
rules lean — this is orientation/reference, not an enforceable rule. Read it when you need the map.

```
metatv/
├── core/               # Business logic (no UI dependencies)
│   ├── config.py            # Pydantic config (~/.config/metatv/config.yaml)
│   ├── database.py          # SQLAlchemy models + connection
│   ├── channel_visibility.py # THE definition of "which channels are visible" (VisibilityScope + apply)
│   ├── channel_name_utils.py # Curated lookup tables (regions, quality, audio) + name parsing
│   ├── content_identity.py  # content_key_for() — tmdb-first cross-source identity, computed at ingestion
│   ├── epg_utils.py         # All EPG time/timezone helpers (UTC-naive storage, local display)
│   ├── filter_utils.py      # Exclusion-criterion builders shared by channel_visibility
│   ├── url_cycle.py         # THE way to try a provider's alternate URLs + record the outcome (UrlCycler)
│   ├── url_policy.py        # Resolved host-ranking knobs (UrlRankingPolicy); holds no Config
│   ├── tag_decomposer.py    # Facet/tag decomposition chokepoint (curated data lives in channel_name_utils)
│   ├── build_info.py        # Version resolution for the packaged app
│   ├── series_monitor.py    # Monitored-series episode-count polling + new-episode alerts
│   ├── preference_engine.py # Attribute-weight + TF-IDF recommendation scoring; RecScoringSettings dials
│   ├── media_mix.py         # Movie/series mix for rec lists (√-damped automatic share, or explicit)
│   ├── discovery_engine.py  # SQL queries for Discovery shelves (genre/decade/actor/director)
│   ├── content_dedup.py     # Cross-source title normalization + deduplication
│   ├── epg_manager.py       # EPG fetch/parse/store + watchlist notification timer
│   ├── image_cache.py       # Async image cache, MD5-keyed, LRU cleanup at 500MB
│   ├── metadata_manager.py  # Metadata provider chain + caching
│   ├── notifications.py     # Toast notification system
│   ├── provider_loader.py   # Background channel loading
│   ├── special_content.py   # PPV/Events/Sports detection + classification
│   ├── stream_retry_manager.py  # URL failover + retry logic
│   ├── xmltv_parser.py      # Streaming XMLTV parser (iterparse, 140MB+)
│   └── repositories/
│       ├── channel.py   # Channel queries (hidden_only, prefix filters, search)
│       ├── epg.py       # EPG programme queries (current, watchlist, browse, search)
│       ├── queue.py     # Watch queue CRUD (QueueEntry, WatchQueueRepository)
│       ├── dtos.py      # Frozen dataclasses for thread-safe sidebar/series data
│       └── provider.py  # Provider queries
├── gui/                # PyQt6 UI components
│   ├── theme.py              # Design tokens + role-named stylesheet constants + qt_palette() floor
│   ├── theme_palettes.py     # The three palettes (Midnight/Graphite/Daylight) — only home of hex literals
│   ├── icons.py              # Every icon/emoji/symbol in the app
│   ├── cursor_affordance.py  # set_clickable() — the only place PointingHandCursor is set
│   ├── channel_menu.py       # Channel context-menu registry (ACTIONS + SURFACE_LAYOUTS)
│   ├── channel_state_bus.py  # The one publish point for per-channel user-state changes
│   ├── main_window.py        # Three-panel main window + chip nav
│   ├── details_pane.py       # Right panel — metadata, play, favorite, hide/unhide
│   ├── discover_view.py      # Discovery view orchestration (glue layer, ~290 lines)
│   ├── discover_card.py      # Content card widget + flow layout helper
│   ├── discover_shelf.py     # Horizontal scroll shelf row widget
│   ├── discover_browse.py    # See-all drill-down view + search/grid
│   ├── discover_workers.py   # Background shelf-loading QThread workers
│   ├── similar_lightbox.py   # Similar Titles modal lightbox
│   ├── preferences_view.py   # Recommendations dashboard (attribute weights + exclusions)
│   ├── epg_view.py           # EPG view — Watchlist / On Now / Browse tabs
│   ├── global_filter_dialog.py  # Global content filter (prefix groups + Other expandable)
│   ├── events_view.py        # Live events view
│   ├── sports_view.py        # Sports events view
│   ├── sports_filter_bar.py  # Sport/league filter chips
│   ├── provider_editor.py    # Provider add/edit form
│   ├── settings_dialog.py    # App settings
│   ├── sidebar_sections.py   # CollapsibleSection base + sections (queue, recs, alerts, favorites, history)
│   └── notification_widget.py
├── providers/          # IPTV source plugins
│   ├── base.py         # ProviderPlugin abstract base
│   └── xtream.py       # Xtream API client
└── metadata_providers/ # Metadata enrichment plugins
    ├── base.py         # MetadataProviderPlugin + MetadataResult
    └── provider.py     # Extracts from Xtream raw_data (zero-latency)
```

**Data locations:**
- Config: `~/.config/metatv/config.yaml`
- Database: `~/.local/share/metatv/metatv.db`
- Logs: `~/.config/metatv/logs/`
- Image cache: `~/.cache/metatv/images/`
