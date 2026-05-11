# Xtream Codes API Data Schema

This document describes the data structures returned by the Xtream Codes API, based on actual responses from the TREX provider.

## Table of Contents
- [Overview](#overview)
- [Series Info Response](#series-info-response)
- [Season Structure](#season-structure)
- [Episode Structure](#episode-structure)
- [Metadata Extraction Strategy](#metadata-extraction-strategy)
- [Search & Discovery Use Cases](#search--discovery-use-cases)
- [Video/Audio Technical Data](#videoaudio-technical-data)

---

## Overview

**Purpose**: This schema documents the rich metadata available from Xtream Codes API to enable advanced content discovery features:
- Search by actor, director, crew
- Filter by year, decade, genre
- Find similar/related content
- Quality-based organization (4K, HDR, etc.)
- Rating-based recommendations

**Key Insight**: Xtream API provides TMDb IDs and basic metadata, but we'll need to:
1. Extract structured data from raw fields (crew parsing, title parsing)
2. Enrich with additional TMDb API calls for full cast/crew objects
3. Build searchable indexes for actors, years, genres, quality

**Primary Metadata Sources**:
- **Xtream API**: Technical data, TMDb IDs, basic info (current)
- **TMDb API**: Full cast/crew, genres, plot, ratings (future integration)
- **OMDb API**: Alternative metadata source (optional)

---

## Series Info Response

The `get_series_info(series_id)` endpoint returns a dict with three keys:

```python
{
    "seasons": List[SeasonDict],     # List of season metadata
    "info": SeriesInfoDict,           # Series-level metadata
    "episodes": List[List[EpisodeDict]]  # Nested lists: [[season1_eps], [season2_eps], ...]
}
```

### Structure Notes
- **episodes** is a list of lists, where each inner list contains all episodes for one season
- Episodes must be flattened and grouped by their `season` field
- Season numbering: 0 = Specials, 1+ = regular seasons

---

## Season Structure

```python
{
    "name": str,                    # e.g. "Season 1", "Specials"
    "episode_count": str,           # Total episodes (as string)
    "overview": str | None,         # Season description
    "air_date": str,                # ISO date "1966-09-08"
    "cover": str,                   # TMDb thumbnail URL (w154)
    "cover_tmdb": str,              # TMDb path "/path.jpg"
    "season_number": int,           # 0 for specials, 1+ for seasons
    "cover_big": str,               # TMDb larger cover (w500) - may have concatenation issue
    "releaseDate": str,             # Duplicate of air_date
    "duration": str                 # Episode runtime in minutes "50"
}
```

### Available Metadata
- ✅ Season title and number
- ✅ Episode count
- ✅ Cover art (multiple sizes)
- ✅ Air date
- ⚠️ Overview often null
- ⚠️ cover_big has URL concatenation bug

---

## Episode Structure

```python
{
    # Identifiers
    "id": str,                      # Provider-specific episode ID "1004425"
    "episode_num": int,             # Episode number within season
    "season": int,                  # Season number (0 for specials)
    
    # Basic Info
    "title": str,                   # Full title "EN - Star Trek (1966) - S03E01"
    "container_extension": str,     # File format "mkv", "mp4"
    "custom_sid": str | None,       # Custom stream ID (usually null)
    "added": str,                   # Unix timestamp string "1662142840"
    "direct_source": str,           # Direct URL (usually empty)
    
    # Rich Metadata
    "info": {
        # Core Metadata
        "air_date": str,            # ISO date "1968-09-20"
        "crew": str,                # Comma-separated crew list
        "rating": float,            # User rating 5.8
        "id": int,                  # TMDb series ID 253
        "movie_image": str,         # Episode thumbnail URL (TMDb w185)
        "duration_secs": int,       # Runtime in seconds 3368
        "duration": str,            # Runtime formatted "00:56:08"
        
        # Technical Video Data
        "video": {
            "index": int,           # Stream index 0
            "codec_name": str,      # "av1", "h264", "hevc"
            "codec_long_name": str, # Full codec name
            "profile": str,         # "Main", "High"
            "codec_type": str,      # "video"
            "width": int,           # 1440
            "height": int,          # 1080
            "has_b_frames": int,    # B-frame count
            "level": int,           # Codec level
            "color_range": str,     # "tv", "pc"
            "r_frame_rate": str,    # "24000/1001"
            "avg_frame_rate": str,  # "24000/1001"
            "time_base": str,       # "1/1000"
            "start_pts": int,
            "start_time": str,
            "disposition": Dict,     # Stream flags
            "tags": Dict            # Container metadata
        },
        
        # Technical Audio Data
        "audio": {
            "index": int,
            "codec_name": str,      # "opus", "aac", "ac3"
            "codec_long_name": str,
            "codec_type": str,      # "audio"
            "sample_fmt": str,      # "fltp"
            "sample_rate": str,     # "48000"
            "channels": int,        # 2
            "channel_layout": str,  # "stereo"
            "bits_per_sample": int,
            "r_frame_rate": str,    # "0/0"
            "avg_frame_rate": str,
            "time_base": str,
            "start_pts": int,
            "start_time": str,
            "disposition": Dict,
            "tags": Dict            # Language, bitrate, etc.
        },
        
        "bitrate": int              # Total bitrate in kbps 1181
    }
}
```

### Stream URL Pattern
```
{base_url}/series/{username}/{password}/{episode_id}.{container_extension}
```

Example:
```
http://provider.com/series/user123/pass456/1004425.mkv
```

---

## Metadata Extraction Strategy

### Phase 1: Extract from Xtream API (Current Provider)

#### Available Now
| Data Type | Field | Extraction Method | Search Use Case |
|-----------|-------|-------------------|-----------------|
| **Year** | `episode.title` | Regex: `\((\d{4})\)` | "Find all 1990s content" |
| **Series Name** | `episode.title` | Regex: Parse before year | "Show me Star Trek episodes" |
| **Language** | `episode.title` | Prefix: `EN`, `FR`, etc. | "Filter by English content" |
| **Episode Code** | `episode.title` | Parse: `S03E01` | Episode identification |
| **Crew** | `episode.info.crew` | Split by comma | "Find all Gene Roddenberry shows" |
| **Air Date** | `episode.info.air_date` | Direct use | "Sort by release date" |
| **Rating** | `episode.info.rating` | Direct use | "Show highly-rated episodes" |
| **Quality** | `video.width/height` | Compute badge | "Filter to 4K only" |
| **Codec** | `video.codec_name` | Direct use | "Show AV1 content" |
| **TMDb ID** | `episode.info.id` | Direct use | Link to TMDb for enrichment |

#### Title Parsing Example
```python
# Input: "EN - Star Trek (1966) - S03E01"
title_pattern = r'^([A-Z]{2})\s*-\s*(.+?)\s*\((\d{4})\)\s*-\s*(S\d+E\d+)$'
match = re.match(title_pattern, title)

# Extracted:
language = "EN"
series = "Star Trek"
year = 1966
episode_code = "S03E01"
season = 3
episode = 1
```

#### Crew Parsing Example
```python
# Input: "Gene L. Coon, Marc Daniels, Walter M. Jefferies, ..."
crew = episode.info.crew.split(', ')

# Result:
["Gene L. Coon", "Marc Daniels", "Walter M. Jefferies", ...]

# Use cases:
# - Index each name for search
# - First 1-2 names often director/writer
# - Build "More by this director" features
```

### Phase 2: TMDb API Enrichment (Planned)

Use `episode.info.id` (TMDb series ID) to fetch:

```python
# TMDb API call example
tmdb_data = tmdb.get_tv_series(series_id=253)  # Star Trek TOS

# Additional metadata:
{
    "genres": ["Sci-Fi & Fantasy", "Drama"],
    "cast": [
        {"name": "William Shatner", "character": "James T. Kirk", "order": 0},
        {"name": "Leonard Nimoy", "character": "Spock", "order": 1},
        ...
    ],
    "created_by": ["Gene Roddenberry"],
    "production_companies": ["Norway Productions", "Paramount Television"],
    "overview": "Full plot summary...",
    "keywords": ["space", "future", "exploration"],
    "similar_series": [253, 1851, ...],  # Similar TMDb IDs
    "recommendations": [...]
}
```

### Phase 3: Searchable Index Structure (Future)

```python
# Proposed MetadataDB enhancements

class ActorDB(Base):
    id: str                  # Actor name normalized
    name: str                # Display name
    character: str           # Character played (if available)
    appearances: int         # Count of episodes/movies
    
class GenreDB(Base):
    id: str
    name: str                # "Sci-Fi", "Action", etc.
    
class KeywordDB(Base):
    id: str
    keyword: str             # "space", "time travel", etc.

# Many-to-many relationships
channel_actors = Table('channel_actors', ...)
channel_genres = Table('channel_genres', ...)
channel_keywords = Table('channel_keywords', ...)
```

---

## Search & Discovery Use Cases

### 1. Actor-Based Search
**User Query**: "Show me all content with William Shatner"

**Implementation**:
```python
# Phase 1: Search crew field
results = session.query(EpisodeDB).filter(
    EpisodeDB.raw_data['info']['crew'].astext.contains('William Shatner')
).all()

# Phase 2: Join with ActorDB
results = session.query(ChannelDB).join(
    channel_actors
).filter(
    ActorDB.name == 'William Shatner'
).all()
```

### 2. Year/Decade Filtering
**User Query**: "Show me all 90s action movies"

**Implementation**:
```python
# Extract year from parsed title
results = session.query(ChannelDB).filter(
    ChannelDB.year.between(1990, 1999),
    ChannelDB.genres.contains('Action')
).all()
```

### 3. Quality-Based Organization
**User Query**: "Show me all 4K content"

**Implementation**:
```python
# Query raw_data for video dimensions
results = session.query(EpisodeDB).filter(
    EpisodeDB.raw_data['info']['video']['height'].astext.cast(Integer) >= 2160
).all()
```

### 4. Similar Content Discovery
**User Query**: "More like Star Trek"

**Implementation**:
```python
# Phase 1: Same crew members
same_crew = find_by_common_crew(series="Star Trek")

# Phase 2: TMDb similar/recommendations
tmdb_similar = tmdb.get_similar_series(series_id=253)
results = session.query(ChannelDB).filter(
    ChannelDB.tmdb_id.in_(tmdb_similar)
).all()

# Phase 3: Same genres + keywords
same_genre = session.query(ChannelDB).filter(
    ChannelDB.genres.contains('Sci-Fi')
).all()
```

### 5. Watch Alerts by Metadata
**User Query**: "Notify me when new Christopher Nolan movies are added"

**Implementation**:
```python
alert = AlertPatternDB(
    name="Christopher Nolan Films",
    pattern_type="director",
    pattern_value="Christopher Nolan",
    metadata_field="crew"
)

# On provider refresh:
new_channels = get_new_channels_since_last_refresh()
matches = [
    ch for ch in new_channels
    if "Christopher Nolan" in ch.crew
]
```

---

## Metadata Fields

### Immediately Usable Metadata

| Field | Location | Type | Quality | Notes |
|-------|----------|------|---------|-------|
| Episode Title | `episode.title` | string | ⚠️ | Contains full formatted name, needs parsing |
| Episode Number | `episode.episode_num` | int | ✅ | Clean |
| Season Number | `episode.season` | int | ✅ | Clean |
| Air Date | `episode.info.air_date` | string | ✅ | ISO format |
| Duration | `episode.info.duration_secs` | int | ✅ | Seconds |
| Rating | `episode.info.rating` | float | ✅ | User rating |
| Thumbnail | `episode.info.movie_image` | string | ✅ | TMDb w185 |
| Crew | `episode.info.crew` | string | ⚠️ | Comma-separated, needs parsing |
| TMDb ID | `episode.info.id` | int | ✅ | Series ID (not episode) |

### Technical Quality Indicators

| Field | Location | Use Case |
|-------|----------|----------|
| Resolution | `video.width` × `video.height` | Quality badges (4K, 1080p, 720p) |
| Codec | `video.codec_name` | Format info (AV1, H.264, HEVC) |
| Bitrate | `info.bitrate` | Quality estimate |
| Audio Codec | `audio.codec_name` | Audio quality (Opus, AAC, AC3) |
| Audio Channels | `audio.channels` | Surround sound detection |
| Language | `audio.tags.language` | Multi-audio support |

---

## Data Parsing Requirements

### Episode Title Parsing
Format: `"EN - Star Trek (1966) - S03E01"`

Extract:
- Language prefix: `EN`
- Series name: `Star Trek`
- Year: `1966`
- Season/Episode: `S03E01`

### Crew Parsing
Format: Comma-separated string of names

Example:
```
"Gene L. Coon, Marc Daniels, Walter M. Jefferies, ..."
```

Could be used for:
- Director detection (first name often director)
- Cast/crew search
- Alert patterns

### Resolution Detection
```python
def get_quality_badge(width: int, height: int) -> str:
    if height >= 2160: return "4K"
    elif height >= 1080: return "1080p"
    elif height >= 720: return "720p"
    elif height >= 480: return "480p"
    else: return "SD"
```

---

## Future Provider Comparison

### What Xtream Provides
- ✅ Rich technical metadata (codecs, bitrates, etc.)
- ✅ TMDb integration (IDs, thumbnails)
- ✅ Episode-level metadata
- ⚠️ Title parsing required
- ⚠️ Crew as comma-separated string

### What Other Providers Might Provide
- **Plex**: Structured metadata, better episode info, watch status
- **Jellyfin**: Similar to Plex, open format
- **TMDb Direct**: Rich plot summaries, full cast/crew objects
- **OMDb**: Alternative metadata source

### Provider-Agnostic Model Requirements
See [ROADMAP.md](../ROADMAP.md) - Phase 2: Provider-agnostic data layer

The internal data model should:
1. Normalize all providers to common fields
2. Support optional/provider-specific extensions
3. Handle missing data gracefully
4. Provide adapters for each provider format

---

## Database Mapping

Current SQLAlchemy models:

### SeasonDB
```python
id: str                  # {series_id}_s{season_num}
series_id: str           # From channel.source_id
provider_id: str         # Provider UUID
season_number: int       # From season_data.season_number
name: str                # From season_data.name
cover_url: str           # From season_data.cover
episode_count: int       # From len(episodes)
series_name: str         # Denormalized from parent
raw_data: JSON           # Full season_data dict
```

### EpisodeDB
```python
id: str                  # {provider_id}_{episode_id}
season_id: str           # FK to SeasonDB
series_id: str           # FK to ChannelDB (series entry)
provider_id: str
episode_id: str          # From episode.id
episode_num: int         # From episode.episode_num
season_num: int          # From episode.season
title: str               # From episode.title
duration: str            # From episode.info.duration
container_extension: str # From episode.container_extension
stream_url: str          # Constructed URL
cover_url: str           # From episode.info.movie_image
is_watched: bool         # User tracking
watch_progress: int      # Seconds watched
last_played: DateTime    # User tracking
play_count: int          # User tracking
series_name: str         # Denormalized
raw_data: JSON           # Full episode dict
```

---

## Implementation Notes

### Current Status (v0.1.0)
- ✅ Series data loading from Xtream API
- ✅ Season/episode database storage
- ✅ Tree UI with accordion navigation
- ⚠️ Title parsing not implemented
- ⚠️ Metadata extraction minimal
- ⚠️ TMDb integration not started

### Next Steps
1. **Title Parser**: Extract language, series, year, episode codes
2. **Metadata Extractor**: Convert raw_data to searchable fields
3. **Quality Detector**: Parse resolution/codec for badges
4. **TMDb Enrichment**: Use episode.info.id to fetch additional data
5. **Provider Adapter Pattern**: Prepare for Plex, Jellyfin support

---

## Example: Complete Episode Data

```json
{
  "id": "1004425",
  "episode_num": 1,
  "season": 3,
  "title": "EN - Star Trek (1966) - S03E01",
  "container_extension": "mkv",
  "added": "1662142840",
  "custom_sid": null,
  "direct_source": "",
  "info": {
    "air_date": "1968-09-20",
    "crew": "Gene L. Coon, Marc Daniels, Walter M. Jefferies, William Ware Theiss, ...",
    "rating": 5.8,
    "id": 253,
    "movie_image": "https://image.tmdb.org/t/p/w185/2oGU0wcPmGmgplUWV5PvvcV4lH8.jpg",
    "duration_secs": 3368,
    "duration": "00:56:08",
    "video": {
      "codec_name": "av1",
      "width": 1440,
      "height": 1080,
      "r_frame_rate": "24000/1001"
    },
    "audio": {
      "codec_name": "opus",
      "channels": 2,
      "sample_rate": "48000"
    },
    "bitrate": 1181
  }
}
```

### Parsed Representation
```python
Episode(
    id="4814008b-38ab-4db1-b790-0e22aaec89e1_1004425",
    series="Star Trek",
    year=1966,
    language="EN",
    season=3,
    episode=1,
    title="S03E01",  # or fetch real title from TMDb
    duration_seconds=3368,
    air_date=date(1968, 9, 20),
    rating=5.8,
    quality="1080p",
    codec="AV1",
    thumbnail_url="https://image.tmdb.org/t/p/w185/2oGU0wcPmGmgplUWV5PvvcV4lH8.jpg",
    stream_url="http://provider.com/series/user/pass/1004425.mkv"
)
```

---

## References

- Xtream Codes API Documentation: (unofficial/community docs)
- TMDb Image URLs: `https://image.tmdb.org/t/p/{size}{path}`
  - Sizes: w154, w185, w300, w500, original
- FFmpeg codec names: Standard FFmpeg codec identifiers
