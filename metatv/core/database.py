"""Database models and connection management"""

from datetime import datetime
from typing import Optional
from sqlalchemy import create_engine, Column, String, Integer, Boolean, DateTime, Float, Text, JSON, text, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from loguru import logger

Base = declarative_base()


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
    detected_prefix = Column(String, index=True)  # Auto-detected prefix for filtering (e.g., "EN", "AR", "4K")
    logo_url = Column(Text)  # Channel logo/icon
    cover_url = Column(Text)  # Series/Movie cover art (for future use)
    epg_channel_id = Column(String)
    
    media_type = Column(String, default="unknown", index=True)
    quality = Column(String, default="unknown", index=True)
    
    metadata_id = Column(String, index=True)
    
    is_favorite = Column(Boolean, default=False, index=True)
    is_hidden = Column(Boolean, default=False, index=True)
    is_adult = Column(Boolean, default=False, index=True)
    last_played = Column(DateTime)
    play_count = Column(Integer, default=0)

    raw_data = Column(JSON)
    
    # Special content categorization (PPV, Events, Sports)
    special_view = Column(String, index=True)  # 'ppv', 'live_event', 'sports', or NULL
    event_start_time = Column(DateTime, index=True)  # Parsed event date/time for PPV/events
    sport_type = Column(String, index=True)  # 'soccer', 'basketball', 'football', etc.
    league_name = Column(String, index=True)  # 'Premier League', 'NBA', 'NFL', etc.
    team_name = Column(String, index=True)  # 'Manchester United', 'Lakers', etc.
    event_metadata = Column(JSON)  # Additional parsed data (event name, quality, etc.)
    
    added_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class MetadataDB(Base):
    """Metadata database model"""
    __tablename__ = "metadata"
    
    id = Column(String, primary_key=True)
    title = Column(String, nullable=False, index=True)
    
    year = Column(Integer, index=True)
    runtime = Column(Integer)
    
    genres = Column(JSON)
    media_type = Column(String, default="unknown", index=True)
    
    # People (cast is the new name, actors kept for backwards compatibility)
    actors = Column(JSON)  # Deprecated: use cast instead
    cast = Column(JSON)  # [{name, character, photo_url}]
    crew = Column(JSON)  # [{name, job, department}]
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
    urls = Column(JSON)  # List of ProviderURL objects
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
    epg_data_end = Column(DateTime, nullable=True)          # Latest stop_time in fetched EPG data
    epg_refresh_hours_before = Column(Integer, default=48)  # Refresh when data expires within N hours

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
            cur.execute("PRAGMA busy_timeout=5000")
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
            ("providers", "epg_last_fetched",          "DATETIME"),
            ("providers", "epg_data_end",              "DATETIME"),
            ("providers", "epg_refresh_hours_before",  "INTEGER DEFAULT 48"),
        ]
        with self.engine.connect() as conn:
            for table, col, col_type in migrations:
                try:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
                    conn.commit()
                    logger.info(f"Migration: added column {col} to {table}")
                except Exception:
                    pass  # column already exists
    
    def get_session(self) -> Session:
        """Get a new database session"""
        return self.SessionLocal()
    
    def close(self):
        """Close database connection"""
        self.engine.dispose()
        logger.info("Database connection closed")
