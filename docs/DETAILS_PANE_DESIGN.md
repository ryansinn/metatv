# Details Pane Design

## Overview
A right-side detail panel that shows rich metadata for selected content with progressive loading, intelligent caching, and **plugin-based metadata providers**.

## Implementation Status

### ✅ Phase 1 MVP (COMPLETED)
- ✅ Three-panel layout with collapsible splitters
- ✅ Click-to-collapse/expand functionality
- ✅ Basic metadata display (title, year, plot, poster, rating, genres)
- ✅ Collapsible sections (Technical Details, Cast & Crew)
- ✅ Play and Favorite buttons
- ✅ Three-tier loading (Database → Provider → External APIs)
- ✅ State persistence (width, visibility, collapsed sections)
- ✅ Single-click selection from favorites/history
- ✅ Qt threading fixes (pyqtSignal for thread-safe updates)
- ✅ Metadata plugin architecture (MetadataProviderPlugin, MetadataResult, registry)
- ✅ ProviderMetadataProvider (extracts from raw_data)
- ✅ Image cache with URL failover
- ✅ Poster fallback chain (cover → movie_image → logo_url)
- ✅ Loading indicators ("Loading poster...")

### 🔄 Phase 2 (PLANNED)
- [ ] TMDbProvider (external API for rich metadata)
- [ ] OMDbProvider (external API for ratings)
- [ ] Similar content recommendations
- [ ] User reviews and ratings
- [ ] Episode listings (for series)
- [ ] Trailer playback
- [ ] Background metadata enrichment
- [ ] Xtream VOD API enhancement (get_vod_info, get_live_info)

### 🐛 Known Issues
- **VOD Metadata Limitation**: Movies and live streams show minimal metadata because current implementation only uses `get_vod_streams` (basic info). Need to implement `get_vod_info()` and `get_live_info()` API calls for full metadata.
- **Episode Metadata**: Individual episodes don't show metadata in details pane. Need to extract episode-level metadata from series_info response.

## Current Implementation

The Phase 1 MVP is fully functional with the metadata plugin architecture in place. See these files for details:
- `metatv/metadata_providers/base.py` - MetadataProviderPlugin base class and MetadataResult
- `metatv/core/metadata_manager.py` - MetadataManager with provider fallback chain
- `metatv/metadata_providers/provider_metadata.py` - ProviderMetadataProvider implementation
- `metatv/gui/details_pane.py` - Details pane UI with progressive loading
- `docs/METADATA_SYSTEM.md` - Comprehensive metadata system documentation

## Metadata Provider Plugin Architecture

### Philosophy
Metadata sources use the same plugin pattern as providers (ProviderPlugin) and players (PlayerPlugin). This allows:
- **Community extensions**: Users can add custom metadata sources
- **Flexible data sources**: Images, reviews, ratings, cast info from any API
- **Graceful degradation**: If one source fails, try the next
- **Extensibility**: New data types (trailers, subtitles, etc.) without core changes

### Plugin Interface

```python
from abc import ABC, abstractmethod
from typing import Optional, Dict, List, Any
from dataclasses import dataclass

@dataclass
class MetadataResult:
    \"\"\"Standard metadata result structure\"\"\"
    # Basic info
    title: Optional[str] = None
    year: Optional[int] = None
    plot: Optional[str] = None
    tagline: Optional[str] = None
    
    # Media
    poster_url: Optional[str] = None
    backdrop_url: Optional[str] = None
    logo_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    
    # People
    cast: List[Dict[str, Any]] = None  # [{name, character, photo_url}]
    crew: List[Dict[str, Any]] = None  # [{name, job, department}]
    director: Optional[str] = None
    
    # Classification
    genres: List[str] = None
    content_rating: Optional[str] = None  # PG-13, TV-MA, etc.
    
    # Ratings
    rating: Optional[float] = None  # 0-10 scale
    rating_count: Optional[int] = None
    ratings: Dict[str, float] = None  # {\"imdb\": 8.5, \"tmdb\": 8.2, \"rt\": 85}
    
    # Technical
    runtime: Optional[int] = None  # minutes
    release_date: Optional[str] = None  # ISO date
    
    # Links
    trailer_url: Optional[str] = None
    imdb_id: Optional[str] = None
    tmdb_id: Optional[str] = None
    
    # Provider info
    provider_name: str = None  # Which plugin provided this data
    confidence: float = 1.0    # 0-1 confidence score
    

class MetadataProviderPlugin(ABC):
    \"\"\"Base class for metadata provider plugins\"\"\"
    
    @property
    @abstractmethod
    def name(self) -> str:
        \"\"\"Plugin name (e.g., 'tmdb', 'omdb', 'fanart_tv')\"\"\"
        pass
    
    @property
    @abstractmethod
    def display_name(self) -> str:
        \"\"\"Human-readable name for UI (e.g., 'The Movie Database')\"\"\"
        pass
    
    @property
    @abstractmethod
    def supported_media_types(self) -> List[str]:
        \"\"\"Media types this provider supports: ['movie', 'series', 'live']\"\"\"
        pass
    
    @property
    @abstractmethod
    def supported_fields(self) -> List[str]:
        \"\"\"Fields this provider can populate: ['poster', 'cast', 'plot', etc.]\"\"\"
        pass
    
    @abstractmethod
    async def search(self, title: str, year: Optional[int] = None, 
                    media_type: str = \"movie\") -> List[Dict[str, Any]]:
        \"\"\"Search for content by title and year\"\"\"
        pass
    
    @abstractmethod
    async def get_details(self, external_id: str, 
                         media_type: str = \"movie\") -> Optional[MetadataResult]:
        \"\"\"Get full metadata for content by external ID (tmdb_id, imdb_id, etc.)\"\"\"
        pass
    
    @abstractmethod
    async def test_connection(self) -> tuple[bool, Optional[str]]:
        \"\"\"Test if provider is accessible and configured correctly\"\"\"
        pass
    
    def get_rate_limit(self) -> tuple[int, int]:
        \"\"\"Return (requests, seconds) for rate limiting. Default: no limit\"\"\"
        return (0, 0)  # 0 = no limit
    
    def requires_api_key(self) -> bool:
        \"\"\"Whether this provider needs an API key\"\"\"
        return False
    
    def get_priority(self) -> int:
        \"\"\"Default priority (lower = higher priority). Can be overridden in config\"\"\"
        return 50  # Medium priority


# Example: TMDb Provider Implementation
class TMDbProvider(MetadataProviderPlugin):
    \"\"\"The Movie Database metadata provider\"\"\"
    
    def __init__(self, api_key: str, language: str = \"en-US\"):
        self.api_key = api_key
        self.language = language
        self.base_url = \"https://api.themoviedb.org/3\"
    
    @property
    def name(self) -> str:
        return \"tmdb\"
    
    @property
    def display_name(self) -> str:
        return \"The Movie Database (TMDb)\"
    
    @property
    def supported_media_types(self) -> List[str]:
        return [\"movie\", \"series\"]
    
    @property
    def supported_fields(self) -> List[str]:
        return [\"poster\", \"backdrop\", \"plot\", \"cast\", \"crew\", \"genres\", 
                \"rating\", \"trailer\", \"release_date\", \"runtime\"]
    
    def get_rate_limit(self) -> tuple[int, int]:
        return (40, 10)  # 40 requests per 10 seconds
    
    def requires_api_key(self) -> bool:
        return True
    
    def get_priority(self) -> int:
        return 10  # High priority (standard metadata source)
    
    async def search(self, title: str, year: Optional[int] = None,
                    media_type: str = \"movie\") -> List[Dict[str, Any]]:
        endpoint = \"search/movie\" if media_type == \"movie\" else \"search/tv\"
        params = {
            \"api_key\": self.api_key,
            \"language\": self.language,
            \"query\": title,
            \"year\": year
        }
        # ... make request, return results
    
    async def get_details(self, tmdb_id: str, 
                         media_type: str = \"movie\") -> Optional[MetadataResult]:
        endpoint = f\"{media_type}/{tmdb_id}\"
        # ... fetch data from TMDb API
        # ... also fetch credits endpoint for cast/crew
        # ... return MetadataResult populated with data
    
    async def test_connection(self) -> tuple[bool, Optional[str]]:
        try:
            # Try to fetch configuration (cheap endpoint)
            response = await self.request(\"configuration\")
            return (True, None)
        except Exception as e:
            return (False, str(e))


# Example: Provider-native metadata (from raw_data)
class ProviderMetadataProvider(MetadataProviderPlugin):
    \"\"\"Extract metadata from provider's raw_data field (Xtream API)\"\"\"
    
    @property
    def name(self) -> str:
        return \"provider\"
    
    @property
    def display_name(self) -> str:
        return \"Provider Metadata\"
    
    @property
    def supported_media_types(self) -> List[str]:
        return [\"movie\", \"series\", \"live\"]
    
    @property
    def supported_fields(self) -> List[str]:
        return [\"poster\", \"backdrop\", \"plot\", \"cast\", \"director\", \"genres\",
                \"rating\", \"release_date\", \"runtime\"]
    
    def get_priority(self) -> int:
        return 1  # Highest priority (already cached, no API call)
    
    async def get_details(self, channel_id: str, 
                         media_type: str = \"movie\") -> Optional[MetadataResult]:
        # Fetch from ChannelDB.raw_data
        channel = session.query(ChannelDB).get(channel_id)
        if not channel or not channel.raw_data:
            return None
        
        info = channel.raw_data.get('info', {})
        
        return MetadataResult(
            title=info.get('name'),
            plot=info.get('plot'),
            poster_url=info.get('cover'),
            backdrop_url=info.get('backdrop_path', [None])[0],
            director=info.get('director'),
            cast=self._parse_cast_string(info.get('cast', '')),
            genres=self._parse_genres(info.get('genre', '')),
            rating=float(info.get('rating', 0)),
            release_date=info.get('releaseDate'),
            runtime=self._parse_runtime(info.get('duration')),
            tmdb_id=str(info.get('tmdb_id', '')),
            provider_name=\"provider\",
            confidence=1.0
        )
    
    async def search(self, title: str, year: Optional[int] = None,
                    media_type: str = \"movie\") -> List[Dict[str, Any]]:
        # Search in ChannelDB by name
        # This provider doesn't really \"search\", it just provides cached data
        return []
    
    async def test_connection(self) -> tuple[bool, Optional[str]]:
        return (True, None)  # Always available (database)
```

