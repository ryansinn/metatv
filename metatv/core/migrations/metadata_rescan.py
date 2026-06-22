"""Migration task: re-derive stale metadata for channels whose stream ID was reused.

IPTV providers recycle stream IDs for different content over time.  Before the
stream-ID-reuse guard landed in ``_flush_batch``, a channel whose name changed on
refresh kept its old ``metadata_id`` — so the details pane showed the previous
occupant's poster/title.

This task finds every channel whose linked ``MetadataDB.title`` is inconsistent
with the channel's current name and re-derives the metadata from the channel's
stored ``raw_data`` via ``ProviderMetadataProvider``.  Because ``raw_data`` is
updated at each provider refresh (it is in ``_CATALOG_UPDATE_COLS``), re-derivation
from it produces correct metadata for the current content even for channels on
sources that were later removed.

Staleness signal
----------------
``MetadataDB.title`` stores the title extracted at derivation time
(``info.get('name') or channel.name``).  For the stale case, that title belongs to
the previous occupant.  We flag a link as stale when ``metadata.title`` shares no
alphabetic tokens (≥ 3 chars) with the channel's bare name after stripping common
IPTV prefixes.  We use ``channel.detected_title`` (stored at ingestion) when
available; otherwise the full ``channel.name`` is used.

False-positive risk: channels whose metadata title is a translation or abbreviation
of their channel name.  False-positive rate is low in practice because legitimate
metadata titles almost always share at least one significant word with the channel
name.

Idempotency
-----------
Processing is done in batches; cancellation leaves the completed batches durable.
``on_completed`` bumps ``config.metadata_rescan_version`` so the task won't re-run
unless we explicitly bump ``CURRENT_METADATA_RESCAN_VERSION``.
"""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Callable

from loguru import logger

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database

# Bump this constant to re-trigger the backfill for all users on next launch.
#
# History:
#   1 — initial backfill: re-derive metadata for stale stream-ID-reuse links.
CURRENT_METADATA_RESCAN_VERSION = 1

# Process this many channels per batch to keep memory bounded and give cooperative
# cancellation a chance to fire between batches.
_BATCH_SIZE = 500

# Minimum token length for the staleness overlap check — short tokens like "TV",
# "HD", "the" produce too many false matches, so we require ≥ 3 alphabetic chars.
_MIN_TOKEN_LEN = 3


def _alpha_tokens(text: str) -> set[str]:
    """Return the set of lower-cased alphabetic tokens (≥ _MIN_TOKEN_LEN chars) in *text*."""
    return {
        t.lower()
        for t in re.findall(r"[a-zA-Z]+", text)
        if len(t) >= _MIN_TOKEN_LEN
    }


def _is_stale_link(channel_name: str, detected_title: str | None,
                   metadata_title: str) -> bool:
    """Return True when the metadata title looks like it belongs to different content.

    Uses ``detected_title`` (prefix-stripped name stored at ingestion) as the
    normalized channel name when available; falls back to the full ``channel.name``.
    A link is considered stale when the two token sets share **no** tokens at all —
    i.e. zero alphabetic words overlap after case-folding.
    """
    bare = (detected_title or channel_name).strip()
    channel_tokens = _alpha_tokens(bare)
    meta_tokens = _alpha_tokens(metadata_title)
    if not channel_tokens or not meta_tokens:
        # Can't decide — leave it alone.
        return False
    return channel_tokens.isdisjoint(meta_tokens)


