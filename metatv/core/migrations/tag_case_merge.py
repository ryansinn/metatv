"""Merge case-variant tag rows into the most-used spelling.

``get_or_create_tag`` matched ``(type, value)`` exactly, so ``"Drama"``,
``"DRAMA"`` and ``"drama"`` became three rows. Measured on the owner's library:

    genre tags                          654
      case/space-variant collisions      27   (36 surplus rows)
      tags with ZERO channels           288   (49% of the low-count tail)

Owner: *"DRAMA and Drama shelves are separate."* They were — though for `drama`
specifically the duplicates carried **no channels at all**, so what showed was
an empty shelf beside a full one rather than split content. Exactly one
collision genuinely split content: ``Talk Show تاک شو`` (10) against
``TALK SHOW تاک شو`` (2).

One pass: for each ``(type, casefolded value)`` group, keep the row with the
most ``content_tags`` — ties broken by the lowest id so the result is stable —
repoint every other row's ``content_tags`` at it, then delete the losers. The
SURVIVING row keeps its own display text, so "Drama" stays "Drama". Safe to
re-run: a no-op once each group has one row.

TAG-2 (2026-09): this task USED to end with a second, unscoped pass —

    DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM content_tags)

— every tag with zero links, not merely the ones THIS merge just orphaned.
Those are already gone by that point: the per-group loop above deletes its
own losers explicitly, right after repointing (or absorbing, see ``run()``)
their ``content_tags``, whether or not they carried any links to begin with.
So the second pass was never load-bearing for the merge; it was a standalone
"delete anything currently unreferenced" sweep riding along on this task's
version gate. That was harmless while ``tags`` held only observed provider
values, where an unlinked row is genuinely dead debris. It stops being
harmless the moment ``tags`` carries curated vocabulary a merge never touched
(CONCEPT-1: 368 alias rows resolving to ~39 concepts via a prospective
``concept_id`` column) — a concept with no CURRENTLY linked channel is not
garbage, and this statement would delete the curation itself, silently, on a
task that runs at every launch. Removed. Whether a standalone,
deliberately-scoped dead-vocabulary sweep is still wanted is an open question
tracked in docs/REFACTOR_PLAN.md, not decided here.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Callable

from loguru import logger
from sqlalchemy import text

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database

#: Bumped when this task should run again over an already-migrated library.
CURRENT_VERSION: int = 1


class TagCaseMergeTask:
    """Collapse case-variant tag rows into the most-used spelling."""

    id: str = "tag_case_merge"
    label: str = "Tidying duplicate genre labels"

    def __init__(self, db: "Database") -> None:
        """
        Args:
            db: Database instance.
        """
        self._db = db

    def needs_run(self, config: "Config") -> bool:
        """Return True until this library has been merged at this version.

        Args:
            config: The application Config.

        Returns:
            True when the stored version is behind ``CURRENT_VERSION``.
        """
        return getattr(config, "tag_case_merge_version", 0) < CURRENT_VERSION

    def run(
        self,
        progress_cb: Callable[[int, int], None],
        is_cancelled: Callable[[], bool],
        config: "Config | None" = None,
    ) -> None:
        """Merge case-variant tag rows into the most-used spelling. Runs on a worker thread.

        Args:
            progress_cb: ``(done, total)`` — total is 1, called once at the end.
            is_cancelled: Returns True when asked to stop.
            config: Stamped with ``CURRENT_VERSION`` on success.
        """
        merged = 0
        with self._db.session_scope() as session:
            rows = session.execute(text(
                "SELECT t.id, t.type, t.value, "
                "       (SELECT count(*) FROM content_tags ct WHERE ct.tag_id = t.id) "
                "  FROM tags t"
            )).all()

            groups: dict[tuple, list] = defaultdict(list)
            for tid, ttype, value, n in rows:
                groups[(ttype, (value or "").strip().casefold())].append((tid, n))

            for (_ttype, _key), members in groups.items():
                if is_cancelled():
                    return
                if len(members) < 2:
                    continue
                # Most-referenced wins; lowest id breaks a tie so the outcome
                # does not depend on row order.
                keep_id, _ = max(members, key=lambda m: (m[1], -m[0]))
                losers = [tid for tid, _ in members if tid != keep_id]
                if not losers:
                    continue
                placeholders = ",".join(str(int(i)) for i in losers)
                # Repoint every loser's content_tags at the keeper. content_tags'
                # primary key is the composite (channel_key, tag_id, source)
                # (DB-9), so a channel that already carries BOTH the keeper's
                # and a loser's tag under the same source already owns the row
                # this UPDATE would target — that's a PK collision, and
                # OR IGNORE absorbs it by leaving the loser's row untouched
                # instead of raising.
                session.execute(text(
                    f"UPDATE OR IGNORE content_tags SET tag_id = {int(keep_id)} "
                    f"WHERE tag_id IN ({placeholders})"
                ))
                # Whatever OR IGNORE could not move is, by construction, a
                # duplicate of a link the channel already has via the keeper —
                # never a link that would otherwise be lost — so delete it
                # unconditionally, then the now fully-unreferenced loser tag
                # rows themselves (regardless of whether they carried any
                # content_tags to begin with — see module docstring on why a
                # second, unscoped prune pass used to sit here and no longer
                # does). See
                # test_a_channel_carrying_both_variants_does_not_duplicate_or_lose_its_link.
                session.execute(text(
                    f"DELETE FROM content_tags WHERE tag_id IN ({placeholders})"
                ))
                session.execute(text(f"DELETE FROM tags WHERE id IN ({placeholders})"))
                merged += len(losers)
            session.commit()

        progress_cb(1, 1)
        logger.info("tag_case_merge: merged {} duplicate tag row(s)", merged)

    def on_completed(self, config: "Config") -> None:
        """Stamp the version so this does not re-run every launch.

        Args:
            config: Saved with the new version.
        """
        config.tag_case_merge_version = CURRENT_VERSION
        config.save()