### Plugin Registry and Manager

```python
class MetadataProviderRegistry:
    \"\"\"Registry for metadata provider plugins\"\"\"
    
    def __init__(self):
        self.providers: Dict[str, MetadataProviderPlugin] = {}
        self.priority_order: List[str] = []
    
    def register(self, provider: MetadataProviderPlugin):
        \"\"\"Register a metadata provider\"\"\"
        self.providers[provider.name] = provider
        self._update_priority_order()
    
    def get(self, name: str) -> Optional[MetadataProviderPlugin]:
        \"\"\"Get provider by name\"\"\"
        return self.providers.get(name)
    
    def get_all(self) -> List[MetadataProviderPlugin]:
        \"\"\"Get all registered providers in priority order\"\"\"
        return [self.providers[name] for name in self.priority_order 
                if name in self.providers]
    
    def _update_priority_order(self):
        \"\"\"Sort providers by priority\"\"\"
        items = list(self.providers.items())
        items.sort(key=lambda x: x[1].get_priority())
        self.priority_order = [name for name, _ in items]


class MetadataManager:
    \"\"\"Manages metadata fetching with plugin fallback chain\"\"\"
    
    def __init__(self, registry: MetadataProviderRegistry, db: Database):
        self.registry = registry
        self.db = db
        self.rate_limiters: Dict[str, RateLimiter] = {}
    
    async def get_metadata(self, channel: Channel, 
                          force_refresh: bool = False) -> MetadataResult:
        \"\"\"Get metadata using plugin fallback chain\"\"\"
        
        # Check cache first (unless force refresh)
        if not force_refresh and channel.metadata_id:
            cached = self._get_cached_metadata(channel.metadata_id)
            if cached and not self._is_stale(cached):
                return self._metadata_db_to_result(cached)
        
        # Try providers in priority order
        result = MetadataResult()
        
        for provider in self.registry.get_all():
            # Skip if not supported for this media type
            if channel.media_type not in provider.supported_media_types:
                continue
            
            # Rate limit check
            if not self._check_rate_limit(provider.name):
                continue
            
            try:
                # Fetch from provider
                partial = await provider.get_details(
                    channel.id, 
                    media_type=channel.media_type
                )
                
                if partial:
                    # Merge partial result (fill in missing fields only)
                    result = self._merge_metadata(result, partial)
                    
                    # If all fields populated, stop early
                    if self._is_complete(result):
                        break
            
            except Exception as e:
                logger.warning(f\"Metadata fetch failed from {provider.name}: {e}\")
                continue
        
        # Save to cache
        self._save_metadata_cache(channel, result)
        
        return result
    
    def _merge_metadata(self, base: MetadataResult, 
                       new: MetadataResult) -> MetadataResult:
        \"\"\"Merge metadata, preferring higher-confidence sources\"\"\"
        # Only fill in fields that are None or empty in base
        for field in new.__dataclass_fields__:
            base_value = getattr(base, field)
            new_value = getattr(new, field)
            
            if new_value and not base_value:
                setattr(base, field, new_value)
        
        return base
```

## Data Loading Strategy

### Three-Tier Loading System (IMPLEMENTED)

The details pane uses a progressive loading strategy that displays data as it becomes available.

#### Tier 1: Immediate (Database Cache)
**Source**: MetadataDB cached metadata  
**Latency**: <5ms  
**Display**: Immediately on selection  
**Status**: ✅ Implemented

When a channel is selected, the details pane first checks the metadata cache. If cached metadata exists and hasn't expired (TTL: 30 days), it's displayed immediately.

```python
# Instant display from cache
cached = metadata_manager.get_metadata(channel_id)
if cached and not expired:
    details_pane.show_metadata(cached)
```

**Available Data:**
- Title, year, plot
- Poster URL (with logo_url fallback)
- Cast, crew, director
- Genres, rating, content_rating
- Runtime, release_date
- Trailer URL, IMDb/TMDb IDs

#### Tier 2: Provider Metadata (Fast)
**Source**: ChannelDB.raw_data (Xtream API)  
**Latency**: ~0ms (already in database)  
**Display**: Show loading state, then populate  
**Status**: ✅ Implemented (ProviderMetadataProvider)

If cache is empty or expired, fetch metadata from the provider's raw_data field. This data is already cached in the database from the initial channel sync.

```python
# ProviderMetadataProvider extracts from raw_data
provider_meta = ProviderMetadataProvider().get_details(channel, session)
if provider_meta:
    details_pane.show_metadata(provider_meta)
```

**Available Data (Xtream API):**
- **Series**: cover, plot, cast (comma-separated), director, genres, rating, release_date, youtube_trailer, tmdb_id
- **Movies**: movie_image, plot, cast, director, genres, rating, release_date, duration
- **Live**: logo_url, description (minimal metadata)

