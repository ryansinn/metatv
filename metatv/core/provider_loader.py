"""Provider data loading and management"""

import asyncio
import re
from typing import Optional, Dict, Any, List
from PyQt6.QtCore import QThread, pyqtSignal
from loguru import logger
from sqlalchemy.dialects.sqlite import insert as _sqlite_insert

from metatv.core.models import Provider, MediaType
from metatv.core.database import Database, ChannelDB, SeasonDB, EpisodeDB, ProviderDB
from metatv.core.repositories.provider import parse_provider_urls
from metatv.providers.factory import get_provider

# Columns written by the catalog loader on every channel upsert.
# On conflict (same `id`), ONLY these columns are updated — derived fields
# (detected_*, is_favorite, is_hidden, play_count, user_category, etc.) are
# left untouched so user data is preserved across provider refreshes.
_CATALOG_COLS: tuple[str, ...] = (
    "id",
    "source_id",
    "provider_id",
    "name",
    "stream_url",
    "category",
    "category_id",
    "logo_url",
    "media_type",
    "quality",
    "is_adult",
    "raw_data",
    "source_num",
    "source_category",
    "source_quality_flags",
)

# The same set minus `id` — on conflict we update all catalog fields except the PK.
_CATALOG_UPDATE_COLS: tuple[str, ...] = tuple(c for c in _CATALOG_COLS if c != "id")

# Batch size for bulk upsert VALUES lists.
# SQLite ≥3.32 raises SQLITE_MAX_VARIABLE_NUMBER at 32766 by default; older
# builds cap at 999. With ~15 catalog columns, 500 rows × 15 cols = 7 500
# parameters — well inside either limit and far fewer commits than every-100.
_STORE_BATCH = 500

_HASH_HEADER_RE = re.compile(r'^#{2,}\s*(.*?)\s*#{2,}$')

# Superscript quality markers embedded in ## category headers ##
_SUPERSCRIPT_QUALITY: list[tuple[str, str]] = [
    ("ᴴᴰ",   "HD"),
    ("ᵁᴴᴰ",  "UHD"),
    ("ᴿᴬᵂ",  "RAW"),
    ("⁶⁰ᶠᵖˢ", "60FPS"),
    ("⁵⁰ᶠᵖˢ", "50FPS"),
]


def _parse_hash_header(name: str) -> tuple[str, str] | None:
    """Return (clean_label, quality_flags) if *name* is a ##...## header, else None.

    quality_flags is a comma-separated string of decoded markers (may be empty).
    """
    m = _HASH_HEADER_RE.match(name)
    if not m:
        return None
    label = m.group(1)
    flags: list[str] = []
    for superscript, flag in _SUPERSCRIPT_QUALITY:
        if superscript in label:
            label = label.replace(superscript, "").strip()
            flags.append(flag)
    return label.strip(), ",".join(flags)


