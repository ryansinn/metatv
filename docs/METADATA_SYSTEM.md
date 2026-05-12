# MetaTV Metadata System

## Overview

MetaTV uses a plugin-based metadata system to enrich channel data with comprehensive information (plot, cast, ratings, artwork, etc.). The system supports multiple metadata providers with intelligent fallback chains, caching, and merge logic.

## Architecture

### Core Components

1. **MetadataProviderPlugin** (Base Class)
   - Abstract interface for all metadata providers
   - Location: `metatv/metadata_providers/base.py`
   - Defines standard methods: `get_details()`, `search()`, `get_images()`

2. **MetadataResult** (Data Class)
   - Container for metadata fields
   - Location: `metatv/metadata_providers/base.py`
   - Fields: title, year, plot, poster_url, cast, crew, genres, ratings, etc.
   - Includes intelligent merge() logic with confidence scoring

3. **MetadataManager** (Orchestrator)
   - Coordinates metadata fetching across providers
   - Location: `metatv/core/metadata_manager.py`
   - Handles caching, provider chain, and fallback logic

4. **MetadataProviderRegistry** (Registry)
   - Manages available metadata providers
   - Location: `metatv/core/metadata_manager.py`
   - Handles provider priority and selection

5. **MetadataDB** (Database Model)
   - SQLAlchemy model for cached metadata
   - Location: `metatv/core/database.py`
   - Stores enriched metadata with TTL-based expiration

### Data Flow

```
┌─────────────────┐
│  User selects   │
│    channel      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ MetadataManager │◄─────── config.yaml (priority, TTL)
│  .get_metadata()│
└────────┬────────┘
         │
         ├──── Check cache (MetadataDB)
         │     └── If fresh → Return cached data
         │
         ├──── Provider chain (by priority)
         │     ├── ProviderMetadataProvider (raw_data)
         │     ├── TMDbProvider (external API) [future]
         │     └── OMDbProvider (external API) [future]
         │
         ├──── Merge results (confidence-based)
         │     └── MetadataResult.merge(other)
         │
         └──── Save to cache (MetadataDB)
               └── Return merged metadata
```

## MetadataResult Class

### Fields

```python
@dataclass
class MetadataResult:
    # Basic info
    title: Optional[str] = None
    year: Optional[int] = None
    plot: Optional[str] = None
    
    # Images
    poster_url: Optional[str] = None
    backdrop_url: Optional[str] = None
    logo_url: Optional[str] = None
    
    # People
    cast: Optional[list[dict]] = None        # [{"name": str, "character": str, "photo_url": str}]
    crew: Optional[list[dict]] = None        # [{"name": str, "job": str, "department": str}]
    director: Optional[str] = None
    
    # Classification
    genres: Optional[list[str]] = None
    content_rating: Optional[str] = None      # "PG-13", "TV-MA", etc.
    
    # Ratings
    rating: Optional[float] = None            # 0.0-10.0 scale
    vote_count: Optional[int] = None
    imdb_rating: Optional[float] = None
    rt_rating: Optional[int] = None           # Rotten Tomatoes 0-100
    
    # Technical
    runtime: Optional[int] = None             # Minutes
    release_date: Optional[str] = None        # ISO date format
    original_language: Optional[str] = None   # ISO 639-1 code
    
    # Links
    trailer_url: Optional[str] = None         # YouTube video ID
    homepage: Optional[str] = None
    imdb_id: Optional[str] = None
    tmdb_id: Optional[int] = None
    
    # Metadata
    confidence: float = 0.0                   # 0.0-1.0 (higher = more reliable)
    source_provider: Optional[str] = None     # Which provider supplied this data
    last_updated: Optional[datetime] = None
```

### Merge Logic

The `merge()` method intelligently combines metadata from multiple providers:

```python
def merge(self, other: 'MetadataResult') -> 'MetadataResult':
    """Merge another MetadataResult into this one
    
    Rules:
    - If target (self) is empty (no title/plot/poster), accept all from other
    - If both have data, prefer higher confidence
    - Always keep existing data if other is None
    """
    # Check if target is effectively empty
    target_empty = not self.title and not self.plot and not self.poster_url
    
    if target_empty:
        # Accept all fields from other
        return other
    
    # Merge field by field
    if other.confidence > self.confidence:
        # Other has higher confidence - prefer its non-None fields
        for field in fields(self):
            other_value = getattr(other, field.name)
            if other_value is not None:
                setattr(self, field.name, other_value)
    else:
        # Keep existing data, fill in gaps from other
        for field in fields(self):
            if getattr(self, field.name) is None:
                setattr(self, field.name, getattr(other, field.name))
    
    return self
```

**Example**:
```python
# Provider data (low confidence but fast)
provider_meta = MetadataResult(
    title="Breaking Bad",
    plot="Short description",
    poster_url="http://provider.com/poster.jpg",
    confidence=0.5
)

# TMDb data (high confidence but slower)
tmdb_meta = MetadataResult(
    title="Breaking Bad",
    plot="Detailed plot from TMDb...",
    cast=[...],  # Full cast list
    crew=[...],  # Full crew list
    confidence=0.9
)

# Merge: TMDb overwrites plot, adds cast/crew
result = provider_meta.merge(tmdb_meta)
# result.plot = TMDb's detailed plot (higher confidence)
# result.cast = TMDb's cast list (was None in provider)
# result.poster_url = provider's poster (TMDb didn't provide)
```

## Provider Chain

### Configuration

Providers are configured in `config.yaml`:

```yaml
metadata_provider_priority:
  - "provider"    # Built-in (fast, limited data)
  - "tmdb"        # External API (slow, rich data)
  - "omdb"        # External API (slow, ratings)

metadata_enabled_providers:
  - "provider"
  # Uncomment when API keys configured:
  # - "tmdb"
  # - "omdb"
```

### Execution Flow

```python
def get_metadata(self, channel_id: str, force_refresh: bool = False) -> Optional[MetadataResult]:
    """Fetch metadata with provider fallback chain"""
    
    # 1. Check cache (if not force refresh)
    if not force_refresh:
        cached = self._get_from_cache(channel_id)
        if cached and not self._is_expired(cached):
            return cached
    
    # 2. Try providers in priority order
    merged_result = MetadataResult()
    
    for provider_name in self.config.metadata_provider_priority:
        if provider_name not in self.config.metadata_enabled_providers:
            continue
        
        provider = self.registry.get_provider(provider_name)
        if not provider:
            continue
        
        try:
            result = provider.get_details(channel, session)
            if result:
                merged_result = merged_result.merge(result)
        except Exception as e:
            logger.error(f"Provider {provider_name} failed: {e}", exc_info=True)
    
    # 3. Save to cache
    if merged_result.title:  # Only cache if we got something
        self._save_metadata_cache(channel_id, merged_result)
    
    return merged_result if merged_result.title else None
```

### Three-Tier Loading

1. **Database Cache** (instant)
   - Cached metadata from previous fetches
   - TTL-based expiration (default: 30 days)
   - Fastest option

2. **Provider Data** (fast)
   - Extract from Xtream API `raw_data` field
   - Already cached in ChannelDB
   - Zero network latency
   - Limited data (title, year, plot, poster, cast)

3. **External APIs** (slow)
   - TMDb, OMDb, FanartTV, TVDB
   - Rich metadata and high-quality images
   - Requires API keys
   - Network latency (100-500ms per request)

## Built-in Providers

### ProviderMetadataProvider

**Location**: `metatv/metadata_providers/provider_metadata.py`

**Purpose**: Extract metadata from Xtream API `raw_data` field

**Supported Fields**:
- Title, year, plot
- Poster URL (with fallback chain: cover → movie_image → logo_url)
- Cast (parsed from comma-separated string)
- Rating (0-10 scale)
- Genres
- Duration
- Release date

**Advantages**:
- Zero latency (data already in database)
- No API key required
- Always available

**Limitations**:
- Limited metadata (depends on provider)
- Image quality varies by provider
- No crew/director information
- Limited cast details (names only, no photos)

**Example raw_data**:
```json
{
  "info": {
    "name": "Breaking Bad",
    "cover": "http://provider.com/images/breaking_bad.jpg",
    "plot": "Chemistry teacher turns to making meth...",
    "cast": "Bryan Cranston, Aaron Paul, Anna Gunn",
    "rating": "9.5",
    "genre": "Crime, Drama, Thriller",
    "duration": "47",
    "releasedate": "2008-01-20"
  }
}
```