**Poster Fallback Chain**: `cover → movie_image → logo_url`

**Limitations**:
- Cast is comma-separated string (no character names or photos)
- Image quality varies by provider
- No crew information (beyond director)
- VOD limitation: Only `get_vod_streams` currently used (basic info)
  - **Future**: Implement `get_vod_info()` for full movie metadata
  - **Future**: Implement `get_live_info()` for live stream details

#### Tier 3: Enriched Metadata (External APIs)
**Source**: TMDb, OMDb, FanartTV, TVDB (future)  
**Latency**: 200-500ms per API call  
**Display**: Show provider data, update with enriched data when ready  
**Status**: 🔄 Planned for Phase 2

External APIs provide high-quality metadata and images but require API keys and have rate limits.

**Planned Providers:**
- **TMDbProvider**: High-resolution images, full cast/crew with photos, ratings, trailers
- **OMDbProvider**: IMDb/Rotten Tomatoes ratings aggregation
- **FanartTvProvider**: High-quality artwork (logos, clearart, character art)
- **TVDBProvider**: Episode-level metadata and thumbnails

**Provider Chain Example**:
```python
# Priority order from config
providers = ["provider", "tmdb", "omdb"]

# Try providers until sufficient data found
for provider in providers:
    result = provider.get_details(channel)
    if result:
        merged = merged.merge(result)  # Merge with confidence scoring
```

### Progressive Loading Flow

```
User selects channel
        ↓
┌───────────────────────┐
│ Show loading state    │
│ (animated spinner)    │
└───────────────────────┘
        ↓
┌───────────────────────┐
│ Check metadata cache  │ ← Tier 1: <5ms
│ (MetadataDB)          │
└───────────────────────┘
        ↓
    Cached? ──YES→ Display cached metadata
        ↓ NO
┌───────────────────────┐
│ Fetch from providers  │ ← Tier 2: ~0ms (provider data)
│ (priority chain)      │   ← Tier 3: 200-500ms (external APIs, future)
└───────────────────────┘
        ↓
┌───────────────────────┐
│ Merge results         │
│ (confidence-based)    │
└───────────────────────┘
        ↓
┌───────────────────────┐
│ Update UI             │ ← Main thread via pyqtSignal
│ (show metadata)       │
└───────────────────────┘
        ↓
┌───────────────────────┐
│ Save to cache         │
│ (MetadataDB, 30d TTL) │
└───────────────────────┘
```

### Thread-Safe Implementation

All metadata fetching happens in background threads to keep the UI responsive:

```python
class MainWindow(QWidget):
    # Signal for cross-thread communication
    metadata_loaded = pyqtSignal(str, object)  # channel_id, MetadataResult
    
    def on_channel_selected(self, channel_id: str):
        """Main thread - show loading state"""
        self.details_pane.show_loading_state()
        
        # Spawn worker thread
        future = self.executor.submit(self._fetch_metadata, channel_id)
        future.add_done_callback(lambda f: self._on_done(f, channel_id))
    
    def _fetch_metadata(self, channel_id: str) -> MetadataResult:
        """Worker thread - blocking I/O"""
        return self.metadata_manager.get_metadata(channel_id)
    
    def _on_done(self, future, channel_id: str):
        """Worker thread - emit signal"""
        metadata = future.result()
        self.metadata_loaded.emit(channel_id, metadata)
    
    def _update_ui(self, channel_id: str, metadata: MetadataResult):
        """Main thread - safe to update UI"""
        self.details_pane.show_metadata(metadata)
```

See [docs/THREADING_PATTERNS.md](THREADING_PATTERNS.md) for comprehensive Qt threading documentation.

## Metadata Provider Plugin Architecture

The details pane uses a plugin-based metadata system for flexibility and extensibility. See [docs/METADATA_SYSTEM.md](METADATA_SYSTEM.md) for comprehensive documentation.

### Core Components

1. **MetadataProviderPlugin** - Base class for all metadata providers
2. **MetadataResult** - Dataclass with all metadata fields and merge() logic
3. **MetadataManager** - Orchestrates provider chain and caching
4. **MetadataProviderRegistry** - Manages provider priority and selection
5. **MetadataDB** - SQLAlchemy model for cached metadata (30-day TTL)

### Provider Chain

Providers are tried in priority order (configured in `config.yaml`):

```yaml
metadata_provider_priority:
  - "provider"    # ProviderMetadataProvider (fast, limited data)
  - "tmdb"        # TMDbProvider (slow, rich data) [Phase 2]
  - "omdb"        # OMDbProvider (slow, ratings) [Phase 2]
```

Each provider returns a `MetadataResult` with a confidence score (0.0-1.0). Results are merged, with higher-confidence data preferred.

### Current Providers

**ProviderMetadataProvider** (✅ Implemented):
- Extracts metadata from Xtream API `raw_data` field
- Zero latency (already cached in database)
- Supports: title, year, plot, poster, cast, rating, genres, runtime, release_date
- Poster fallback: cover → movie_image → logo_url
- Confidence: 0.6 (medium, provider data quality varies)

**Future Providers** (🔄 Phase 2):
- **TMDbProvider**: High-quality images, full cast/crew, trailers, ratings
- **OMDbProvider**: IMDb/Rotten Tomatoes ratings
- **FanartTvProvider**: High-quality artwork
- **TVDBProvider**: Episode-level metadata

See [docs/METADATA_SYSTEM.md](METADATA_SYSTEM.md) for creating custom providers.

## UI Layout (IMPLEMENTED)

### Three-Panel Layout with Collapsible Splitters

```
┌────────────────┬──────────────────────────────┬──────────────────┐
│                │                              │                  │
│  Left Sidebar  │      Center Content          │  Details Pane    │
│   (300px)      │       (flexible)             │    (400px)       │
│                │                              │                  │
│  ┌──────────┐  │  ┌─────────────────────┐    │  ┌────────────┐  │
│  │ Sources  │  │  │                     │    │  │   Poster   │  │
│  │          │  │  │   Channel Grid      │    │  │            │  │
│  ├──────────┤  │  │   or List View      │    │  ├────────────┤  │
│  │Favorites │  │  │                     │    │  │   Title    │  │
│  │          │  │  │                     │    │  │   Rating   │  │
│  ├──────────┤  │  │                     │    │  │   Genres   │  │
│  │ History  │  │  │                     │    │  ├────────────┤  │
│  │          │  │  │                     │    │  │ ▼ Overview │  │
│  └──────────┘  │  │                     │    │  ├────────────┤  │
│                │  │                     │    │  │ ▼ Cast     │  │
│                │  │                     │    │  ├────────────┤  │
│                │  └─────────────────────┘    │  │ ▼ Details  │  │
│                │                              │  └────────────┘  │
└────────────────┴──────────────────────────────┴──────────────────┘
```

**Collapsible Splitters**: Click the splitter handle to collapse/expand panels
- Left sidebar: Sources, Favorites, History
- Right details pane: Poster, metadata sections
- Smooth transitions with visual affordances
- State persisted to config (widths, collapsed sections)

### Details Pane Sections (Collapsible)

1. **Header** (always visible)
   - Poster image (with loading indicator)
   - Title, year
   - Rating (stars + numeric)
   - Genres (chips)
   - Play button, Favorite button

2. **Overview** (collapsible, default: expanded)
   - Plot/description
   - Tagline (if available)

3. **Cast & Crew** (collapsible, default: expanded)
   - Cast list with character names (if available)
   - Director, writers
   - Photo thumbnails (Phase 2)

