"""Drop the old credit TEXT once every credit lives as tags.

Credits are read only through ``core.credits`` (cast / director tags). This
task retires ``metadata.cast`` / ``metadata.director`` (and the legacy
``actors`` and the interim ``alt_titles``, already title tags):

1. Re-convert every credited channel from the text, with the corrected writer
   (a name credited twice keeps its FIRST billing position).
2. Verify: every channel that has credit text has credit tags. If not, stop
   with an error and clear NOTHING — the text is the only way to rebuild them.
3. Clear the text in short batches.

The space comes back to SQLite's free list at once; the FILE shrinks only
after a VACUUM.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from loguru import logger
from sqlalchemy import text

from metatv.core.migrations.credit_tags_backfill import _HAS_CREDITS, CreditTagsBackfillTask

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database

_SPAN = 20000

_HAS_TEXT = ("(\"cast\" IS NOT NULL OR director IS NOT NULL OR actors IS NOT NULL "
             "OR alt_titles IS NOT NULL)")


class CreditsTextDropTask:
    """Re-convert, verify, then clear the metadata credit text."""

    id: str = "credits_text_drop"
    label: str = "Finishing the cast & title index"

    def __init__(self, db: "Database") -> None:
        self._db = db

    def needs_run(self, config: "Config") -> bool:
        """True while any metadata row still carries credit text. Self-limiting:
        once cleared there is nothing left, so no version stamp is needed."""
        try:
            with self._db.engine.connect() as conn:
                return bool(conn.execute(text(
                    f"SELECT EXISTS(SELECT 1 FROM metadata WHERE {_HAS_TEXT})")).scalar())
        except Exception:
            logger.exception("credits_text_drop: could not check; skipping")
            return False

    def run(self, progress_cb: Callable[[int, int], None],
            is_cancelled: Callable[[], bool], config: "Config | None" = None) -> None:
        # 1. Re-convert with the corrected writer (first credit wins).
        CreditTagsBackfillTask(self._db).run(progress_cb, is_cancelled, config)
        if is_cancelled():
            return
        # 2. Verify before touching anything irreversible.
        with self._db.engine.connect() as conn:
            missing = conn.execute(text(
                "SELECT COUNT(*) FROM channels c JOIN metadata m ON m.id = c.metadata_id "
                f"WHERE {_HAS_CREDITS} AND NOT EXISTS (SELECT 1 FROM content_tags ct "
                "JOIN tags t ON t.id = ct.tag_id WHERE ct.channel_key = c.channel_key "
                "AND t.type IN ('cast', 'director', 'title'))")).scalar() or 0
            top = conn.execute(text("SELECT COALESCE(MAX(rowid), 0) FROM metadata")).scalar()
        if missing:
            raise RuntimeError(
                f"credits_text_drop: {missing} channel(s) have credit text but no credit "
                "tags — keeping the text; nothing was cleared")
        # 3. Clear, in short batches.
        cleared, start = 0, 0
        while start <= top and not is_cancelled():
            with self._db.session_scope() as session:
                cleared += session.execute(text(
                    "UPDATE metadata SET \"cast\" = NULL, director = NULL, actors = NULL, "
                    f"alt_titles = NULL WHERE rowid >= :a AND rowid < :b AND {_HAS_TEXT}"),
                    {"a": start, "b": start + _SPAN}).rowcount or 0
            start += _SPAN
        logger.info("credits_text_drop: cleared credit text from {:,} metadata row(s)", cleared)

    def on_completed(self, config: "Config") -> None:
        """Nothing to stamp — :meth:`needs_run` reads the data itself."""
