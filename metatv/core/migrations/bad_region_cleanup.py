"""Migration task: clear regions that contradict a row's own locale prefix.

Owner report: ``|EN| Aladdin 4K`` showed ``detected_region = "DE"``, and so did
``|AR| Aladdin`` — an Arabic release presented as German. Measured across the
owner's library: **74,172 rows** carrying a region that contradicts their own
prefix, across 420 distinct (prefix, region) pairs. Worst offenders were
``EN→DE`` (8,242), ``EN→FR`` (6,139), ``AR→DE`` (4,899).

Cause (fixed forward in ``_propagate_region_from_siblings_impl``): the final
ingestion pass filled an empty ``detected_region`` from the *most common* region
among ``content_key`` siblings. ``content_key`` is deliberately generous —
``"aladdin|movie|"`` carries no year and no TMDb id, so 15 unrelated releases
collapse into it — which made "most common sibling region" mean "whichever
locale dominates this library". Platform-prefixed rows were hit the same way:
``A+`` (Apple TV+) and ``D+`` (Disney+) titles, overwhelmingly US, were handed
DE/FR/ES.

That forward fix is fill-empty-only by design, so it prevents new mislabels and
leaves every existing one in place. This task is the one-time cleanup.

**It only ever CLEARS, never rewrites.** An empty region is honest — the row's
own prefix is a language code with no country attached, which is a fact, not a
gap. Guessing a *different* country would repeat the original mistake. The owner
put it exactly right: "better to have no region than lump everything under
Germany."

Rows whose prefix is not a recognised locale code (``MULTI``, ``4K``, none) are
untouched: those genuinely have no locale of their own, and inheriting a
sibling's region is the intended behaviour.

Idempotency
-----------
``needs_run`` compares ``config.bad_region_cleanup_version`` against
``CURRENT_VERSION``. An interrupted or crashing run leaves the version unbumped
so the next launch restarts it; already-committed batches are durable, and
because the pass only clears contradictions it converges — a re-run over
already-cleaned rows finds nothing to do.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from loguru import logger

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database

# Bump to re-run the cleanup for all users on next launch.
# History:
#   1 — initial sweep: clear detected_region wherever it contradicts the row's
#       own detected_prefix, and drop the region tag that was derived from it.
#   2 — widen the platform pass to the FULL prefix-group vocabulary and add the
#       name-token arbiter. v1 used channel_name_utils.PLATFORM_CODES (11
#       streaming brands), but the tag system classifies platforms from
#       config.BASE_PLATFORM_GROUPS — which is far larger and includes "SC".
#       That gap left "4K-SC - Ballerina (2025)" (category "|SCA| NORDIC FILMS
#       4K") carrying region ES, tagged Spanish, on a precise tmdb content_key.
CURRENT_VERSION: int = 2

_BATCH = 2000


class BadRegionCleanupTask:
    """Clear mislabelled ``detected_region`` values and their derived region tags."""

    id: str = "bad_region_cleanup"
    label: str = "Correcting mislabelled regions"

    def __init__(self, db: "Database") -> None:
        """
        Args:
            db: Database instance.
        """
        self._db = db

    def needs_run(self, config: "Config") -> bool:
        """Return True when the cleanup has not yet completed for this version.

        Args:
            config: The application Config instance.

        Returns:
            True when ``config.bad_region_cleanup_version`` is behind
            ``CURRENT_VERSION``.
        """
        stored = getattr(config, "bad_region_cleanup_version", 0)
        return stored < CURRENT_VERSION

    def run(
        self,
        progress_cb: Callable[[int, int], None],
        is_cancelled: Callable[[], bool],
        config: "Config | None" = None,
    ) -> None:
        """Clear every contradicting region, in committed batches.

        Runs on a **worker thread** (called by ``MigrationManager``). Exceptions
        propagate so the manager leaves the version unbumped and the task
        retries next launch (#364 crash-retry semantics).

        Args:
            progress_cb: ``(done, total)`` called after each batch commit.
            is_cancelled: Returns True when the manager has been asked to stop.
            config: Unused; accepted for forward-compat with the manager's
                keyword call.
        """
        from metatv.core.database import ChannelDB
        from metatv.core.repositories.channel import _contradicts_own_locale

        logger.info(
            "BadRegionCleanupTask: scanning for regions that contradict their "
            "own locale prefix (version={})", CURRENT_VERSION,
        )

        with self._db.session_scope() as session:
            candidates = (
                session.query(ChannelDB.id, ChannelDB.detected_prefix,
                              ChannelDB.detected_region, ChannelDB.category,
                              ChannelDB.name)
                .filter(ChannelDB.detected_region.isnot(None))
                .filter(ChannelDB.detected_region != "")
                .filter(ChannelDB.detected_prefix.isnot(None))
                .filter(ChannelDB.detected_prefix != "")
                .all()
            )

        # Decided in Python, not SQL: the predicates consult CODE_FACETS and the
        # category decomposition to ask what a row's OWN fields imply, neither of
        # which is expressible as a join.
        doomed = [
            (cid, region)
            for cid, prefix, region, _cat, _name in candidates
            if _contradicts_own_locale(prefix, region)
        ]
        doomed += self._unsupported_platform_regions(candidates, config)
        total = len(doomed)
        logger.info(
            "BadRegionCleanupTask: {:,} of {:,} regioned rows contradict their "
            "own prefix", total, len(candidates),
        )
        if not total:
            progress_cb(0, 0)
            return

        done = 0
        for start in range(0, total, _BATCH):
            if is_cancelled():
                logger.info(
                    "BadRegionCleanupTask: cancelled at {}/{}", done, total
                )
                return
            chunk = doomed[start:start + _BATCH]
            self._clear_batch(chunk)
            done += len(chunk)
            progress_cb(done, total)

        logger.info("BadRegionCleanupTask: cleared {:,} mislabelled regions", done)

    @staticmethod
    def _unsupported_platform_regions(candidates, config) -> list[tuple[str, str]]:
        """Platform-prefixed rows whose region nothing on the row supports.

        ``A+``/``D+``/``NF`` are PLATFORM codes, not locales, so
        ``_contradicts_own_locale`` has nothing to contradict and leaves them
        alone — yet they were inheriting a sibling's region just the same. The
        owner: "clearly A+, D+ etc are mostly US, but better to have no region
        than lump everything under Germany."

        The arbiter is the row's own category, read through
        :func:`~metatv.core.tag_decomposer.region_code_from_category` — the same
        extraction ingestion uses, so this cannot drift from it. That
        distinction is real and load-bearing in the owner's library:

          * ``D+`` under ``"UK| DISCOVERY +"`` → UK, self-evident, KEPT
          * ``PRIME`` under ``"US| PRIME"``    → US, self-evident, KEPT
          * ``A+`` under ``"APPLE+ MOVIES"``   → ISR/FR/NL, inherited, CLEARED
          * ``NF`` under ``"|MULTI| NETFLIX"`` → FR/DE,     inherited, CLEARED

        Rows with no locale AND no platform prefix are deliberately untouched:
        those have no evidence of their own, which is exactly the gap sibling
        propagation exists to fill.

        Args:
            candidates: ``(id, prefix, region, category)`` rows.
            config: Live Config for the category decomposition, or None.

        Returns:
            ``(channel_id, region)`` pairs to clear.
        """
        from metatv.core.channel_name_utils import (
            normalize_region_code, parse_channel_name,
        )
        from metatv.core.tag_decomposer import region_code_from_category

        if config is None:
            from metatv.core.config import Config
            config = Config()

        from metatv.core.config import BASE_PLATFORM_GROUPS

        # BASE_PLATFORM_GROUPS' VALUES, not channel_name_utils.PLATFORM_CODES
        # and not the group KEYS. Three distinct things, and picking wrong is
        # silent: PLATFORM_CODES holds 11 streaming brands and missed "SC"
        # entirely (which is what let the Scandinavian Ballerina keep region ES);
        # the keys are human group NAMES ("Apple TV+", "Netflix"), so matching
        # them drops "A+"/"PRIME". The values are the 85 actual prefix tokens,
        # and they are what the tag decomposer classifies platforms from — so
        # the sweep and the tags agree by construction.
        platform_codes = {
            normalize_region_code(token)
            for tokens in BASE_PLATFORM_GROUPS.values()
            for token in tokens
        }

        name_of = {c[0]: c[4] for c in candidates}
        out: list[tuple[str, str]] = []
        for cid, prefix, region, category, _name in candidates:
            if normalize_region_code((prefix or "").strip()) not in platform_codes:
                continue
            wanted = normalize_region_code(region)
            # The NAME's parenthetical suffix, e.g. "SC - Monk (US)". Note
            # ParsedChannel.lang holds that suffix — .region holds the PREFIX —
            # so reading .region here would compare a platform code against a
            # country and wrongly clear 385 rows that state their own country.
            parsed = parse_channel_name(name_of.get(cid, "") or "")
            if normalize_region_code(parsed.lang or "") == wanted:
                continue
            own = region_code_from_category(category, config=config)
            if own and normalize_region_code(own) == wanted:
                continue     # the row's own category says so — keep it
            out.append((cid, region))
        return out

    def _clear_batch(self, chunk: list[tuple[str, str]]) -> None:
        """Clear ``detected_region`` and drop the matching region tag for *chunk*.

        The tag matters as much as the column: the bogus region produced a
        ``region`` facet the user can filter by and that feeds recommendations,
        so leaving it behind would keep the wrong answer visible even after the
        column is honest. Only the tag whose VALUE equals the region being
        cleared is removed — a region tag from any other feeder is untouched.

        Args:
            chunk: ``(channel_id, region_being_cleared)`` pairs.
        """
        from sqlalchemy import update

        from metatv.core.database import ChannelDB, ContentTagDB, TagDB

        from metatv.core.channel_name_utils import CODE_FACETS, normalize_region_code

        ids = [cid for cid, _ in chunk]
        by_region: dict[str, list[str]] = {}
        for cid, region in chunk:
            by_region.setdefault(region, []).append(cid)

        # A region code also implies a LANGUAGE, and the decomposer tagged it —
        # so the owner's English Aladdin carried a "German" language tag purely
        # because it had been handed region DE. Clearing the region without that
        # tag leaves the visible symptom in place: the title still reads German
        # in filters and still feeds recommendations as German.
        #
        # Only dropped when the row's OWN prefix does not also imply that
        # language, so a genuinely bilingual row keeps what it earned.
        lang_by_region: dict[str, set[str]] = {}
        for region in by_region:
            implied = {
                value for facet, value, _c
                in CODE_FACETS.get(normalize_region_code(region), ())
                if facet == "language"
            }
            if implied:
                lang_by_region[region] = implied

        with self._db.session_scope() as session:
            session.execute(
                update(ChannelDB)
                .where(ChannelDB.id.in_(ids))
                .values(detected_region=None)
            )
            for region, cids in by_region.items():
                tag_ids = [
                    row[0] for row in session.query(TagDB.id)
                    .filter(TagDB.type == "region", TagDB.value == region).all()
                ]
                if not tag_ids:
                    continue
                (
                    session.query(ContentTagDB)
                    .filter(ContentTagDB.channel_id.in_(cids))
                    .filter(ContentTagDB.tag_id.in_(tag_ids))
                    .delete(synchronize_session=False)
                )

            # …and the language tag that region implied.
            for region, languages in lang_by_region.items():
                cids = by_region[region]
                keepers = {
                    cid for cid, in session.query(ChannelDB.id)
                    .filter(ChannelDB.id.in_(cids))
                    .filter(ChannelDB.detected_prefix.in_(
                        [c for c, entries in CODE_FACETS.items()
                         if any(f == "language" and v in languages
                                for f, v, _ in entries)]
                    )).all()
                }
                targets = [c for c in cids if c not in keepers]
                if not targets:
                    continue
                lang_ids = [
                    row[0] for row in session.query(TagDB.id)
                    .filter(TagDB.type == "language", TagDB.value.in_(languages)).all()
                ]
                if not lang_ids:
                    continue
                (
                    session.query(ContentTagDB)
                    .filter(ContentTagDB.channel_id.in_(targets))
                    .filter(ContentTagDB.tag_id.in_(lang_ids))
                    .delete(synchronize_session=False)
                )

    def on_completed(self, config: "Config") -> None:
        """Persist the version so the sweep does not repeat.

        Args:
            config: The application Config instance.
        """
        config.bad_region_cleanup_version = CURRENT_VERSION
        config.save()
        logger.info(
            "BadRegionCleanupTask: complete (version={})", CURRENT_VERSION
        )
