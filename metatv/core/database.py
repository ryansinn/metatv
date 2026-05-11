"""Database models and connection management"""

from datetime import datetime
from typing import Optional
from sqlalchemy import create_engine, Column, String, Integer, Boolean, DateTime, Float, Text, JSON
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
    last_played = Column(DateTime)
    play_count = Column(Integer, default=0)
    
    raw_data = Column(JSON)
    
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
    
    actors = Column(JSON)
    director = Column(String)
    
    plot = Column(Text)
    tagline = Column(Text)
    
    rating = Column(Float)
    rating_count = Column(Integer)
    
    poster_url = Column(Text)
    backdrop_url = Column(Text)
    
    imdb_id = Column(String, index=True)
    tmdb_id = Column(String, index=True)
    
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


class Database:
    """Database connection manager"""
    
    def __init__(self, database_url: str):
        self.engine = create_engine(database_url, echo=False)
        self.SessionLocal = sessionmaker(bind=self.engine)
        logger.info(f"Database initialized: {database_url}")
    
    def create_tables(self):
        """Create all tables"""
        Base.metadata.create_all(self.engine)
        logger.info("Database tables created")
    
    def get_session(self) -> Session:
        """Get a new database session"""
        return self.SessionLocal()
    
    def close(self):
        """Close database connection"""
        self.engine.dispose()
        logger.info("Database connection closed")