**Implementation**:
```python
class ProviderMetadataProvider(MetadataProviderPlugin):
    def get_details(self, channel: ChannelDB, session) -> Optional[MetadataResult]:
        """Extract metadata from channel.raw_data"""
        if not channel.raw_data:
            return None
        
        try:
            data = json.loads(channel.raw_data)
            info = data.get("info", data)  # Handle nested or flat structure
            
            # Poster fallback chain
            poster_url = (
                info.get("cover") or 
                info.get("movie_image") or 
                channel.logo_url
            )
            
            # Parse comma-separated cast
            cast = self._parse_cast_string(info.get("cast", ""))
            
            return MetadataResult(
                title=info.get("name") or channel.name,
                year=self._parse_year(info.get("releasedate")),
                plot=info.get("plot") or info.get("description"),
                poster_url=poster_url,
                cast=cast,
                rating=self._parse_rating(info.get("rating")),
                genres=self._parse_genres(info.get("genre")),
                runtime=self._parse_int(info.get("duration")),
                release_date=info.get("releasedate"),
                confidence=0.6,  # Medium confidence (provider data quality varies)
                source_provider="provider"
            )
        except Exception as e:
            logger.error(f"Failed to extract provider metadata: {e}", exc_info=True)
            return None
    
    def _parse_cast_string(self, cast_str: str) -> list[dict]:
        """Parse 'Actor1, Actor2, Actor3' into list of dicts"""
        if not cast_str:
            return []
        
        return [
            {
                "name": name.strip(),
                "character": None,
                "photo_url": None
            }
            for name in cast_str.split(",")
            if name.strip()
        ]
```

## Future Providers

### TMDbProvider (The Movie Database)

**Status**: Planned for Phase 2

**Features**:
- Comprehensive movie/TV metadata
- High-quality images (posters, backdrops)
- Full cast and crew with photos
- Multiple languages
- User ratings and reviews

**API Key**: Free at https://www.themoviedb.org/settings/api

**Rate Limit**: 40 requests per 10 seconds

### OMDbProvider (Open Movie Database)

**Status**: Planned for Phase 2

**Features**:
- Movie/TV metadata
- IMDb and Rotten Tomatoes ratings
- Simple API
- Good for ratings aggregation

**API Key**: Free (with limits) at http://www.omdbapi.com/apikey.aspx

**Rate Limit**: 1,000 requests per day (free tier)

### FanartTvProvider

**Status**: Future consideration

**Features**:
- High-quality artwork
- TV show logos, clearart
- Character art
- Multiple image types

**API Key**: Required at https://fanart.tv/get-an-api-key/

### TVDBProvider (TheTVDB)

**Status**: Future consideration

**Features**:
- Episode-level metadata
- Season/episode structure
- Air dates
- Episode descriptions and thumbnails

**API Key**: Required at https://thetvdb.com/api-information

## Database Caching

### Schema

```python
class MetadataDB(Base):
    __tablename__ = "metadata"
    
    channel_id = Column(String, ForeignKey("channels.id"), primary_key=True)
    
    # Basic info
    title = Column(String)
    year = Column(Integer)
    plot = Column(Text)
    
    # Images
    poster_url = Column(String)
    backdrop_url = Column(String)
    logo_url = Column(String)
    
    # People (JSON arrays)
    cast = Column(String)  # JSON string: [{"name": str, "character": str, ...}]
    crew = Column(String)  # JSON string: [{"name": str, "job": str, ...}]
    director = Column(String)
    
    # Classification
    genres = Column(String)  # JSON string: ["Crime", "Drama"]
    content_rating = Column(String)
    
    # Ratings
    rating = Column(Float)
    vote_count = Column(Integer)
    
    # Technical
    runtime = Column(Integer)
    release_date = Column(String)
    original_language = Column(String)
    
    # Links
    trailer_url = Column(String)
    homepage = Column(String)
    imdb_id = Column(String)
    tmdb_id = Column(Integer)
    
    # Metadata
    confidence = Column(Float, default=0.0)
    source_provider = Column(String)
    last_updated = Column(DateTime, default=datetime.utcnow)
```

