"""Migration task: clear stored regions the region table cannot name (ledger F4).

The parser stored ANY trailing 2-3 letter token as the title's region, in
round brackets always and in square ones by a generic fallback. On the owner's
library 2026-11-01, 113 of 259 distinct region codes had no name, on 1,446
rows: "SUB" 675 and "DUB" 465 (subtitle/dub markers), "DOC", "(BK)" backup
feeds, team codes ("[TOR]"), Australian states, and language codes the table
lacked ("[SPA]", "(PNJ)", "(VFQ)"). The parser now accepts only codes the table
knows, and those language codes are aliases.

This only CLEARS (through the shared ``clear_regions_and_derived_tags``, which
also drops the region/language tags derived from the value). It runs before
``detected_title_reparse``, whose fill-empty pass then re-derives each cleared
row's region with the fixed parser — "[SPA]" comes back as ES.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from loguru import logger

from metatv.core.migrations.bad_region_cleanup import clear_regions_and_derived_tags
from metatv.core.migrations.base import VersionGatedTask
from metatv.core.region_codes import REGION_FULL_NAMES

if TYPE_CHECKING:
    from metatv.core.config import Config

# Bump to re-run for every user on next launch.
#   1 — initial sweep (F4).
CURRENT_VERSION: int = 1

_BATCH = 2000


class UnknownRegionCleanupTask(VersionGatedTask):
    """Clear ``detected_region`` values ``REGION_FULL_NAMES`` cannot name."""

    id: str = "unknown_region_cleanup"
    label: str = "Clearing region codes nothing can name"

    VERSION_FIELD: str = "unknown_region_cleanup_version"
    CURRENT_VERSION: int = CURRENT_VERSION

    def run(self, progress_cb: Callable[[int, int], None],
            is_cancelled: Callable[[], bool], config: "Config | None" = None) -> None:
        from metatv.core.database import ChannelDB
        with self._db.session_scope() as session:
            doomed = [(cid, region) for cid, region in session.query(ChannelDB.id, ChannelDB.detected_region)
                      .filter(ChannelDB.detected_region.isnot(None), ChannelDB.detected_region != "")
                      if region not in REGION_FULL_NAMES]
        total = len(doomed)
        logger.info("unknown_region_cleanup: {:,} row(s) carry a region code nothing names", total)
        progress_cb(0, total)
        for start in range(0, total, _BATCH):
            if is_cancelled():
                return
            chunk = doomed[start:start + _BATCH]
            clear_regions_and_derived_tags(self._db, chunk)
            progress_cb(start + len(chunk), total)
