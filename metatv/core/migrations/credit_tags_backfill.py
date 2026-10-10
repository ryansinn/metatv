"""Backfill: cast, directors and alternate titles as tags.

Credits used to live only as text inside each title's metadata (a JSON cast
list, a comma-separated director string) — the same name spelled out once per
film, searchable only by text matching. New saves now write them as tags
(``tag_decomposer.credit_tags`` — one vocabulary row per person, a link per
channel carrying billing order and character). This sweep converts what is
already stored, plus any ``metadata.alt_titles`` into ``title`` tags.

Reads by keyset on ``channel_key`` and writes one bulk upsert per batch, so it
runs in the background without one long transaction. The links carry the
persistent ``metadata_credits`` / ``provider_detail`` feeders, so a later
re-tag never deletes them.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Callable

from loguru import logger
from sqlalchemy import text

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database

#: Bumped when this should sweep again.
CURRENT_VERSION: int = 1

_BATCH = 2000

_HAS_CREDITS = (
    "((m.\"cast\" IS NOT NULL AND m.\"cast\" NOT IN ('', '[]')) "
    " OR (m.director IS NOT NULL AND m.director != '') "
    " OR (m.alt_titles IS NOT NULL AND m.alt_titles NOT IN ('', '[]')))"
)


def _loads(value):
    if not value:
        return []
    try:
        return json.loads(value) if isinstance(value, str) else value
    except (ValueError, TypeError):
        return []


class CreditTagsBackfillTask:
    """Convert stored cast/director/alternate titles into tags."""

    id: str = "credit_tags_backfill"
    label: str = "Indexing cast, directors and titles"

    def __init__(self, db: "Database") -> None:
        self._db = db

    def needs_run(self, config: "Config") -> bool:
        """True until this version has run over a library that has credits."""
        if getattr(config, "credit_tags_backfill_version", 0) >= CURRENT_VERSION:
            return False
        try:
            with self._db.engine.connect() as conn:
                return bool(conn.execute(text(
                    "SELECT EXISTS(SELECT 1 FROM channels c JOIN metadata m "
                    f"ON m.id = c.metadata_id WHERE {_HAS_CREDITS})"
                )).scalar())
        except Exception:
            logger.exception("credit_tags_backfill: could not check; skipping")
            return False

    def run(self, progress_cb: Callable[[int, int], None],
            is_cancelled: Callable[[], bool], config: "Config | None" = None) -> None:
        """Convert every channel's stored credits, batch by batch."""
        from metatv.core.repositories.tag import TagRepository
        from metatv.core.tag_decomposer import credit_tags, title_tags

        with self._db.engine.connect() as conn:
            total = conn.execute(text(
                "SELECT COUNT(*) FROM channels c JOIN metadata m "
                f"ON m.id = c.metadata_id WHERE {_HAS_CREDITS}")).scalar() or 0
        done, last_key, written = 0, -1, 0
        progress_cb(0, total)
        while not is_cancelled():
            with self._db.engine.connect() as conn:
                rows = conn.execute(text(
                    "SELECT c.channel_key, c.id, m.\"cast\", m.director, m.alt_titles "
                    "FROM channels c JOIN metadata m ON m.id = c.metadata_id "
                    f"WHERE c.channel_key > :k AND {_HAS_CREDITS} "
                    "ORDER BY c.channel_key LIMIT :n"), {"k": last_key, "n": _BATCH}).all()
            if not rows:
                break
            mapping = {}
            for key, cid, cast, director, alt in rows:
                items = credit_tags(_loads(cast), director) + title_tags(_loads(alt))
                if items:
                    mapping[cid] = items
                last_key = key
            if mapping:
                with self._db.session_scope() as session:
                    TagRepository(session).set_content_tags_bulk(mapping)
                written += sum(len(v) for v in mapping.values())
            done += len(rows)
            progress_cb(done, total)
        logger.info("credit_tags_backfill: {:,} channel(s), {:,} credit/title tag link(s)",
                    done, written)

    def on_completed(self, config: "Config") -> None:
        """Stamp the version so this stops checking on every launch."""
        config.credit_tags_backfill_version = CURRENT_VERSION
        config.save()
