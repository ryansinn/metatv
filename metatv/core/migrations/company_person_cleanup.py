"""Migration task: companies filed as people (ledger F59).

A series' metadata often puts the production company in the director field
("A+E Studios" directing YOU, "CBS Television Studios", "Sony Pictures
Television"), and ``tag_decomposer.credit_tags`` filed every name there as a
``person``. Measured on the owner's library 2026-11-01: 3,139 person tags
carried a company word and 317 of their links were live, all from the
``metadata_credits`` feeder with the director role. The writer skips them now
(``content_labels.looks_like_company``); this removes the ones already stored —
generated data, never the user's.

Deletes each such tag with its links and aliases. Idempotent: a second run
finds nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from loguru import logger
from sqlalchemy import text

from metatv.core.content_labels import looks_like_company
from metatv.core.migrations.base import VersionGatedTask
from metatv.core.tag_source import PERSON_TYPE

if TYPE_CHECKING:
    from metatv.core.config import Config

# Bump to re-run for every user on next launch.
#   1 — initial sweep (F59).
#   2 — plurals/Spanish ("Entertainments", "Estudios") and dash compounds
#       ("W-Pictures"): 8 survivors of v1 on the owner's library.
CURRENT_VERSION: int = 2

_BATCH = 500


class CompanyPersonCleanupTask(VersionGatedTask):
    """Delete person tags whose name is a company, with their links and aliases."""

    id: str = "company_person_cleanup"
    label: str = "Removing studios listed as people"

    VERSION_FIELD: str = "company_person_cleanup_version"
    CURRENT_VERSION: int = CURRENT_VERSION

    def run(self, progress_cb: Callable[[int, int], None],
            is_cancelled: Callable[[], bool], config: "Config | None" = None) -> None:
        with self._db.engine.connect() as conn:
            doomed = [tid for tid, value in conn.execute(
                text("SELECT id, value FROM tags WHERE type = :t"), {"t": PERSON_TYPE})
                if looks_like_company(value)]
        total = len(doomed)
        logger.info("company_person_cleanup: {:,} company name(s) stored as people", total)
        progress_cb(0, total)
        for start in range(0, total, _BATCH):
            if is_cancelled():
                return
            ids = doomed[start:start + _BATCH]
            marks = ",".join(str(int(i)) for i in ids)
            with self._db.session_scope() as session:
                for table, col in (("tag_aliases", "tag_id"), ("content_tags", "tag_id"), ("tags", "id")):
                    session.execute(text(f"DELETE FROM {table} WHERE {col} IN ({marks})"))
            progress_cb(min(start + _BATCH, total), total)
        from metatv.core.repositories.tag import _clear_tag_cache
        _clear_tag_cache()   # deleted ids must not be handed out from the cache
        logger.info("company_person_cleanup: removed {:,}", total)