class MetadataRescanTask:
    """Backfill migration: re-derive metadata for channels with stale links.

    Iterates channels that have a ``metadata_id`` and whose linked
    ``MetadataDB.title`` has zero token overlap with the current channel name.
    For each stale channel it calls ``MetadataManager.get_metadata`` with
    ``force_refresh=True``, which clears the old cache row and re-derives from
    ``raw_data`` via ``ProviderMetadataProvider``.
    """

    id: str = "metadata_rescan"
    label: str = "Re-deriving metadata for changed channels"

    def __init__(self, db: "Database", metadata_manager) -> None:
        """
        Args:
            db: Database instance.
            metadata_manager: MetadataManager instance (owns the provider chain).
        """
        self._db = db
        self._metadata_manager = metadata_manager

    def needs_run(self, config: "Config") -> bool:
        """Return True when the backfill has not yet run for the current version."""
        stored = getattr(config, "metadata_rescan_version", 0)
        return stored < CURRENT_METADATA_RESCAN_VERSION

    def run(
        self,
        progress_cb: Callable[[int, int], None],
        is_cancelled: Callable[[], bool],
    ) -> None:
        """Execute the stale-metadata backfill.

        Runs on a **worker thread** (called by MigrationManager).  Uses
        ``asyncio.run()`` to drive the async ``MetadataManager.get_metadata``
        calls, one per stale channel.

        Args:
            progress_cb: ``(done, total)`` called after each batch.
            is_cancelled: Returns True when the manager has been asked to stop.
        """
        logger.info(
            "MetadataRescanTask: scanning for stale metadata links "
            "(version={})", CURRENT_METADATA_RESCAN_VERSION,
        )

        stale_ids = self._find_stale_channel_ids()
        total = len(stale_ids)

        if total == 0:
            logger.info("MetadataRescanTask: no stale links found — nothing to do")
            progress_cb(0, 0)
            return

        logger.info("MetadataRescanTask: found {} stale metadata link(s)", total)

        done = 0
        for batch_start in range(0, total, _BATCH_SIZE):
            if is_cancelled():
                logger.info(
                    "MetadataRescanTask: cancelled after {}/{}", done, total
                )
                return

            chunk = stale_ids[batch_start : batch_start + _BATCH_SIZE]
            refreshed = self._refresh_batch(chunk)
            done = min(batch_start + len(chunk), total)
            logger.info(
                "MetadataRescanTask: batch {}–{}: refreshed {} channel(s)",
                batch_start, done, refreshed,
            )
            progress_cb(done, total)

        logger.info(
            "MetadataRescanTask: completed — processed {} stale link(s)", total
        )

    def on_completed(self, config: "Config") -> None:
        """Bump the version field so the task won't re-run on next launch."""
        config.metadata_rescan_version = CURRENT_METADATA_RESCAN_VERSION
        config.save()
        logger.debug(
            "MetadataRescanTask: bumped metadata_rescan_version={}",
            CURRENT_METADATA_RESCAN_VERSION,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _find_stale_channel_ids(self) -> list[str]:
        """Query the DB and return IDs of channels with stale metadata links."""
        from metatv.core.database import ChannelDB, MetadataDB

        stale: list[str] = []
        with self._db.session_scope(commit=False) as session:
            # Only channels that actually have a metadata link.
            rows = (
                session.query(
                    ChannelDB.id,
                    ChannelDB.name,
                    ChannelDB.detected_title,
                    MetadataDB.title,
                )
                .join(MetadataDB, ChannelDB.metadata_id == MetadataDB.id)
                .filter(ChannelDB.metadata_id.isnot(None))
                .filter(MetadataDB.title.isnot(None))
                .all()
            )

        for channel_id, channel_name, detected_title, meta_title in rows:
            if _is_stale_link(channel_name, detected_title, meta_title):
                stale.append(channel_id)

        return stale

    def _refresh_batch(self, channel_ids: list[str]) -> int:
        """Force-refresh metadata for each channel in *channel_ids*.

        Returns the number of channels whose metadata was successfully refreshed.
        """
        refreshed = 0
        for channel_id in channel_ids:
            try:
                result = asyncio.run(
                    self._metadata_manager.get_metadata(
                        channel_id, force_refresh=True
                    )
                )
                if result is not None:
                    refreshed += 1
            except Exception:
                logger.warning(
                    "MetadataRescanTask: failed to refresh channel {}",
                    channel_id,
                    exc_info=True,
                )
        return refreshed