### JSON Storage

SQLAlchemy's JSON type has compatibility issues with SQLite. Use manual serialization:

```python
import json

# Saving
metadata.cast = json.dumps(result.cast) if result.cast else None
metadata.crew = json.dumps(result.crew) if result.crew else None
metadata.genres = json.dumps(result.genres) if result.genres else None
session.commit()

# Loading
cast = json.loads(metadata.cast) if metadata.cast else []
crew = json.loads(metadata.crew) if metadata.crew else []
genres = json.loads(metadata.genres) if metadata.genres else []
```

### Cache TTL

Metadata expires after `metadata_cache_ttl_days` (default: 30 days):

```python
def _is_expired(self, metadata: MetadataDB) -> bool:
    """Check if cached metadata has expired"""
    if not metadata.last_updated:
        return True
    
    ttl = timedelta(days=self.config.metadata_cache_ttl_days)
    age = datetime.utcnow() - metadata.last_updated
    return age > ttl
```

Force refresh with `get_metadata(channel_id, force_refresh=True)`

## Thread Safety

Metadata fetching is I/O-bound and must not block the UI.

### Correct Pattern

```python
from concurrent.futures import ThreadPoolExecutor
from PyQt6.QtCore import pyqtSignal

class MainWindow(QWidget):
    # Signal for cross-thread communication
    metadata_loaded = pyqtSignal(str, object)  # channel_id, MetadataResult
    
    def __init__(self):
        super().__init__()
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.metadata_loaded.connect(self._update_ui_with_metadata)
    
    def load_metadata(self, channel_id: str):
        """Start background metadata fetch"""
        # Update UI immediately (main thread)
        self.details_pane.show_loading_state()
        
        # Submit to worker thread
        future = self.executor.submit(self._fetch_metadata, channel_id)
        future.add_done_callback(lambda f: self._on_done(f, channel_id))
    
    def _fetch_metadata(self, channel_id: str) -> Optional[MetadataResult]:
        """Worker thread - do NOT update UI"""
        return self.metadata_manager.get_metadata(channel_id)
    
    def _on_done(self, future, channel_id: str):
        """Worker thread - emit signal to marshal to main thread"""
        try:
            metadata = future.result()
            self.metadata_loaded.emit(channel_id, metadata)
        except Exception as e:
            logger.error(f"Metadata fetch failed: {e}", exc_info=True)
    
    def _update_ui_with_metadata(self, channel_id: str, metadata: MetadataResult):
        """Main thread - safe to update UI"""
        self.details_pane.show_metadata(metadata)
```

### Anti-Pattern (DO NOT DO THIS)

```python
# ❌ WRONG: Update UI from worker thread
def _fetch_metadata(self, channel_id: str):
    metadata = self.metadata_manager.get_metadata(channel_id)
    self.details_pane.show_metadata(metadata)  # CRASH! Wrong thread!
```

## Creating a Metadata Provider

### Step 1: Create Provider Class

Create `metatv/metadata_providers/your_provider.py`:

```python
from metatv.metadata_providers.base import MetadataProviderPlugin, MetadataResult
from metatv.core.database import ChannelDB
from loguru import logger
from typing import Optional

class YourProvider(MetadataProviderPlugin):
    """Your provider description"""
    
    @property
    def name(self) -> str:
        """Unique identifier (lowercase, no spaces)"""
        return "your_provider"
    
    @property
    def display_name(self) -> str:
        """Human-readable name"""
        return "Your Provider"
    
    @property
    def supported_media_types(self) -> list[str]:
        """Which media types this provider supports"""
        return ["live", "movie", "series"]
    
    @property
    def supported_fields(self) -> list[str]:
        """Which metadata fields this provider can supply"""
        return ["title", "plot", "cast", "poster_url", "rating"]
    
    def get_details(self, channel: ChannelDB, session) -> Optional[MetadataResult]:
        """Fetch metadata for a channel
        
        Args:
            channel: Channel database model
            session: SQLAlchemy session
        
        Returns:
            MetadataResult with fetched data, or None if not found
        """
        try:
            # Your API logic here
            data = self._fetch_from_api(channel.name)
            
            if not data:
                return None
            
            return MetadataResult(
                title=data.get("title"),
                year=data.get("year"),
                plot=data.get("plot"),
                poster_url=data.get("poster"),
                cast=self._parse_cast(data.get("cast", [])),
                rating=data.get("rating"),
                confidence=0.9,  # 0.0-1.0 scale
                source_provider=self.name
            )
        
        except Exception as e:
            logger.error(f"{self.display_name} failed: {e}", exc_info=True)
            return None
    
    def _fetch_from_api(self, title: str) -> dict:
        """Your API implementation"""
        # Make HTTP request, parse response, etc.
        pass
```

