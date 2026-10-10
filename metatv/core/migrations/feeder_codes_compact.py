"""Convert content_tags.feeders from JSON names to codes (tag_source.FEEDER_CODES).

New writes already store codes; this rewrites the existing rows so the saving
applies to the whole table. Batches by channel_key range — one short UPDATE
each, so other writers are never held off for long — and touches only rows
still in the JSON form, so an interrupted run simply resumes.

The file only SHRINKS after a VACUUM; until then SQLite reuses the freed pages
for new data, so the database stops growing for a while instead.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from loguru import logger
from sqlalchemy import text

from metatv.core.tag_source import FEEDER_CODES

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database

CURRENT_VERSION: int = 1
_SPAN = 20000      # channel_keys per batch

_CASE = "CASE j.value " + " ".join(
    f"WHEN '{name}' THEN '{code}'" for name, code in sorted(FEEDER_CODES.items())
) + " ELSE j.value END"


class FeederCodesCompactTask:
    """Rewrite legacy JSON feeder lists as compact codes."""

    id: str = "feeder_codes_compact"
    label: str = "Compacting tag data"

    def __init__(self, db: "Database") -> None:
        self._db = db

    def needs_run(self, config: "Config") -> bool:
        if getattr(config, "feeder_codes_compact_version", 0) >= CURRENT_VERSION:
            return False
        try:
            with self._db.engine.connect() as conn:
                return bool(conn.execute(text(
                    "SELECT EXISTS(SELECT 1 FROM content_tags WHERE feeders LIKE '[%')")).scalar())
        except Exception:
            logger.exception("feeder_codes_compact: could not check; skipping")
            return False

    def run(self, progress_cb: Callable[[int, int], None],
            is_cancelled: Callable[[], bool], config: "Config | None" = None) -> None:
        with self._db.engine.connect() as conn:
            top = conn.execute(text("SELECT COALESCE(MAX(channel_key), 0) FROM content_tags")).scalar()
        converted, start = 0, 0
        progress_cb(0, top)
        while start <= top and not is_cancelled():
            with self._db.session_scope() as session:
                result = session.execute(text(
                    "UPDATE content_tags SET feeders = ("
                    f"  SELECT group_concat({_CASE}, ',') FROM json_each(content_tags.feeders) j)"
                    " WHERE channel_key >= :a AND channel_key < :b AND feeders LIKE '[%'"
                    " AND json_valid(feeders)"), {"a": start, "b": start + _SPAN})
                converted += result.rowcount or 0
            start += _SPAN
            progress_cb(min(start, top), top)
        logger.info("feeder_codes_compact: converted {:,} tag link(s) to feeder codes", converted)

    def on_completed(self, config: "Config") -> None:
        config.feeder_codes_compact_version = CURRENT_VERSION
        config.save()
