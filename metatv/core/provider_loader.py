"""Provider data loading and management"""

import asyncio
from typing import Optional, Dict, Any, List
from PyQt6.QtCore import QThread, pyqtSignal
from loguru import logger

from metatv.core.models import Provider, MediaType
from metatv.core.database import Database, ChannelDB, SeasonDB, EpisodeDB
from metatv.providers.factory import get_provider


class ProviderLoadThread(QThread):
    """Background thread for loading provider data into database"""
    
    finished = pyqtSignal(bool, str)  # success, message
    progress = pyqtSignal(int, int, str)  # current, total, message
    
    def __init__(self, provider: Provider, db: Database):
        super().__init__()
        self.provider = provider
        self.db = db
    
    def run(self):
        """Load provider data"""
        try:
            asyncio.run(self.load_provider())
        except Exception as e:
            logger.error(f"Provider load error: {e}")
            self.finished.emit(False, str(e))
    
    async def load_provider(self):
        """Load provider data using provider plugin"""
        # Get provider plugin
        provider_plugin = get_provider(self.provider.type)
        if not provider_plugin:
            self.finished.emit(False, f"Unknown provider type: {self.provider.type}")
            return
        
        # Progress callback
        def on_progress(current, total, message):
            self.progress.emit(current, total, message)
        
        # Fetch channels using provider plugin
        channels = await provider_plugin.fetch_channels(self.provider, progress_callback=on_progress)
        
        total = len(channels)
        logger.info(f"Loaded {total:,} items from {self.provider.name}")
        
        # Store in database
        session = self.db.get_session()
        
        try:
            processed = 0
            
            # Process all channels
            for channel in channels:
                db_channel = ChannelDB(
                    id=channel.id,
                    source_id=channel.source_id,
                    provider_id=channel.provider_id,
                    name=channel.name,
                    stream_url=channel.stream_url,
                    category=channel.category,
                    category_id=channel.category_id,
                    logo_url=channel.logo_url,
                    media_type=channel.media_type,
                    quality=channel.quality.value,
                    raw_data=channel.raw_data
                )
                session.merge(db_channel)
                
                processed += 1
                if processed % 100 == 0:
                    session.commit()  # Commit periodically
                    percent = int(70 + (processed / total * 30))
                    self.progress.emit(percent, 100, f"Processing channels ({processed:,}/{total:,})...")
            
            # Final commit
            session.commit()
            self.progress.emit(100, 100, f"Completed loading {total:,} channels")
            self.finished.emit(True, f"Loaded {total:,} channels successfully")
            
        except Exception as e:
            session.rollback()
            logger.error(f"Database error during provider load: {e}")
            raise
        finally:
            session.close()


class ProviderTestThread(QThread):
    """Background thread for testing provider connection"""
    
    result = pyqtSignal(bool, str)  # success, message
    progress = pyqtSignal(str)  # status message
    
    def __init__(self, provider_type: str, url: str, username: str, password: str):
        super().__init__()
        self.provider_type = provider_type
        self.url = url
        self.username = username
        self.password = password
    
    def run(self):
        """Run connection test"""
        try:
            asyncio.run(self.test_provider())
        except Exception as e:
            logger.error(f"Connection test error: {e}")
            self.result.emit(False, str(e))
    
    async def test_provider(self):
        """Test provider connection using provider plugin"""
        self.progress.emit("Testing connection...")
        
        # Get provider plugin
        provider_plugin = get_provider(self.provider_type)
        if not provider_plugin:
            self.result.emit(False, f"Unknown provider type: {self.provider_type}")
            return
        
        # Test connection
        self.progress.emit("Checking DNS and connectivity...")
        success, error = await provider_plugin.test_connection(self.url, self.username, self.password)
        
        if not success:
            self.result.emit(False, f"Connection failed: {error}")
            return
        
        self.result.emit(True, "Connection successful!")