4. **Technical Details** (collapsible, default: collapsed)
   - Runtime, release date
   - Content rating (PG-13, TV-MA, etc.)
   - Original language
   - Resolution, codec, bitrate (from provider)

5. **Links** (collapsible, default: collapsed)
   - Trailer (YouTube embed, Phase 2)
   - IMDb/TMDb links
   - Official website

6. **Similar Content** (Phase 2)
   - Recommendations based on genres/cast
   - Horizontal scrollable list

7. **Reviews** (Phase 2)
   - User reviews from TMDb/IMDb
   - Spoiler warnings

### Width discipline — every section must subordinate to the pane width (recurring trap)

**How the pane is structured** (and why that structure is a trap):

```
DetailsPaneWidget
└─ QScrollArea( setWidgetResizable(True), HorizontalScrollBar = AlwaysOff )
   └─ content QWidget
      └─ QVBoxLayout
         ├─ _PosterSection   (poster image / live logo + action rail)
         ├─ _MetadataSection (title, media/badge row, genre chips)
         ├─ _VersionSection  ("Also available as" chip rows)
         ├─ _PlotSection / _CastSection / _TechnicalSection / _TagsSection / …
         └─ EpgAgendaWidget
```

With `setWidgetResizable(True)` **and the horizontal scrollbar off**, the scroll area
sizes the inner `content` widget to:

> `content.width = max( viewport.width , max(child.minimumSizeHint().width) over all sections )`

So the column is only as narrow as its **widest-minimum child**. If *any one* section
reports a `minimumSizeHint().width()` larger than the viewport, the scroll area makes
the whole content widget that wide — and because there's no horizontal scrollbar, every
*other* section is silently laid out past the right edge and clips. The symptom always
looks like "the chips/text in section X don't wrap," but the culprit is usually a
*different* section forcing the width. **This is the trap: the visible victim is not the
cause.**

**The rule: no section may drive width.** Every section must be horizontally shrinkable
down to the 300px pane minimum. The three ways a section accidentally forces width, and
the canonical fixes (each learned the hard way):

| Forcer | Why it floors the width | Fix |
|---|---|---|
| A **pixmap `QLabel`** (poster, live logo) with `setScaledContents(False)` | A QLabel with a pixmap reports `minimumSizeHint().width() == pixmap.width()`; default `Preferred` policy won't shrink below it | Horizontal size policy → `QSizePolicy.Policy.Ignored`, **and** rescale the retained original pixmap to the granted width on resize (`_PosterSection._rescale_current_image`). Entry 122. |
| A **non-wrapping `QHBoxLayout`** of labels/badges (e.g. the media/IMDb/TMDb/rating row) | Its minimum width is the **sum** of all children | Use a wrapping `_FlowLayout` instead — its minimum width is the **widest single chip**. Entries 93/103. |
| A **word-wrapped `QLabel`** (plot, tagline, cast, tech, …) containing a **long unbreakable token** — a scene-release name (`A.Very.Long.Name.1998.1080p.x265-GROUP`) or a URL | Word-wrap only breaks at **spaces**, so a no-space token sets `minimumSizeHint().width()` to the *whole token*. `setWordWrap(True)` does **not** prevent this — that is why only the variants whose plot/tagline carried such a token clipped. | Horizontal policy → `Ignored` via the shared `_no_width_force(label)` helper; Qt then breaks the token at a character boundary instead of widening the pane. Apply it at **every** `setWordWrap(True)` in the pane. Entry 123. |

**Debugging recipe (do this instead of guessing — it's what finally cracked the
multi-attempt "Cowboy Bebop genres clip" bug):**
1. Reproduce the over-wide content offscreen: build the **full** section composition
   inside a real `QScrollArea(widgetResizable=True, HScroll=Off)` at a narrow width.
2. Print `minimumSizeHint().width()` for **each** section. The one exceeding the
   viewport is the forcer — it is frequently *not* the section whose contents visibly
   clip.
3. Fix the forcer with the matching pattern above; re-measure that
   `content.width() == viewport.width()`.
4. **Test at the full-composition level, never per-section in isolation.** Three earlier
   fixes (entries 92/93/103) and their tests all passed while the bug persisted because
   they only measured `_MetadataSection` alone — which was never the forcer. The poster
   was. See `tests/test_details_poster_width.py` for the composition-level regression
   that actually guards this.

### Loading States

**Poster Loading**:
- Initial: "Loading poster..." text
- Success: Display poster image
- Failure: "No poster available"
- URL failover: Try alternate domains if primary fails

**Metadata Sections**:
- Show section headers immediately
- Display loading spinner for empty sections
- Populate when data arrives
- Hide spinner when complete or no data

**Progressive Enhancement**:
```python
# Show basic info immediately
details_pane.show_channel(channel)

# Load metadata in background
metadata_manager.get_metadata_async(channel_id)

# Update UI when ready (via signal)
def on_metadata_loaded(metadata):
    details_pane.update_metadata(metadata)
```

## Image Caching (IMPLEMENTED)

Phase 1 MVP uses URL-based caching with MD5 hashing:

**Cache Directory**: `~/.cache/metatv/images/`
- MD5(url) as filename
- ~90% deduplication (same path, different domains)
- LRU cleanup at 500MB limit
- Image validation (magic bytes)

**Async Loading**:
```python
# Request image asynchronously
image_cache.get_image_async(url, provider_urls)

# Connect signals
image_cache.image_loaded.connect(on_image_loaded)
image_cache.image_failed.connect(on_image_failed)

# Update UI when ready (main thread)
def on_image_loaded(url, pixmap):
    poster_label.setPixmap(pixmap)
```

**URL Failover**:
If primary URL fails, reconstruct with alternate provider domains:
```python
# Try primary: http://provider1.com/images/poster.jpg
# Try alternate: http://provider2.com/images/poster.jpg
# Keep path, swap domain
```

