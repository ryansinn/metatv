"""Migration task: clear regions a row inherited on the strength of an age rating.

Owner report (2026-09-08): ``18+ - Truly Naked (2026)`` — category ``RATED R``,
English audio, fr/fa/nl subtitles — showed ``detected_region = "DE"`` and carried
a ``language=German`` tag derived from it.

Cause (fixed forward in ``_contradicts_own_locale``): ``parse_channel_name``
yields no usable region for that name, because ``18+`` is an age RATING. The
final ingestion pass then filled the empty ``detected_region`` from the most
common region among the row's ``content_key`` siblings — here ``tmdb:1281195
|movie``, whose other two rows are genuine ``DE - Truly Naked (2026)``. Majority
won, DE was stamped, and "German" followed it into the tag set.

The guard that should have caught it existed and was one concept short: a row
carrying its OWN locale code (``EN``, ``AR`` …) already refuses the fill, because
an empty region there is a fact rather than a gap. An age rating is not a locale
code, so the row looked eligible. It is the same fact with less information: a
rating says what may be WATCHED, never where.

Measured on the owner's library before the fix: of rows with an age-rating
prefix, 312 were correctly empty and **154 carried an inherited region** — DE 40,
PL 26, FR 17, ES 12, ALB 10, IT 6, IN 6, and a long tail. The damage reads like
a list of things that are not German: "A Serbian Film", "Benedetta (FRENCH MULTI
SUB)", "Bula (TAGALOG ENG-SUB)".

**It only ever CLEARS, never rewrites** — the same rule as its sibling
``bad_region_cleanup.py``, whose batch writer it shares. Guessing a *different*
country from an age rating would repeat the original mistake in a new direction.
Empty is honest.

Scope: rows whose ``detected_prefix`` IS an age rating
(:data:`~metatv.core.channel_name_utils.AGE_RATING_PREFIXES`) and whose
``detected_region`` is non-empty. A row whose own NAME carries a region —
``DE - Truly Naked (2026)`` — has ``detected_prefix = "DE"``, so it is outside
the predicate and keeps its DE.

Idempotency
-----------
``needs_run`` compares ``config.age_rating_region_cleanup_version`` against
``CURRENT_VERSION`` (``VersionGatedTask``). An interrupted or crashing run leaves
the version unbumped so the next launch restarts it; already-committed batches
are durable, and because the pass only clears it converges — a second run over
already-cleaned rows selects nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from loguru import logger

from metatv.core.channel_name_utils import AGE_RATING_PREFIXES
from metatv.core.migrations.bad_region_cleanup import clear_regions_and_derived_tags
from metatv.core.migrations.base import VersionGatedTask

if TYPE_CHECKING:
    from metatv.core.config import Config

# Bump to re-run the cleanup for all users on next launch.
# History:
#   1 — initial sweep: clear detected_region (and the region/language tags it
#       produced) on every row whose detected_prefix is an age rating.
CURRENT_VERSION: int = 1

_BATCH = 2000


class AgeRatingRegionCleanupTask(VersionGatedTask):
    """Clear ``detected_region`` on rows whose only prefix is an age rating."""

    id: str = "age_rating_region_cleanup"
    label: str = "Clearing regions guessed from an age rating"

    VERSION_FIELD: str = "age_rating_region_cleanup_version"
    CURRENT_VERSION: int = CURRENT_VERSION

    def run(
        self,
        progress_cb: Callable[[int, int], None],
        is_cancelled: Callable[[], bool],
        config: "Config | None" = None,
    ) -> None:
        """Clear every age-rating-inherited region, in committed batches.

        Runs on a **worker thread** (called by ``MigrationManager``). Exceptions
        propagate so the manager leaves the version unbumped and the task retries
        next launch (#364 crash-retry semantics).

        Args:
            progress_cb: ``(done, total)`` called after each batch commit.
            is_cancelled: Returns True when the manager has been asked to stop.
            config: Unused; accepted for forward-compat with the manager's
                keyword call.
        """
        from metatv.core.database import ChannelDB

        logger.info(
            "AgeRatingRegionCleanupTask: scanning for regions inherited by "
            "age-rating rows (version={})", CURRENT_VERSION,
        )

        with self._db.session_scope() as session:
            doomed: list[tuple[str, str]] = [
                (cid, region)
                for cid, region in session.query(
                    ChannelDB.id, ChannelDB.detected_region
                )
                .filter(ChannelDB.detected_prefix.in_(sorted(AGE_RATING_PREFIXES)))
                .filter(ChannelDB.detected_region.isnot(None))
                .filter(ChannelDB.detected_region != "")
                .all()
            ]

        total = len(doomed)
        logger.info(
            "AgeRatingRegionCleanupTask: {:,} age-rating row(s) carry a region "
            "nothing on the row supports", total,
        )
        if not total:
            progress_cb(0, 0)
            return

        done = 0
        for start in range(0, total, _BATCH):
            if is_cancelled():
                logger.info(
                    "AgeRatingRegionCleanupTask: cancelled at {}/{}", done, total
                )
                return
            chunk = doomed[start:start + _BATCH]
            clear_regions_and_derived_tags(self._db, chunk)
            done += len(chunk)
            progress_cb(done, total)

        logger.info(
            "AgeRatingRegionCleanupTask: cleared {:,} inherited region(s)", done
        )