class SeriesLoadThread(QThread):
    """Background thread for loading series details (seasons and episodes)"""
    
    finished = pyqtSignal(bool, str, object)  # success, message, series_data
    progress = pyqtSignal(str)  # status message
    
    def __init__(self, provider: Provider, series_id: str, series_name: str, db: Database):
        super().__init__()
        self.provider = provider
        self.series_id = series_id
        self.series_name = series_name
        self.db = db
    
    def run(self):
        """Load series details"""
        try:
            asyncio.run(self.load_series())
        except Exception as e:
            logger.error(f"Series load error: {e}")
            self.finished.emit(False, str(e), None)
    
    async def load_series(self):
        """Load series details using provider plugin"""
        self.progress.emit(f"Fetching series information for {self.series_name}...")
        
        # Get provider plugin
        provider_plugin = get_provider(self.provider.type)
        if not provider_plugin:
            self.finished.emit(False, f"Unknown provider type: {self.provider.type}", None)
            return
        
        # Fetch series information
        series_data = await provider_plugin.fetch_series_info(self.provider, self.series_id)
        
        if not series_data:
            self.finished.emit(False, "Could not fetch series information", None)
            return
        
        # Debug: Log the structure of what we received
        logger.debug(f"Series data type: {type(series_data)}")
        logger.debug(f"Series data keys: {series_data.keys() if isinstance(series_data, dict) else 'NOT A DICT'}")
        
        # Handle case where API returns unexpected format
        if not isinstance(series_data, dict):
            logger.error(f"Expected dict from fetch_series_info, got {type(series_data)}")
            self.finished.emit(False, f"Unexpected API response format: {type(series_data)}", None)
            return
        
        self.progress.emit("Storing seasons and episodes...")
        
        # Store in database
        with self.db.get_session() as session:
            # Parse and store seasons
            seasons = series_data.get("seasons", [])
            episodes_data = series_data.get("episodes", {})
            
            # Debug logging
            logger.debug(f"Seasons type: {type(seasons)}, count: {len(seasons) if isinstance(seasons, list) else 'N/A'}")
            if seasons and len(seasons) > 0:
                logger.debug(f"First season type: {type(seasons[0])}, value: {seasons[0]}")
            logger.debug(f"Episodes type: {type(episodes_data)}")
            if isinstance(episodes_data, list) and len(episodes_data) > 0:
                logger.debug(f"First episode item type: {type(episodes_data[0])}")
            
            # Handle both dict and list formats for episodes
            if isinstance(episodes_data, dict):
                # Episodes keyed by season number
                episodes_by_season = episodes_data
            elif isinstance(episodes_data, list):
                # Check if this is a list of lists (nested structure)
                # or a flat list of episode dicts
                episodes_by_season = {}
                
                # Flatten nested lists if needed
                flat_episodes = []
                for item in episodes_data:
                    if isinstance(item, list):
                        # Nested list - flatten it
                        flat_episodes.extend(item)
                    elif isinstance(item, dict):
                        # Already flat
                        flat_episodes.append(item)
                    else:
                        logger.error(f"Unexpected episode item type: {type(item)}")
                
                # Group episodes by season number
                for ep in flat_episodes:
                    if not isinstance(ep, dict):
                        logger.error(f"Episode is not a dict: {type(ep)}")
                        continue
                    season_num = str(ep.get("season", 0))
                    if season_num not in episodes_by_season:
                        episodes_by_season[season_num] = []
                    episodes_by_season[season_num].append(ep)
            else:
                logger.error(f"Unexpected episodes data type: {type(episodes_data)}")
                episodes_by_season = {}
            
            season_count = len(seasons)
            total_episodes = sum(len(eps) for eps in episodes_by_season.values())
            
            logger.info(f"Found {season_count} seasons and {total_episodes} episodes for {self.series_name}")
            
            for season_data in seasons:
                logger.debug(f"Processing season, type: {type(season_data)}, value: {season_data}")
                
                # Handle case where season_data might be a list instead of dict
                if isinstance(season_data, list):
                    logger.error(f"Season data is a list, expected dict: {season_data}")
                    continue
                
                season_num = season_data.get("season_number", 0)
                season_id = f"{self.series_id}_s{season_num}"
                
                # Check if season exists
                existing_season = session.query(SeasonDB).filter_by(id=season_id).first()
                
                season_episodes = episodes_by_season.get(str(season_num), [])
                
                if existing_season:
                    # Update existing
                    existing_season.name = season_data.get("name", f"Season {season_num}")
                    existing_season.cover_url = season_data.get("cover", "")
                    existing_season.episode_count = len(season_episodes)
                    existing_season.raw_data = season_data
                else:
                    # Create new
                    season = SeasonDB(
                        id=season_id,
                        series_id=self.series_id,
                        provider_id=self.provider.id,
                        season_number=season_num,
                        name=season_data.get("name", f"Season {season_num}"),
                        cover_url=season_data.get("cover", ""),
                        episode_count=len(season_episodes),
                        series_name=self.series_name,
                        raw_data=season_data
                    )
                    session.add(season)
                
                # Store episodes for this season
                for episode_data in season_episodes:
                    if not isinstance(episode_data, dict):
                        logger.error(f"Episode data is not a dict in season {season_num}: {type(episode_data)}, value: {episode_data}")
                        continue
                    
                    episode_id = episode_data.get("id", "")
                    episode_num = int(episode_data.get("episode_num", 0))
                    
                    db_episode_id = f"{self.provider.id}_{episode_id}"
                    
                    # Check if episode exists
                    existing_episode = session.query(EpisodeDB).filter_by(id=db_episode_id).first()
                    
                    # Build stream URL
                    container = episode_data.get("container_extension", "mp4")
                    stream_url = f"{self.provider.url}/series/{self.provider.username}/{self.provider.password}/{episode_id}.{container}"
                    
                    if existing_episode:
                        # Update existing
                        existing_episode.title = episode_data.get("title", f"Episode {episode_num}")
                        existing_episode.duration = episode_data.get("duration", "")
                        existing_episode.stream_url = stream_url
                        existing_episode.cover_url = episode_data.get("info", {}).get("movie_image", "")
                        existing_episode.container_extension = container
                        existing_episode.raw_data = episode_data
                    else:
                        # Create new
                        episode = EpisodeDB(
                            id=db_episode_id,
                            season_id=season_id,
                            series_id=self.series_id,
                            provider_id=self.provider.id,
                            episode_id=episode_id,
                            episode_num=episode_num,
                            season_num=season_num,
                            title=episode_data.get("title", f"Episode {episode_num}"),
                            duration=episode_data.get("duration", ""),
                            container_extension=container,
                            stream_url=stream_url,
                            cover_url=episode_data.get("info", {}).get("movie_image", ""),
                            series_name=self.series_name,
                            raw_data=episode_data
                        )
                        session.add(episode)
            
            session.commit()
            logger.info(f"Stored {season_count} seasons and {total_episodes} episodes for {self.series_name}")
        
        self.finished.emit(True, f"Loaded {season_count} seasons", series_data)

