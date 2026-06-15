"""Database models and connection management"""

from contextlib import contextmanager
from datetime import datetime
import json as _json
from typing import Optional
from sqlalchemy import create_engine, Column, String, Integer, Boolean, DateTime, Float, Text, JSON, text, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.types import TypeDecorator
from loguru import logger

Base = declarative_base()


class JSONEncoded(TypeDecorator):
    """Stores any JSON-serializable Python object as TEXT in SQLite.

    Use instead of Column(JSON) to avoid SQLite JSON-type quirks. Assign plain
    Python objects (lists, dicts, None); serialization is transparent.

        cast = Column(JSONEncoded)   # assign/read a Python list — no json.dumps/loads needed
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return _json.dumps(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return _json.loads(value)


class ChannelDB(Base):
    """Channel database model"""
    __tablename__ = "channels"
    
    id = Column(String, primary_key=True)
    source_id = Column(String, nullable=False, index=True)
    provider_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False, index=True)
    stream_url = Column(Text)  # Cached URL, can be reconstructed dynamically
    
    category = Column(String, default="", index=True)
    category_id = Column(String)
    
    language = Column(String, index=True)
    detected_prefix = Column(String, index=True)   # Separator-delimited prefix token (e.g. "EN", "NF", "4K")
    detected_quality = Column(String, index=True)  # Quality token found anywhere in name (e.g. "HD", "4K", "UHD")
    detected_region = Column(String, index=True)   # Parenthetical lang/region suffix (e.g. "(US)"→"US", "(JP)"→"JP")
    detected_title = Column(String)                # Bare channel name with all prefixes/suffixes stripped
    detected_year = Column(String)                 # Year or range extracted from name (e.g. "2025", "1993-2002")
    logo_url = Column(Text)  # Channel logo/icon
    cover_url = Column(Text)  # Series/Movie cover art (for future use)
    epg_channel_id = Column(String)
    
    media_type = Column(String, default="unknown", index=True)
    quality = Column(String, default="unknown", index=True)
    
    metadata_id = Column(String, index=True)
    
    is_favorite = Column(Boolean, default=False, index=True)
    is_hidden = Column(Boolean, default=False, index=True)  # hidden from all views
    is_adult = Column(Boolean, default=False, index=True)
    is_rec_suppressed = Column(Boolean, default=False, index=True)  # hidden from recommendations only
    last_played = Column(DateTime)
    play_count = Column(Integer, default=0)

    raw_data = Column(JSON)
    
    # Special content categorization (PPV, Events, Sports)
    special_view = Column(String, index=True)  # 'ppv', 'live_event', 'sports', or NULL
    event_start_time = Column(DateTime, index=True)  # Parsed event date/time for PPV/events
    sport_type = Column(String, index=True)  # 'soccer', 'basketball', 'football', etc.
    league_name = Column(String, index=True)  # 'Premier League', 'NBA', 'NFL', etc.
    team_name = Column(String, index=True)  # 'Manchester United', 'Lakers', etc.
    event_metadata = Column(JSONEncoded)  # Additional parsed data (event name, quality, etc.)

    rec_shown_count = Column(Integer, default=0, index=True)  # impression counter for recommendation decay
    rec_last_shown  = Column(DateTime, nullable=True)           # for per-session cooldown deduplication

    # Provider-ordering and header-derived category (live channels only)
    # source_num: the `num` field from the Xtream API — provider's canonical display order
    # source_category: label extracted from the nearest preceding ##...## header in the stream list
    # source_quality_flags: comma-separated quality markers decoded from that header (HD,RAW,60FPS,UHD)
    source_num           = Column(Integer, index=True)
    source_category      = Column(String,  index=True)
    source_quality_flags = Column(String)

    # User-defined category — assigned via "Add to Category" right-click action.
    # Appears as a custom Discovery shelf; influences recommendations via category_mood.
    # category_mood: "like" | "curious" | "not_interested" | "dislike" | None (neutral)
    user_category = Column(String, index=True)
    category_mood = Column(String)

    added_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class MetadataDB(Base):
    """Metadata database model"""
    __tablename__ = "metadata"
    
    id = Column(String, primary_key=True)
    title = Column(String, nullable=False, index=True)
    
    year = Column(Integer, index=True)
    runtime = Column(Integer)
    
    genres = Column(JSONEncoded)
    media_type = Column(String, default="unknown", index=True)

    # People (cast is the new name, actors kept for backwards compatibility)
    actors = Column(JSONEncoded)  # Deprecated: use cast instead
    cast = Column(JSONEncoded)  # [{name, character, photo_url}]
    crew = Column(JSONEncoded)  # [{name, job, department}]
    director = Column(String)
    
    plot = Column(Text)
    tagline = Column(Text)
    
    # Ratings
    rating = Column(Float)
    rating_count = Column(Integer)
    
    # Images
    poster_url = Column(Text)
    backdrop_url = Column(Text)
    
    # Links
    imdb_id = Column(String, index=True)
    tmdb_id = Column(String, index=True)
    trailer_url = Column(Text)
    
    # Technical
    content_rating = Column(String)  # PG-13, TV-MA, etc.
    release_date = Column(String)  # ISO date format
    
    source = Column(String, default="unknown")
    fetched_at = Column(DateTime, default=datetime.now)


class ProviderDB(Base):
    """Provider database model"""
    __tablename__ = "providers"
    
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)
    
    url = Column(Text, nullable=False)
    urls = Column(JSONEncoded)  # List of ProviderURL objects
    username = Column(String)
    password = Column(String)  # TODO: Encrypt this
    
    refresh_schedule = Column(String, default="manual")
    last_refresh = Column(DateTime)
    
    is_active = Column(Boolean, default=True)
    last_sync = Column(DateTime)
    last_error = Column(Text)
    
    total_channels = Column(Integer, default=0)
    total_categories = Column(Integer, default=0)
    max_connections = Column(Integer, default=1)  # Maximum simultaneous streams allowed by provider

    # Customization
    icon = Column(String, default="")       # User-chosen emoji/icon e.g. "🔥" or "⭐"
    color = Column(String, default="")      # CSS hex color for sidebar label e.g. "#ff8800"
    epg_url = Column(String, default="")   # XMLTV EPG feed URL
    force_adult = Column(Boolean, default=False)  # Treat all channels as adult regardless of is_adult flag
    epg_last_fetched = Column(DateTime, nullable=True)      # When EPG was last downloaded
    epg_data_start = Column(DateTime, nullable=True)        # Earliest start_time in fetched EPG data
    epg_data_end = Column(DateTime, nullable=True)          # Latest stop_time in fetched EPG data
    epg_refresh_hours_before = Column(Integer, default=48)  # Refresh when data expires within N hours
    epg_enabled = Column(Boolean, default=True)  # If False, skip EPG fetch and exclude from EPG surfaces
    epg_refresh_interval = Column(String, default="default")  # Per-source throttle: "default"|"every_open"|"4h"|…|"when_stale"
    epg_url_override = Column(String, nullable=True)  # User-supplied XMLTV URL; blank/NULL = use auto-built epg_url

    # Account info cached from provider API
    account_status = Column(String)         # Active, Expired, Banned, Disabled
    account_exp_date = Column(DateTime)     # Subscription expiry
    account_created_at = Column(DateTime)   # Account creation date
    account_active_cons = Column(Integer, default=0)  # Active connections at last check

    added_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class FilterDB(Base):
    """Filter database model"""
    __tablename__ = "filters"
    
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    
    is_global = Column(Boolean, default=False, index=True)
    provider_id = Column(String, index=True)
    
    rules = Column(JSON, nullable=False)
    
    is_enabled = Column(Boolean, default=True)
    order = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class AlertPatternDB(Base):
    """Watch alert pattern database model"""
    __tablename__ = "alert_patterns"
    
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False, index=True)
    description = Column(Text)
    
    pattern_type = Column(String, nullable=False, index=True)  # keyword, regex, genre, actor, quality, media_type
    pattern_value = Column(String, nullable=False)
    
    applies_to = Column(String, default="all", index=True)  # all, live, series, movies
    
    is_enabled = Column(Boolean, default=True, index=True)
    last_checked = Column(DateTime)
    
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class AlertMatchDB(Base):
    """Alert match database model - tracks channels matching alert patterns"""
    __tablename__ = "alert_matches"
    
    id = Column(String, primary_key=True)
    alert_pattern_id = Column(String, nullable=False, index=True)
    channel_id = Column(String, nullable=False, index=True)
    
    matched_at = Column(DateTime, default=datetime.now, index=True)
    is_viewed = Column(Boolean, default=False, index=True)
    is_dismissed = Column(Boolean, default=False, index=True)
    
    created_at = Column(DateTime, default=datetime.now)


class SeasonDB(Base):
    """Season database model - for TV series hierarchy"""
    __tablename__ = "seasons"
    
    id = Column(String, primary_key=True)  # {series_id}_s{season_num}
    series_id = Column(String, nullable=False, index=True)  # Links to ChannelDB.id
    provider_id = Column(String, nullable=False, index=True)
    
    season_number = Column(Integer, nullable=False, index=True)
    name = Column(String)  # e.g., "Season 1"
    cover_url = Column(Text)  # For future cover art display
    episode_count = Column(Integer, default=0)
    
    # Series info (denormalized for convenience)
    series_name = Column(String, index=True)
    
    raw_data = Column(JSON)
    
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class EpisodeDB(Base):
    """Episode database model - for TV series episodes"""
    __tablename__ = "episodes"
    
    id = Column(String, primary_key=True)  # {provider_id}_{episode_id}
    season_id = Column(String, nullable=False, index=True)  # Links to SeasonDB.id
    series_id = Column(String, nullable=False, index=True)  # Links to ChannelDB.id
    provider_id = Column(String, nullable=False, index=True)
    
    episode_id = Column(String, nullable=False)  # From API
    episode_num = Column(Integer, nullable=False, index=True)
    season_num = Column(Integer, nullable=False, index=True)
    
    title = Column(String, nullable=False, index=True)
    duration = Column(String)  # e.g., "45:30"
    container_extension = Column(String, default="mp4")
    stream_url = Column(Text)  # Cached playback URL
    cover_url = Column(Text)  # Episode thumbnail for future use
    
    # Playback tracking
    is_watched = Column(Boolean, default=False, index=True)
    watch_progress = Column(Integer, default=0)  # seconds watched
    last_played = Column(DateTime, index=True)
    play_count = Column(Integer, default=0)
    
    # Series info (denormalized for convenience)
    series_name = Column(String, index=True)
    
    raw_data = Column(JSON)
    
    added_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class EpgProgramDB(Base):
    """EPG programme — one scheduled broadcast slot from an XMLTV feed."""
    __tablename__ = "epg_programmes"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    provider_id    = Column(String, nullable=False, index=True)
    channel_epg_id = Column(String, nullable=False, index=True)  # XMLTV <channel id="...">
    channel_db_id  = Column(String, nullable=True,  index=True)  # matched ChannelDB.id
    title          = Column(String, nullable=False,  index=True)
    description    = Column(Text, default="")
    start_time     = Column(DateTime, nullable=False, index=True)
    stop_time      = Column(DateTime, nullable=False, index=True)
    is_live        = Column(Boolean, default=False)  # ᴸᶦᵛᵉ badge stripped from title
    is_new         = Column(Boolean, default=False)  # ᴺᵉʷ badge stripped from title


class UserRatingDB(Base):
    """User rating for a movie or series — +1 (like) or -1 (dislike)."""
    __tablename__ = "user_ratings"

    channel_id = Column(String, primary_key=True)   # 1:1 with ChannelDB; upsert replaces
    rating     = Column(Integer, nullable=False)     # +1 or -1
    rated_at   = Column(DateTime, default=datetime.utcnow)


class WatchQueueDB(Base):
    """Ordered watch queue — content the user wants to watch soon."""
    __tablename__ = "watch_queue"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    channel_id   = Column(String, nullable=False)            # no FK — channels may be replaced on refresh
    channel_name = Column(String, nullable=False, default="")  # denormalized — survives channel ID changes
    media_type   = Column(String, nullable=False, default="")  # "movie", "series", "live"
    source_id    = Column(String, nullable=False, default="")  # provider's native stream ID (fallback lookup)
    position     = Column(Integer, nullable=False, default=0)
    added_at     = Column(DateTime, default=datetime.utcnow)


class StreamRetryDB(Base):
    """Tracks streams that failed validation so they can be re-checked later."""
    __tablename__ = "stream_retry"

    id              = Column(String, primary_key=True)
    channel_id      = Column(String, nullable=False, unique=True)
    channel_name    = Column(String, nullable=False, default="")
    stream_url      = Column(String, nullable=False, default="")
    first_failed_at = Column(DateTime, default=datetime.utcnow)
    last_checked_at = Column(DateTime)
    next_check_at   = Column(DateTime)
    attempt_count   = Column(Integer, default=0)
    last_error      = Column(String)
    status          = Column(String, default="pending")  # "pending" | "online"


class Database:
    """Database connection manager"""

    def __init__(self, database_url: str):
        self.engine = create_engine(
            database_url,
            echo=False,
            connect_args={"check_same_thread": False, "timeout": 30},
        )

        @event.listens_for(self.engine, "connect")
        def _set_pragmas(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

        self.SessionLocal = sessionmaker(bind=self.engine)
        logger.info(f"Database initialized: {database_url}")
    
    def create_tables(self):
        """Create all tables"""
        Base.metadata.create_all(self.engine)
        logger.info("Database tables created")
        self._migrate()

    def _migrate(self):
        """Apply incremental schema migrations (safe to run on every startup)."""
        migrations = [
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
        ]
        with self.engine.connect() as conn:
            for table, col, col_type in migrations:
                try:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
                    conn.commit()
                    logger.info(f"Migration: added column {col} to {table}")
                except Exception:
                    pass  # column already exists

        self._normalize_double_encoded_json()

    # JSONEncoded columns that, prior to the B3-3 TypeDecorator, were written via
    # ``json.dumps(obj)`` into a ``Column(JSON)`` — double-encoding the value on disk.
    # JSONEncoded decodes exactly once, so those legacy rows would read back as JSON
    # *strings* instead of lists/dicts. See _normalize_double_encoded_json.
    _JSON_ENCODED_COLUMNS = [
        ("metadata",  "cast"),
        ("metadata",  "crew"),
        ("metadata",  "actors"),
        ("metadata",  "genres"),
        ("providers", "urls"),
        ("channels",  "event_metadata"),
    ]

    def _normalize_double_encoded_json(self):
        """One-time fix for legacy double-encoded JSONEncoded values (pre-B3-3).

        Old code assigned ``json.dumps(obj)`` into ``Column(JSON)``, which serialized
        the value a second time — storing a JSON *string* (on-disk text begins with a
        quote, e.g. ``"[{...}]"``) rather than a JSON array/object. ``JSONEncoded``
        decodes once, so such rows now read back as ``str``. This peels the extra layer.

        Only rows whose raw TEXT begins with ``"`` (a double-encoded string) are
        touched; correctly single-encoded rows (``[``/``{``) are skipped, so the pass
        is idempotent. Gated on ``PRAGMA user_version`` so it runs at most once.
        """
        with self.engine.connect() as conn:
            try:
                version = conn.execute(text("PRAGMA user_version")).scalar() or 0
            except Exception:
                version = 0
            if version >= 1:
                return

            for table, col in self._JSON_ENCODED_COLUMNS:
                try:
                    rows = conn.execute(text(
                        f'SELECT rowid, "{col}" FROM {table} WHERE "{col}" LIKE \'"%\''
                    )).fetchall()
                except Exception:
                    continue  # table/column not present in this DB
                fixed = 0
                for rowid, raw in rows:
                    try:
                        inner = _json.loads(raw)
                    except Exception:
                        continue
                    if not isinstance(inner, str):
                        continue  # not actually double-encoded
                    conn.execute(
                        text(f'UPDATE {table} SET "{col}" = :v WHERE rowid = :r'),
                        {"v": inner, "r": rowid},
                    )
                    fixed += 1
                if fixed:
                    logger.info(f"Migration: normalized {fixed} double-encoded {table}.{col} value(s)")

            conn.execute(text("PRAGMA user_version = 1"))
            conn.commit()

    def get_session(self) -> Session:
        """Get a new database session"""
        return self.SessionLocal()

    @contextmanager
    def session_scope(self, commit: bool = True):
        """Context manager that commits on success, rolls back on exception, always closes.

        Preferred form for new code (supersedes raw try/finally around get_session):
            with self.db.session_scope() as session:
                repos = RepositoryFactory(session)
                ...

        Pass ``commit=False`` for a read-only scope: it never issues a COMMIT, and rolls
        back at exit so any accidental write in a read path is discarded rather than
        persisted. The async-read seam (``_run_query``) uses ``commit=False`` — its
        ``query_fn`` returns plain data and must not write.
        """
        session = self.SessionLocal()
        try:
            yield session
            if commit:
                session.commit()
            else:
                session.rollback()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def close(self):
        """Close database connection"""
        self.engine.dispose()
        logger.info("Database connection closed")