class ProviderLoadThread(QThread):
    """Background thread for loading provider data into database"""

    finished = pyqtSignal(bool, str)  # success, message
    progress = pyqtSignal(int, int, str)  # current, total, message

    def __init__(self, provider: Provider, db: Database,
                 separators: list[str] | None = None,
                 language_groups: dict | None = None,
                 quality_groups: dict | None = None,
                 platform_groups: dict | None = None,
                 regional_groups: dict | None = None):
        super().__init__()
        self.provider = provider
        self.db = db
        self._separators = separators
        self._language_groups = language_groups or {}
        self._quality_groups = quality_groups or {}
        self._platform_groups = platform_groups or {}
        self._regional_groups = regional_groups or {}
        self.prefix_stats: dict | None = None  # populated after run; read by main thread
    
    def run(self):
        """Load provider data"""
        try:
            asyncio.run(self.load_provider())
        except Exception as e:
            logger.error(f"Provider load error: {e}")
            self.finished.emit(False, str(e))
    
    async def load_provider(self):
        """Load provider data using provider plugin"""
        provider_plugin = get_provider(self.provider.type)
        if not provider_plugin:
            self.finished.emit(False, f"Unknown provider type: {self.provider.type}")
            return

        def on_progress(current, total, message):
            self.progress.emit(current, total, message)

        channels = await provider_plugin.fetch_channels(self.provider, progress_callback=on_progress)

        # Deduplicate by channel ID: some providers return the same stream_id in multiple
        # category responses, producing duplicate channel.id values. Under no_autoflush the
        # pending INSERT is not visible to merge()'s SELECT, causing UNIQUE constraint errors.
        # Keep the last occurrence per ID (same result as repeated merge/UPDATE calls).
        seen: dict[str, object] = {}
        for ch in channels:
            seen[ch.id] = ch
        if len(seen) < len(channels):
            logger.warning(
                f"{self.provider.name}: dropped {len(channels) - len(seen):,} duplicate "
                f"channel IDs (same stream_id in multiple categories)"
            )
        channels = list(seen.values())

        total = len(channels)
        logger.info(f"Loaded {total:,} items from {self.provider.name}")

        # Refresh account info in the background while channels are being stored
        await self._refresh_account_info(provider_plugin)

        # Persist updated URL success/failure counts back to the DB
        if self.provider.urls:
            url_session = self.db.get_session()
            try:
                db_prov = url_session.query(ProviderDB).filter_by(id=self.provider.id).first()
                if db_prov:
                    raw = parse_provider_urls(db_prov.urls)
                    # Merge updated counts from the in-memory ProviderURL objects
                    url_map = {pu.url.rstrip('/'): pu for pu in self.provider.urls}
                    for entry in raw:
                        key = entry.get('url', '').rstrip('/')
                        if key in url_map:
                            pu = url_map[key]
                            entry['success_count'] = pu.success_count
                            entry['failure_count'] = pu.failure_count
                    db_prov.urls = raw
                    url_session.commit()
            except Exception as e:
                logger.warning(f"Failed to persist URL stats: {e}")
            finally:
                url_session.close()
        
        # Store in database
        session = self.db.get_session()

        try:
            self._store_channels(session, channels, total)
            self.progress.emit(70, 100, f"Stored {total:,} channels")

        except Exception as e:
            session.rollback()
            logger.error(f"Database error during provider load: {e}")
            raise
        finally:
            session.close()

        # Phase: categorize special content (PPV / Events / Sports)
        self.progress.emit(72, 100, "Categorizing content (PPV/Events/Sports)…")
        self._categorize_special_content()

        # Phase: detect channel prefixes
        self.progress.emit(87, 100, "Detecting channel prefixes…")
        self._update_prefixes_in_thread()

        # Phase: compute prefix stats for the filter bar
        self.progress.emit(97, 100, "Updating filter statistics…")
        self._compute_prefix_stats_in_thread()

        self.progress.emit(100, 100, f"Loaded {total:,} channels")

        # If we loaded 0 channels, report as failure — this may indicate a timeout,
        # rate limit, network error, or an empty provider. The user needs visibility.
        if total == 0:
            self.finished.emit(False,
                f"Connected to {self.provider.name}, but received 0 channels — the server may be slow, "
                f"rate-limited, or returned no content. Check the logs and try again.")
        else:
            self.finished.emit(True, f"Loaded {total:,} channels successfully")

    def _store_channels(self, session, channels: list, total: int) -> None:
        """Bulk-upsert *channels* into the DB using SQLite's INSERT OR REPLACE semantics.

        Replaces the old per-row ``session.merge()`` + commit-every-100 approach.
        Key properties preserved:

        * **Order is maintained** — the per-channel loop runs in list order so the
          stateful ``##...##`` hash-header logic (which sets ``source_category`` /
          ``source_quality_flags`` for all subsequent live channels) is correct.
        * **User/derived columns are preserved** — the ``ON CONFLICT DO UPDATE``
          clause only touches ``_CATALOG_UPDATE_COLS``; fields like ``is_favorite``,
          ``play_count``, ``detected_*``, ``user_category``, etc. are untouched on
          existing rows.
        * **Short transaction windows** — ``autoflush=False`` (via ``no_autoflush``)
          means SQLite only holds the write lock during each explicit ``commit()``,
          giving concurrent provider-load threads windows to interleave writes and
          avoiding SQLITE_BUSY errors.
        * **Batch size** — ``_STORE_BATCH`` rows × 15 columns ≈ 7 500 SQL parameters,
          well within SQLite's 32 766 limit (and even the legacy 999 limit with room to
          spare for older builds).
        """
        batch: list[dict] = []
        processed = 0
        current_source_category: str | None = None
        current_source_quality: str | None = None

        # Disable autoflush so writes only happen at each explicit commit().
        # Without this, ORM operations would trigger an autoflush before internal
        # SELECTs, holding the SQLite write lock across up to 100 items.  With
        # no_autoflush the write transaction only opens at commit() and closes
        # immediately, giving other providers interleave windows.
        with session.no_autoflush:
            for channel in channels:
                raw = channel.raw_data or {}
                is_adult = bool(raw.get("is_adult") in (1, "1", True))
                source_num = raw.get("num")
                if source_num is not None:
                    try:
                        source_num = int(source_num)
                    except (ValueError, TypeError):
                        source_num = None

                # Detect ##...## positional category headers (live only).
                # This is stateful — the header applies to all subsequent live
                # channels until the next header.  Processing must stay in order.
                if channel.media_type == "live":
                    parsed = _parse_hash_header(channel.name)
                    if parsed is not None:
                        current_source_category = parsed[0] or None
                        current_source_quality = parsed[1] or None

                batch.append({
                    "id": channel.id,
                    "source_id": channel.source_id,
                    "provider_id": channel.provider_id,
                    "name": channel.name,
                    "stream_url": channel.stream_url,
                    "category": channel.category,
                    "category_id": channel.category_id,
                    "logo_url": channel.logo_url,
                    "media_type": channel.media_type,
                    "quality": channel.quality.value,
                    "is_adult": is_adult,
                    "raw_data": channel.raw_data,
                    "source_num": source_num,
                    "source_category": current_source_category if channel.media_type == "live" else None,
                    "source_quality_flags": current_source_quality if channel.media_type == "live" else None,
                })

                processed += 1
                if len(batch) >= _STORE_BATCH:
                    self._flush_batch(session, batch)
                    batch.clear()
                    percent = int(50 + (processed / total * 20)) if total else 70  # 50–70%
                    self.progress.emit(percent, 100, f"Storing channels ({processed:,}/{total:,})...")

            # Flush the final partial batch
            if batch:
                self._flush_batch(session, batch)
                batch.clear()

    @staticmethod
    def _flush_batch(session, batch: list[dict]) -> None:
        """Execute one bulk upsert for *batch* and commit the transaction.

        Uses SQLite's ``INSERT INTO ... ON CONFLICT(id) DO UPDATE SET ...``
        to insert new rows and update only catalog columns on conflict.
        Derived/user columns (``is_favorite``, ``play_count``, ``detected_*``,
        ``user_category``, etc.) are NOT in the SET clause and are preserved.
        """
        stmt = _sqlite_insert(ChannelDB).values(batch)
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={col: getattr(stmt.excluded, col) for col in _CATALOG_UPDATE_COLS},
        )
        session.execute(stmt)
        session.commit()

    def _categorize_special_content(self) -> None:
        """Categorize PPV / Events / Sports for uncategorized channels from this provider.

        Only processes channels where special_view IS NULL so subsequent refreshes
        of the same provider are fast.  All providers are always included in the
        queries — this scopes to the just-loaded provider to bound the work.
        """
        from metatv.core.special_content import update_channel_special_content

        session = self.db.get_session()
        try:
            channels = session.query(ChannelDB).filter(
                ChannelDB.provider_id == self.provider.id,
                ChannelDB.special_view.is_(None),
            ).all()

            if not channels:
                return

            logger.info(
                f"Categorizing special content for {len(channels):,} uncategorized "
                f"channels from '{self.provider.name}'"
            )

            updated = 0
            n = len(channels)
            for i, channel in enumerate(channels):
                if update_channel_special_content(channel):
                    updated += 1
                if i % 5000 == 4999:
                    session.commit()
                    pct = int(72 + (i / n) * 15)  # 72–87%
                    self.progress.emit(pct, 100, f"Categorizing content ({i+1:,}/{n:,})…")

            session.commit()
            logger.info(
                f"Special content: {updated:,} channels categorized "
                f"(PPV/Events/Sports) for '{self.provider.name}'"
            )
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to categorize special content: {e}")
        finally:
            session.close()

    def _update_prefixes_in_thread(self) -> None:
        """Run update_detected_prefixes in the worker thread (never the main thread)."""
        from metatv.core.repositories import RepositoryFactory
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            updated = repos.channels.update_detected_prefixes(
                provider_id=self.provider.id,
                separators=self._separators,
            )
            logger.info(f"Prefix detection: updated {updated:,} channels")
        except Exception as e:
            logger.error(f"Prefix detection failed: {e}")
        finally:
            session.close()

    def _compute_prefix_stats_in_thread(self) -> None:
        """Compute prefix stats and store on self.prefix_stats for the main thread."""
        from metatv.core.repositories import RepositoryFactory
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            self.prefix_stats = repos.channels.get_prefix_stats(
                provider_id=None,
                language_groups=self._language_groups,
                quality_groups=self._quality_groups,
                platform_groups=self._platform_groups,
                regional_groups=self._regional_groups,
            )
        except Exception as e:
            logger.error(f"Prefix stats failed: {e}")
            self.prefix_stats = None
        finally:
            session.close()

    async def _refresh_account_info(self, provider_plugin) -> None:
        """Fetch and store fresh account/subscription info after a channel load."""
        if not hasattr(provider_plugin, "fetch_account_info"):
            return
        try:
            info = await provider_plugin.fetch_account_info(self.provider)
            if not info:
                return
            from metatv.core.database import ProviderDB
            from datetime import datetime as _dt
            acct_session = self.db.get_session()
            try:
                db_prov = acct_session.query(ProviderDB).filter_by(id=self.provider.id).first()
                if db_prov:
                    db_prov.account_status = info.get("status")
                    db_prov.max_connections = info.get("max_connections", 1)
                    db_prov.account_active_cons = info.get("active_cons", 0)
                    exp_ts = info.get("exp_date")
                    if exp_ts:
                        db_prov.account_exp_date = _dt.fromtimestamp(int(exp_ts))
                    created_ts = info.get("created_at")
                    if created_ts:
                        db_prov.account_created_at = _dt.fromtimestamp(int(created_ts))
                    acct_session.commit()
                    logger.info(
                        f"Account info refreshed for '{self.provider.name}': "
                        f"status={info.get('status')} exp={db_prov.account_exp_date}"
                    )
            except Exception as e:
                acct_session.rollback()
                logger.warning(f"Failed to store account info: {e}")
            finally:
                acct_session.close()
        except Exception as e:
            logger.warning(f"Failed to fetch account info during load: {e}")


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
        session = self.db.get_session()
        try:
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

            # Handle case where there are episodes but no seasons metadata
            # Create a default season so episodes can be stored and displayed
            if season_count == 0 and total_episodes > 0:
                logger.info(f"No seasons metadata but {total_episodes} episodes found - creating default season")
                # Find which season numbers have episodes
                season_nums = [int(s) for s in episodes_by_season.keys() if s.isdigit()]
                if not season_nums:
                    season_nums = [1]  # Default to season 1

                # Create a season entry for each season number that has episodes
                seasons = []
                for season_num in sorted(season_nums):
                    season_key = str(season_num)
                    episode_count = len(episodes_by_season.get(season_key, []))
                    seasons.append({
                        "season_number": season_num,
                        "name": f"Season {season_num}",
                        "cover": "",
                        "episodes": episode_count
                    })
                    logger.debug(f"Created default season {season_num} with {episode_count} episodes")

                season_count = len(seasons)
            else:
                # Seasons metadata exists but may not cover all episode groups.
                # Some providers (e.g. ProSat) return season metadata for season 1 only
                # but split episodes across groups "1" and "2". Append synthetic season
                # entries for any episode groups not already represented.
                covered = {str(s.get("season_number", 0)) for s in seasons if isinstance(s, dict)}
                for season_key in sorted(episodes_by_season.keys()):
                    if season_key.isdigit() and season_key not in covered:
                        season_num = int(season_key)
                        episode_count = len(episodes_by_season[season_key])
                        seasons.append({
                            "season_number": season_num,
                            "name": f"Season {season_num}",
                            "cover": "",
                            "episodes": episode_count
                        })
                        logger.info(
                            f"Episode group '{season_key}' has no season metadata entry — "
                            f"created synthetic Season {season_num} with {episode_count} episodes"
                        )
                season_count = len(seasons)
            
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
                    
                    # Build stream URL (strip trailing slash to avoid double-slash)
                    container = episode_data.get("container_extension", "mp4")
                    base = self.provider.url.rstrip("/")
                    stream_url = f"{base}/series/{self.provider.username}/{self.provider.password}/{episode_id}.{container}"
                    
                    info = episode_data.get("info", {})
                    duration = info.get("duration", "") or episode_data.get("duration", "")

                    if existing_episode:
                        # Update existing
                        existing_episode.title = episode_data.get("title", f"Episode {episode_num}")
                        existing_episode.duration = duration
                        existing_episode.stream_url = stream_url
                        existing_episode.cover_url = info.get("movie_image", "")
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
                            duration=duration,
                            container_extension=container,
                            stream_url=stream_url,
                            cover_url=info.get("movie_image", ""),
                            series_name=self.series_name,
                            raw_data=episode_data
                        )
                        session.add(episode)
            
            session.commit()
            logger.info(f"Stored {season_count} seasons and {total_episodes} episodes for {self.series_name}")
        finally:
            session.close()

        self.finished.emit(True, f"Loaded {season_count} seasons", series_data)