### Step 2: Register Provider

Add to `MetadataProviderRegistry` in `metatv/core/metadata_manager.py`:

```python
# In __init__ of MetadataProviderRegistry
from metatv.metadata_providers.your_provider import YourProvider

self.register(YourProvider())
```

### Step 3: Configure

Add to `config.yaml`:

```yaml
metadata_provider_priority:
  - "provider"
  - "your_provider"  # Add your provider

metadata_enabled_providers:
  - "provider"
  - "your_provider"  # Enable your provider

# Add any API key/config needed
metadata_your_provider_api_key: "your_key_here"
```

### Step 4: Test

```python
# In your development environment
from metatv.core.metadata_manager import MetadataManager

manager = MetadataManager(config, session)
metadata = manager.get_metadata(channel_id="test_channel")

if metadata:
    print(f"Title: {metadata.title}")
    print(f"Plot: {metadata.plot}")
    print(f"Confidence: {metadata.confidence}")
```

## Best Practices

### 1. Set Appropriate Confidence

```python
# Low confidence (0.1-0.4): Scraped data, unreliable source
confidence=0.3

# Medium confidence (0.5-0.7): Provider data, decent quality
confidence=0.6

# High confidence (0.8-1.0): Authoritative API (TMDb, OMDb)
confidence=0.9
```

### 2. Handle Missing Data Gracefully

```python
# Don't set fields to empty strings - use None
plot = data.get("plot") or None  # Not ""
cast = data.get("cast") if data.get("cast") else None  # Not []
```

### 3. Parse Data Defensively

```python
def _parse_year(self, date_str: str) -> Optional[int]:
    """Extract year from date string"""
    if not date_str:
        return None
    
    try:
        # Handle "2008-01-20" or "2008"
        return int(date_str[:4])
    except (ValueError, TypeError):
        return None
```

### 4. Log Errors with Context

```python
try:
    result = self.fetch_data(channel.name)
except requests.ConnectionError as e:
    logger.error(f"Connection failed for '{channel.name}': {e}", exc_info=True)
    return None
except Exception as e:
    logger.error(f"Unexpected error fetching '{channel.name}': {e}", exc_info=True)
    return None
```

### 5. Respect Rate Limits

```python
import time

class RateLimitedProvider(MetadataProviderPlugin):
    def __init__(self):
        self.last_request = 0
        self.min_interval = 0.1  # 100ms between requests
    
    def get_details(self, channel, session):
        # Enforce rate limit
        elapsed = time.time() - self.last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        
        self.last_request = time.time()
        # ... fetch logic
```

## Troubleshooting

### No metadata loading

1. Check enabled providers: `config.yaml → metadata_enabled_providers`
2. Verify API keys configured (for external providers)
3. Check logs: `~/.config/metatv/logs/metatv.log`
4. Test provider manually in Python REPL

### Wrong metadata

1. Check provider priority: `config.yaml → metadata_provider_priority`
2. Verify confidence scores (higher wins)
3. Force refresh: `metadata_manager.get_metadata(channel_id, force_refresh=True)`
4. Check cache: `select * from metadata where channel_id = '...'`

### Metadata not caching

1. Verify TTL setting: `config.yaml → metadata_cache_ttl_days`
2. Check if `title` is set (won't cache empty results)
3. Inspect database: `sqlite3 ~/.local/share/metatv/metatv.db`
4. Check for database errors in logs

### Slow metadata loading

1. Check provider order (try fast providers first)
2. Enable database caching
3. Increase cache TTL
4. Use background enrichment (future feature)
5. Check network latency to external APIs