See [DEVELOPMENT.md](../DEVELOPMENT.md#image-caching-system) for implementation details.

## Future Enhancements (Phase 2)

### External Metadata Providers

**TMDbProvider**:
- API key: https://www.themoviedb.org/settings/api
- Rate limit: 40 requests / 10 seconds
- Features: High-res images, full cast/crew, trailers, ratings
- Confidence: 0.9 (high-quality authoritative data)

**OMDbProvider**:
- API key: http://www.omdbapi.com/apikey.aspx
- Rate limit: 1,000 requests / day (free tier)
- Features: IMDb/Rotten Tomatoes ratings
- Confidence: 0.8 (ratings aggregation)

**Implementation**: See [docs/METADATA_SYSTEM.md](METADATA_SYSTEM.md#creating-a-metadata-provider)

### Xtream API Enhancements

**Current Limitation**: Only `get_vod_streams` used (basic info)

**Planned**:
- `get_vod_info(vod_id)` - Full movie metadata (plot, cast, director, etc.)
- `get_live_info(stream_id)` - Live stream details
- `get_series_info(series_id)` - Full series metadata (already partially used)

### Episode Listings

For series, show episode list with:
- Season/episode numbers
- Episode titles and descriptions
- Air dates
- Thumbnails (Phase 2)
- Watch progress indicators

### Similar Content

Recommend based on:
- Shared genres
- Same cast/director
- User preferences (watch history)
- Provider recommendations (if available)

### Reviews and Ratings

Aggregate from:
- TMDb user reviews
- IMDb ratings
- Rotten Tomatoes scores
- User comments (Phase 2)

### Trailer Playback

- Embed YouTube player in details pane
- Show trailer button when available
- Fallback to external browser if embed fails

## Configuration

All details pane settings are in `config.yaml`:

```yaml
# Details pane visibility and width (auto-managed)
details_pane_visible: false
details_pane_width: 400

# Collapsed sections (auto-managed)
details_pane_collapsed_sections:
  # - "technical_details"
  # - "links"

# Metadata settings
metadata_enabled: true
metadata_cache_ttl_days: 30
metadata_provider_priority: ["provider", "tmdb", "omdb"]
metadata_enabled_providers: ["provider"]

# Image cache settings
image_cache_enabled: true
image_cache_dir: "~/.cache/metatv/images"
image_cache_max_size_mb: 500
```

See [config.yaml.template](../config.yaml.template) for all available options.

## Testing Checklist

Phase 1 MVP testing:

- [x] Details pane shows/hides on click
- [x] Single-click selection from favorites/history
- [x] Metadata loads without blocking UI
- [x] Posters load with failover
- [x] Cast & crew section populates
- [x] Technical details section populates
- [x] Collapsible sections remember state
- [x] Play button works
- [x] Favorite button toggles
- [x] Loading indicators show during fetch
- [x] Error handling for missing metadata
- [x] Thread safety (no crashes from worker threads)
- [x] State persistence across restarts

Phase 2 testing (planned):

- [ ] TMDb provider fetches rich metadata
- [ ] OMDb provider fetches ratings
- [ ] Trailer playback works
- [ ] Episode listings show for series
- [ ] Similar content recommendations
- [ ] Reviews display correctly
- [ ] Background enrichment doesn't impact performance

## Related Documentation

- [docs/METADATA_SYSTEM.md](METADATA_SYSTEM.md) - Metadata plugin architecture and provider chain
- [docs/THREADING_PATTERNS.md](THREADING_PATTERNS.md) - Qt threading best practices
- [DEVELOPMENT.md](../DEVELOPMENT.md) - Image caching and async patterns
- [config.yaml.template](../config.yaml.template) - Configuration options
    ENRICHED = "enriched"     # TMDb/OMDb data loaded
    STALE = "stale"          # Cached but needs refresh

class DetailsPaneLoader:
    def load_details(self, channel):
        """Progressive loading with state tracking"""
        
        # Phase 1: Immediate (0ms)
        basic_info = self.load_basic_info(channel)  # From DB
        self.display_basic(basic_info)
        
        # Phase 2: Provider data (0-2s)
        if channel.raw_data and self.has_rich_metadata(channel.raw_data):
            provider_info = self.extract_provider_metadata(channel.raw_data)
            self.display_provider(provider_info)
        else:
            # Show spinner, fetch from API
            self.show_spinner("provider")
            self.fetch_provider_metadata_async(channel, callback=self.display_provider)
        
        # Phase 3: Enriched metadata (0-500ms)
        metadata = self.get_cached_metadata(channel.metadata_id)
        if metadata and not self.is_stale(metadata):
            # Use cache
            self.display_enriched(metadata)
        else:
            # Show spinners for specific sections
            self.show_spinner("poster")
            self.show_spinner("cast")
            self.show_spinner("similar")
            
            # Fetch in background
            self.fetch_enriched_metadata_async(
                channel, 
                callback=self.display_enriched
            )
```

## Caching Strategy

### MetadataDB Schema Enhancement

```python
class MetadataDB(Base):
    __tablename__ = "metadata"
    
    id = Column(String, primary_key=True)
    
    # Existing fields...
    title = Column(String, nullable=False, index=True)
    year = Column(Integer, index=True)
    genres = Column(JSON)
    plot = Column(Text)
    rating = Column(Float)
    poster_url = Column(Text)
    # ... etc
    
    # NEW: Cache management fields
    source = Column(String)                    # "tmdb", "omdb", "provider"
    fetched_at = Column(DateTime)             # When data was fetched
    refreshed_at = Column(DateTime)           # Last background refresh
    cache_ttl_days = Column(Integer, default=30)  # How long to cache
    fetch_error = Column(Text)                # Last error (if any)
    fetch_attempts = Column(Integer, default=0)   # Retry tracking
```

### Cache Freshness Rules

```python
def is_metadata_stale(metadata: MetadataDB) -> bool:
    """Determine if cached metadata needs refresh"""
    
    if not metadata.fetched_at:
        return True  # Never fetched
    
    age_days = (datetime.now() - metadata.fetched_at).days
    
    # Different TTLs for different scenarios
    if age_days > metadata.cache_ttl_days:
        return True  # Expired
    
    # Older content can be cached longer
    if metadata.year and metadata.year < 2020:
        return age_days > 90  # 3 months for older content
    
    # Recent content refreshes more often
    if metadata.year and metadata.year >= 2024:
        return age_days > 7   # 1 week for current content
    
    return age_days > 30  # Default 30 days

def should_background_refresh(metadata: MetadataDB) -> bool:
    """Check if metadata should be refreshed in background"""
    
    if not metadata.refreshed_at:
        return is_metadata_stale(metadata)
    
    # Refresh in background before TTL expires
    refresh_age = (datetime.now() - metadata.refreshed_at).days
    grace_period = metadata.cache_ttl_days * 0.8  # Refresh at 80% of TTL
    
    return refresh_age > grace_period
```

### Background Refresh Strategy

```python
class MetadataRefreshWorker:
    """Background worker to keep metadata fresh"""
    
    def __init__(self):
        self.queue = Queue()
        self.worker_thread = None
    
    def schedule_refresh(self, channel_id: str, priority: int = 5):
        """Queue metadata for background refresh"""
        self.queue.put((priority, channel_id))
    
    def run_worker(self):
        """Background thread that refreshes metadata"""
        while True:
            try:
                priority, channel_id = self.queue.get(timeout=60)
                
                # Fetch fresh metadata
                metadata = self.fetch_tmdb_data(channel_id)
                
                # Update cache
                self.update_metadata_cache(channel_id, metadata)
                
                # Rate limit: 40 requests per 10 seconds (TMDb limit)
                time.sleep(0.25)
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Metadata refresh failed: {e}")
    
    def prioritize_viewed_content(self):
        """Refresh metadata for recently viewed content"""
        session = get_session()
        
        # Get channels played in last 7 days
        recent = session.query(ChannelDB).filter(
            ChannelDB.last_played > datetime.now() - timedelta(days=7)
        ).order_by(ChannelDB.last_played.desc()).limit(100).all()
        
        for channel in recent:
            if channel.metadata_id:
                metadata = session.query(MetadataDB).get(channel.metadata_id)
                if should_background_refresh(metadata):
                    self.schedule_refresh(channel.id, priority=3)  # Higher priority
```

## UI Design

### Layout Structure

```
┌─────────────────────────────────────────────────────────────────┐
│  Main Window                                                    │
├──────────────┬──────────────────────────────────┬───────────────┤
│  Sidebar     │  Channel List                    │ Details Pane  │
│              │                                  │               │
│  [Sources]   │  Search: [____________]          │ ┌───────────┐ │
│  [Favorites] │                                  │ │  Poster   │ │
│  [History]   │  • Channel 1                     │ │  [Loading]│ │
│              │  • Channel 2 (selected)          │ └───────────┘ │
│              │  • Channel 3                     │               │
│              │  ...                             │ Title (Year)  │
│              │                                  │ ★★★★☆ 8.4/10 │
│              │                                  │               │
│              │                                  │ Genre Tags    │
│              │                                  │               │
│              │                                  │ Plot          │
│              │                                  │ [Loading...]  │
│              │                                  │               │
│              │                                  │ ▸ Cast        │
│              │                                  │   [Loading...]│
│              │                                  │               │
│              │                                  │ ▸ Technical   │
│              │                                  │   1080p AV1   │
│              │                                  │               │
│              │                                  │ [▶ Play]      │
│              │                                  │ [+ Favorite]  │
└──────────────┴──────────────────────────────────┴───────────────┘
```

### Loading Indicators

```python
class DetailsPaneWidget(QWidget):
    """Details pane with progressive loading"""
    
    def __init__(self):
        self.poster_label = QLabel()
        self.poster_spinner = QProgressIndicator()  # Spinning wheel
        
        self.plot_label = QLabel()
        self.plot_spinner = QProgressIndicator()
        
        self.cast_section = CollapsibleSection("Cast & Crew")
        self.cast_spinner = QProgressIndicator()
        
        self.similar_section = CollapsibleSection("Similar Content")
        self.similar_spinner = QProgressIndicator()
    
    def show_loading(self, section: str):
        """Show spinner for specific section"""
        spinners = {
            "poster": self.poster_spinner,
            "plot": self.plot_spinner,
            "cast": self.cast_spinner,
            "similar": self.similar_spinner
        }
        spinner = spinners.get(section)
        if spinner:
            spinner.start_animation()
            spinner.show()
    
    def hide_loading(self, section: str):
        """Hide spinner when data loads"""
        spinners = {
            "poster": self.poster_spinner,
            "plot": self.plot_spinner,
            "cast": self.cast_spinner,
            "similar": self.similar_spinner
        }
        spinner = spinners.get(section)
        if spinner:
            spinner.stop_animation()
            spinner.hide()
```

### Collapsible Sections

```python
class DetailSection(CollapsibleSection):
    """Expandable section with loading state"""
    
    def __init__(self, title: str, parent=None):
        super().__init__(title, parent)
        self.loading_indicator = QProgressIndicator()
        self.content_widget = QWidget()
        
        self.add_widget(self.loading_indicator)
        self.add_widget(self.content_widget)
        
        self.loading_indicator.hide()
    
    def set_loading(self, loading: bool):
        if loading:
            self.content_widget.hide()
            self.loading_indicator.show()
            self.loading_indicator.start_animation()
        else:
            self.loading_indicator.stop_animation()
            self.loading_indicator.hide()
            self.content_widget.show()
```

## Data Source Priority

### For Series/Movies

**Priority Order:**
1. **MetadataDB cache** (if fresh) → 0ms latency
2. **ChannelDB.raw_data** (provider metadata) → 0ms latency
3. **Provider API** (get_series_info) → 500ms-2s latency
4. **TMDb API** (enriched data) → 200-500ms latency

```python
def get_series_metadata(channel: Channel) -> Metadata:
    """Get metadata with fallback chain"""
    
    # Try cache first
    if channel.metadata_id:
        metadata = get_cached_metadata(channel.metadata_id)
        if metadata and not is_stale(metadata):
            return metadata
    
    # Extract from raw_data (Xtream series info)
    if channel.raw_data and 'info' in channel.raw_data:
        info = channel.raw_data['info']
        metadata = Metadata(
            title=info.get('name'),
            year=parse_year(info.get('releaseDate')),
            plot=info.get('plot'),
            genres=parse_genres(info.get('genre')),
            rating=float(info.get('rating', 0)),
            poster_url=info.get('cover'),
            backdrop_url=info.get('backdrop_path', [None])[0],
            director=info.get('director'),
            actors=parse_actors(info.get('cast')),
            tmdb_id=info.get('tmdb_id')
        )
        return metadata
    
    # Fallback: Fetch from provider API
    series_info = provider.get_series_info(channel.source_id)
    return parse_series_info(series_info)
```

### For Live TV

**Priority Order:**
1. **MetadataDB cache** (if exists) → 0ms
2. **ChannelDB fields** (name, logo, category) → 0ms
3. **EPG data** (if available) → Future feature

Live TV typically has less metadata, so the details pane would show:
- Channel logo (large)
- Current program (from EPG - future)
- Schedule (from EPG - future)
- Category/genre
- Technical details (quality, codec)

## Performance Considerations

### Request Batching

```python
class TMDbBatchFetcher:
    """Batch metadata requests to reduce API calls"""
    
    def __init__(self):
        self.queue = []
        self.timer = QTimer()
        self.timer.timeout.connect(self.flush_queue)
        self.timer.start(500)  # Batch every 500ms
    
    def request_metadata(self, tmdb_id: str, callback):
        """Queue a metadata request"""
        self.queue.append((tmdb_id, callback))
    
    def flush_queue(self):
        """Process queued requests in batch"""
        if not self.queue:
            return
        
        # TMDb doesn't have batch endpoint, but we can
        # prioritize and rate-limit efficiently
        batch, self.queue = self.queue[:5], self.queue[5:]
        
        for tmdb_id, callback in batch:
            metadata = self.fetch_tmdb(tmdb_id)
            callback(metadata)
            time.sleep(0.25)  # Rate limit
```

### Image Caching

#### Phase 1: URL-Based Caching (MVP) ✅

**Status**: Implement first

**Strategy**: Hash the URL to create cache key. Same URL = same cached file.

```python
class ImageCache:
    """Cache poster/backdrop images locally - Phase 1"""
    
    def __init__(self, cache_dir="~/.cache/metatv/images"):
        self.cache_dir = Path(cache_dir).expanduser()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_index = {}  # url -> cache_path mapping (in-memory)
    
    async def get_image(self, url: str) -> QPixmap:
        """Get image from cache or download"""
        
        # Check in-memory index first
        if url in self.cache_index:
            cache_path = self.cache_index[url]
            if cache_path.exists():
                return QPixmap(str(cache_path))
        
        # Generate cache key from URL
        cache_key = hashlib.md5(url.encode()).hexdigest()
        cache_path = self.cache_dir / f"{cache_key}.jpg"
        
        # Check disk cache
        if cache_path.exists():
            # Verify image is valid
            if self._verify_image(cache_path):
                self.cache_index[url] = cache_path
                return QPixmap(str(cache_path))
            else:
                # Corrupted - remove and re-download
                cache_path.unlink()
        
        # Download and cache
        try:
            response = await self._download_async(url, timeout=5)
            if response.status_code == 200:
                cache_path.write_bytes(response.content)
                self.cache_index[url] = cache_path
                logger.debug(f"Cached image: {url} -> {cache_key}")
                return QPixmap(str(cache_path))
        except Exception as e:
            logger.warning(f"Failed to download image {url}: {e}")
        
        return None  # Return placeholder
    
    def _verify_image(self, path: Path) -> bool:
        """Quick validation - check file size and magic bytes"""
        try:
            if path.stat().st_size < 100:  # Too small
                return False
            
            # Check JPEG/PNG magic bytes
            magic = path.read_bytes()[:4]
            return magic[:2] == b'\xff\xd8' or magic == b'\x89PNG'
        except:
            return False
    
    def get_cache_stats(self) -> dict:
        """Get cache statistics"""
        if not self.cache_dir.exists():
            return {"total_files": 0, "total_size": 0}
        
        files = list(self.cache_dir.glob("*"))
        total_size = sum(f.stat().st_size for f in files if f.is_file())
        
        return {
            "total_files": len(files),
            "total_size": total_size,
            "total_size_mb": round(total_size / 1024 / 1024, 2)
        }
```

**Benefits**:
- ✅ Simple implementation (~50 lines)
- ✅ Handles same URL from multiple sources (TMDb poster used by multiple language variants)
- ✅ ~90% reduction (283k channels → ~30k unique TMDb posters)
- ✅ Expected cache size: ~3GB

**Limitations**:
- ❌ Different URLs with same content download separately (e.g., same logo from different CDNs)
- ❌ Doesn't catch resized/re-encoded versions

#### Phase 2: Content-Based Deduplication (Optimization) 🎯

**Status**: Add after Phase 1 is stable

**Strategy**: Hash the image content (bytes) to detect duplicates from different URLs.

```python
class ImageCacheDB(Base):
    """Track image cache and deduplication - Phase 2"""
    __tablename__ = "image_cache"
    
    # Primary key is content hash
    content_hash = Column(String, primary_key=True)  # SHA256 of image bytes
    
    # Multiple URLs can point to same image
    source_urls = Column(JSON)  # ["http://url1.com/img.jpg", "http://url2.com/img.jpg"]
    
    file_path = Column(String)  # Local cache path
    file_size = Column(Integer)  # Bytes
    
    # Deduplication stats
    duplicate_count = Column(Integer, default=0)  # How many duplicates detected
    first_seen = Column(DateTime, default=datetime.now)
    last_seen = Column(DateTime, default=datetime.now)
    
    # Image metadata
    width = Column(Integer)
    height = Column(Integer)
    format = Column(String)  # JPEG, PNG, etc.
    
    # Usage tracking
    reference_count = Column(Integer, default=0)  # How many channels use this
    last_accessed = Column(DateTime)


class ImageCachePhase2(ImageCache):
    """Enhanced image cache with content deduplication"""
    
    def __init__(self, cache_dir="~/.cache/metatv/images", db_session=None):
        super().__init__(cache_dir)
        self.db = db_session
    
    async def get_image_deduplicated(self, url: str) -> QPixmap:
        """Get image with content-based deduplication"""
        
        # Check if we've already processed this URL
        cached = self.db.query(ImageCacheDB).filter(
            ImageCacheDB.source_urls.contains(url)
        ).first()
        
        if cached:
            logger.debug(f"URL cache hit: {url}")
            cached.last_accessed = datetime.now()
            cached.reference_count += 1
            self.db.commit()
            return QPixmap(cached.file_path)
        
        # Download image
        try:
            response = await self._download_async(url, timeout=5)
            if response.status_code != 200:
                return None
            
            image_data = response.content
            
            # Calculate content hash
            content_hash = hashlib.sha256(image_data).hexdigest()
            
            # Check if we already have this exact content
            existing = self.db.query(ImageCacheDB).filter_by(
                content_hash=content_hash
            ).first()
            
            if existing:
                # Duplicate detected!
                logger.info(f"Duplicate image detected: {url}")
                logger.info(f"  Matches existing: {existing.source_urls[0]}")
                
                # Add this URL to the list of sources
                if url not in existing.source_urls:
                    existing.source_urls.append(url)
                existing.duplicate_count += 1
                existing.last_seen = datetime.now()
                existing.reference_count += 1
                self.db.commit()
                
                return QPixmap(existing.file_path)
            
            # New unique image - save it
            cache_path = self.cache_dir / f"{content_hash}.jpg"
            cache_path.write_bytes(image_data)
            
            # Extract image metadata
            from PIL import Image
            img = Image.open(BytesIO(image_data))
            
            # Create cache entry
            cache_entry = ImageCacheDB(
                content_hash=content_hash,
                source_urls=[url],
                file_path=str(cache_path),
                file_size=len(image_data),
                width=img.width,
                height=img.height,
                format=img.format,
                reference_count=1
            )
            self.db.add(cache_entry)
            self.db.commit()
            
            logger.debug(f"New unique image cached: {content_hash}")
            return QPixmap(str(cache_path))
            
        except Exception as e:
            logger.warning(f"Failed to process image {url}: {e}")
            return None
    
    def get_deduplication_stats(self) -> dict:
        """Get deduplication statistics"""
        total_entries = self.db.query(ImageCacheDB).count()
        total_urls = self.db.query(
            func.json_array_length(ImageCacheDB.source_urls)
        ).scalar() or 0
        
        duplicates_detected = self.db.query(
            func.sum(ImageCacheDB.duplicate_count)
        ).scalar() or 0
        
        total_size = self.db.query(
            func.sum(ImageCacheDB.file_size)
        ).scalar() or 0
        
        # Estimate saved storage (duplicates × avg file size)
        avg_file_size = total_size / total_entries if total_entries > 0 else 100000
        estimated_saved = duplicates_detected * avg_file_size
        
        return {
            "unique_images": total_entries,
            "total_urls": total_urls,
            "duplicates_detected": duplicates_detected,
            "deduplication_rate": round(duplicates_detected / total_urls * 100, 1) if total_urls > 0 else 0,
            "storage_used_mb": round(total_size / 1024 / 1024, 2),
            "storage_saved_mb": round(estimated_saved / 1024 / 1024, 2)
        }
```

**Benefits**:
- ✅ Catches identical images from different URLs (different CDNs, providers)
- ✅ ~95% reduction (detects network logos used across many channels)
- ✅ Expected cache size: ~1-1.5GB
- ✅ Deduplication statistics and reporting

**Complexity**: Medium (requires database tracking)

**When to implement**: After Phase 1 is working, if storage or bandwidth is a concern

#### Phase 3: Perceptual Hash Deduplication (Advanced) 🚀

**Status**: Optional optimization for maximum efficiency

**Strategy**: Use perceptual hashing to detect similar images (resized, re-encoded, slightly modified).

```python
from PIL import Image
import imagehash  # pip install imagehash

class ImageCachePhase3(ImageCachePhase2):
    """Enhanced with perceptual hashing for similar image detection"""
    
    async def get_image_perceptual(self, url: str) -> QPixmap:
        """Get image with perceptual hash deduplication"""
        
        # Check URL cache first (Phase 1)
        cached = self.db.query(ImageCacheDB).filter(
            ImageCacheDB.source_urls.contains(url)
        ).first()
        
        if cached:
            return QPixmap(cached.file_path)
        
        # Download image
        try:
            response = await self._download_async(url, timeout=5)
            if response.status_code != 200:
                return None
            
            image_data = response.content
            
            # Calculate both content hash and perceptual hash
            content_hash = hashlib.sha256(image_data).hexdigest()
            
            img = Image.open(BytesIO(image_data))
            phash = str(imagehash.average_hash(img))  # 8-byte perceptual hash
            
            # Check for exact content match (Phase 2)
            existing = self.db.query(ImageCacheDB).filter_by(
                content_hash=content_hash
            ).first()
            
            if existing:
                # Exact duplicate
                existing.source_urls.append(url)
                existing.duplicate_count += 1
                self.db.commit()
                return QPixmap(existing.file_path)
            
            # Check for perceptual match (similar images)
            # Find images with similar perceptual hash (Hamming distance <= 5)
            similar = self.db.query(ImageCacheDB).filter(
                ImageCacheDB.perceptual_hash.isnot(None)
            ).all()
            
            for candidate in similar:
                candidate_hash = imagehash.hex_to_hash(candidate.perceptual_hash)
                current_hash = imagehash.hex_to_hash(phash)
                hamming_distance = candidate_hash - current_hash
                
                if hamming_distance <= 5:  # Similar enough
                    logger.info(f"Similar image detected: {url}")
                    logger.info(f"  Matches: {candidate.source_urls[0]}")
                    logger.info(f"  Hamming distance: {hamming_distance}")
                    
                    # Use existing image
                    candidate.source_urls.append(url)
                    candidate.duplicate_count += 1
                    candidate.similar_matches = candidate.similar_matches or []
                    candidate.similar_matches.append({
                        "url": url,
                        "distance": hamming_distance
                    })
                    self.db.commit()
                    
                    return QPixmap(candidate.file_path)
            
            # New unique image
            cache_path = self.cache_dir / f"{content_hash}.jpg"
            cache_path.write_bytes(image_data)
            
            cache_entry = ImageCacheDB(
                content_hash=content_hash,
                perceptual_hash=phash,
                source_urls=[url],
                file_path=str(cache_path),
                file_size=len(image_data),
                width=img.width,
                height=img.height,
                format=img.format,
                reference_count=1
            )
            self.db.add(cache_entry)
            self.db.commit()
            
            return QPixmap(str(cache_path))
            
        except Exception as e:
            logger.warning(f"Failed to process image {url}: {e}")
            return None
```

**Benefits**:
- ✅ Catches resized versions (1080p vs 720p posters)
- ✅ Catches re-encoded versions (different JPEG quality)
- ✅ Catches slightly modified images (cropped, watermarked)
- ✅ Maximum deduplication: ~96-97% reduction
- ✅ Expected cache size: ~500MB-1GB

**Complexity**: High (requires PIL, imagehash library, slower processing)

**When to implement**: Only if Phase 2 isn't sufficient, or for maximum storage efficiency

**Trade-offs**:
- Slower (needs to decode image for perceptual hash)
- False positives possible (different images with similar hash)
- Requires careful tuning of Hamming distance threshold

#### Implementation Timeline

**Immediate (Phase 1)**:
- URL-based caching
- Basic cache statistics
- Cache size limits
- Automatic cleanup (LRU)

**Next iteration (Phase 2)**:
- ImageCacheDB table
- Content hash tracking
- Deduplication statistics
- Migration from Phase 1

**Future (Phase 3)**:
- Perceptual hashing
- Similar image detection
- Advanced analytics
- User controls for similarity threshold

## Config Settings

```python
# In Config class
class Config:
    # Details pane settings
    details_pane_enabled: bool = True
    details_pane_width: int = 350
    details_pane_position: str = "right"  # "right", "bottom", "modal"
    
    # Metadata provider configuration
    metadata_providers_enabled: List[str] = ["provider", "tmdb", "omdb"]  # Priority order
    metadata_provider_config: Dict[str, Dict] = {
        "tmdb": {
            "api_key": "",
            "language": "en-US",
            "include_adult": False
        },
        "omdb": {
            "api_key": ""
        }
    }
    
    # Metadata caching
    metadata_cache_ttl_days: int = 30
    metadata_background_refresh: bool = True
    metadata_refresh_viewed_only: bool = True  # Only refresh viewed content
    
    # Performance
    image_cache_enabled: bool = True
    image_cache_size_mb: int = 500
    metadata_preload_favorites: bool = True  # Preload metadata for favorites
```

## Implementation Phases

### Phase 1: Plugin Architecture Foundation
- [ ] Create `MetadataProviderPlugin` base class
- [ ] Create `MetadataProviderRegistry` for plugin management
- [ ] Create `MetadataManager` for coordinated fetching with fallback
- [ ] Implement `ProviderMetadataProvider` (extracts from raw_data)
- [ ] Add plugin discovery system (scan metatv/metadata_providers/)
- [ ] Rate limiting per provider
- [ ] Plugin configuration in Config class

### Phase 2: Basic Details Pane UI
- [ ] Create DetailsPaneWidget with collapsible sections
- [ ] Show basic info from ChannelDB immediately (Tier 1)
- [ ] Show provider metadata from raw_data (Tier 2)
- [ ] Add section-specific loading spinners
- [ ] Implement progressive loading (show data as it arrives)
- [ ] State persistence (width, visibility, collapsed sections)

### Phase 3: Built-in Metadata Providers
- [ ] Implement `TMDbProvider` plugin
  - API client with rate limiting (40 req/10s)
  - Search by title/year
  - Get full details (cast, crew, posters)
  - Configuration UI for API key
- [ ] Implement `OMDbProvider` plugin
  - Alternative ratings source
  - API key configuration
- [ ] Image caching system for posters/backdrops
- [ ] Background refresh worker

### Phase 4: Advanced Features
- [ ] Similar content recommendations
- [ ] Full cast/crew with photos
- [ ] Reviews and ratings aggregation
- [ ] Trailer integration (YouTube player)
- [ ] EPG data for live TV (via EPG plugins)
- [ ] Community metadata providers:
  - FanartTvProvider (high-quality artwork)
  - TVDBProvider (TV episode data)
  - Custom user plugins

### Phase 5: Developer Experience
- [ ] Plugin development guide
- [ ] Example plugin template
- [ ] Plugin testing framework
- [ ] Plugin packaging/distribution guide
- [ ] Plugin marketplace/registry (future)

## Summary

**Answer to your questions:**

1. **Is on-click most efficient?** → Yes, with progressive loading (show cached immediately, fetch enriched in background)

2. **Loading indicators?** → Yes, section-specific spinners for data being fetched from APIs

3. **Caching strategy?** → Three-tier: Database cache (instant) → Provider data (fast) → Plugin APIs (background with cache)

4. **Data from provider?** → Yes! Xtream API already provides rich metadata (cover, plot, cast, rating) - we extract from raw_data field via ProviderMetadataProvider plugin

5. **Plugin architecture?** → Yes! MetadataProviderPlugin base class allows community extensions for images, reviews, ratings, descriptions, cast, etc. Similar to ProviderPlugin and PlayerPlugin patterns.

**Key Benefits:**
- ⚡ Instant display of cached data (no perceived latency)
- 🔄 Progressive loading keeps UI responsive  
- 💾 Smart caching reduces API calls by 90%+
- 🔍 Background refresh ensures data freshness
- 📊 Prioritizes viewed content for refresh
- 🔌 **Plugin system allows community extensions**
- 🎯 **Graceful degradation if providers fail**
- 🛠️ **Easy to add new data sources without core changes**

## Poster sizing — the recurring trap, and the "couldn't see the render" lesson

**The problem.** A VOD poster is fit inside a fixed-height box (`_POSTER_MIN_H`..`_POSTER_MAX_H`
= 400..600). A portrait 2:3 poster only fills the card while the card width is ≤
`_POSTER_MAX_H × aspect` ≈ 600 × 0.67 ≈ **402px**. Once the card is wider than that, the 600px
height cap limits the poster's height and leaves it narrower than the card → **pillarbox side
padding that grows with pane width**. A separate **rapid-navigation race** could also leave the
poster scaled to a stale (pre-layout) size when paging quickly through a title's variants. The
poster *image* was never the cause — Cowboy Bebop measured 1004×1498 = a clean 2:3.

**How we got here (the expensive part).** This burned a long, costly debugging session because
the work was driven by code + **offscreen** geometry measurements with **no view of the actual
rendered output**. Offscreen probes "proved" the layout was fine (correct min widths) while the
user was looking at a visibly-wrong poster, so the real symptom (pillarbox at wide widths; "too
big" when filled) was repeatedly missed. The user's direct observations — "it's the poster",
"a 2:3 poster can't pad", "it's too big" — were the accurate signal throughout.

**Resolution.** Rather than keep re-engineering the scaler, the **default `details_pane_width`
is set to 452** — the width the user dialed in, where a 2:3 poster fills the card cleanly
(card column ≤ ~402). A proper width-independent fix (size the card to the poster, or fill-width
with a sane height cap) is parked; see PRs #282 / #283 / #286 for the attempts and the
measure-don't-guess method.

**Lessons.** (1) When a visual bug is **width-dependent**, check the *default pane width* before
re-engineering the renderer. (2) Offscreen measurement validates **geometry, not appearance** —
trust the user's eyes over indirect metrics, and ask for a screenshot early instead of
theorizing. (3) A cheap config lever can beat a "correct" but expensive code change.
