"""Merge case-variant tag rows, and delete the ones nothing points at.

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

Two passes, in this order:

1. **Merge.** For each ``(type, casefolded value)`` group, keep the row with the
   most ``content_tags`` — ties broken by the lowest id so the result is stable
   — repoint every other row's ``content_tags`` at it, then delete the losers.
   The SURVIVING row keeps its own display text, so "Drama" stays "Drama".

2. **Prune.** Delete tags no ``content_tags`` row references at all. These are
   ordinary debris: ``set_content_tags`` replaces a channel's generated tags, so
   a genre that stops applying leaves its row behind with nothing attached.

Both are safe to re-run: the merge is a no-op once each group has one row, and
the prune only ever removes rows with a zero reference count.
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
    """Collapse case-variant tags and drop tags nothing references."""

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
        """Merge variants, then prune orphans. Runs on a worker thread.

        Args:
            progress_cb: ``(done, total)`` after each phase.
            is_cancelled: Returns True when asked to stop.
            config: Stamped with ``CURRENT_VERSION`` on success.
        """
        merged = pruned = 0
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
                # Repoint, skipping any pair the keeper already has — the unique
                # constraint is on (channel_id, tag_id, source).
                session.execute(text(
                    f"UPDATE OR IGNORE content_tags SET tag_id = {int(keep_id)} "
                    f"WHERE tag_id IN ({placeholders})"
                ))
                session.execute(text(
                    f"DELETE FROM content_tags WHERE tag_id IN ({placeholders})"
                ))
                session.execute(text(f"DELETE FROM tags WHERE id IN ({placeholders})"))
                merged += len(losers)
            session.commit()
            progress_cb(1, 2)

            result = session.execute(text(
                "DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM content_tags)"
            ))
            pruned = result.rowcount or 0
            session.commit()
            progress_cb(2, 2)

        logger.info(
            "tag_case_merge: merged {} duplicate tag row(s), pruned {} unreferenced",
            merged, pruned,
        )

    def on_completed(self, config: "Config") -> None:
        """Stamp the version so this does not re-run every launch.

        Args:
            config: Saved with the new version.
        """
        config.tag_case_merge_version = CURRENT_VERSION
        config.save()
