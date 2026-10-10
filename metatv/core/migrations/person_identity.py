"""One ``person`` tag per identity; roles on the link (owner, 2026-10-10).

Credits were stored as separate ``cast`` and ``director`` tags, and names read off
a channel title as a third ``person`` tag — so one human was up to three tags,
and a recipe (which ANDs facets) picking two of them matched only the overlap.
Now every name is ONE ``person`` tag and each link carries its role bits
(``tag_source.ROLE_BITS``: acting, directing; none = named in the title).

This folds the existing links, batch by batch over channel_key ranges so other
writers are never held off long:

* every ``cast``/``director`` value gets its ``person`` tag (created if missing);
* each old link becomes a person link with the role bit; where the channel
  already has that person (both roles, or named in the title too) the bits and
  feeders merge into the one link, and a credit's character/billing is kept;
* a person name ending in a billing qualifier ("… Uncredited") merges into the
  clean name;
* the old ``cast``/``director`` tags are deleted last.

Self-limiting: it runs while any ``cast``/``director`` tag exists.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from loguru import logger
from sqlalchemy import text

from metatv.core.channel_name_utils import CREDIT_QUALIFIER_WORDS
from metatv.core.tag_source import ROLE_BITS

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database

_SPAN = 20000      # channel_keys per batch

# Merge an incoming link into an existing one: OR the role bits, keep the
# first detail/ord, append any feeder code the stored list lacks.
_UPSERT = (
    " ON CONFLICT (channel_key, tag_id, source) DO UPDATE SET"
    " qualifier = COALESCE(content_tags.qualifier, 0) | COALESCE(excluded.qualifier, 0),"
    " detail = COALESCE(content_tags.detail, excluded.detail),"
    " ord = COALESCE(content_tags.ord, excluded.ord),"
    " feeders = CASE WHEN excluded.feeders IS NULL OR excluded.feeders = '' THEN content_tags.feeders"
    "  WHEN content_tags.feeders IS NULL OR content_tags.feeders = '' THEN excluded.feeders"
    "  WHEN (',' || content_tags.feeders || ',') LIKE ('%,' || excluded.feeders || ',%')"
    "  THEN content_tags.feeders ELSE content_tags.feeders || ',' || excluded.feeders END"
)


def _clean(value: str) -> str:
    words = value.split()
    while words and words[-1].upper() in CREDIT_QUALIFIER_WORDS:
        words.pop()
    return " ".join(words)


class PersonIdentityTask:
    """Fold cast/director tags into one person tag with role bits."""

    id: str = "person_identity"
    label: str = "Merging cast and directors into one person each"

    def __init__(self, db: "Database") -> None:
        self._db = db

    def needs_run(self, config: "Config") -> bool:
        try:
            with self._db.engine.connect() as conn:
                return bool(conn.execute(text(
                    "SELECT EXISTS(SELECT 1 FROM tags WHERE type IN ('cast', 'director'))"
                    " OR EXISTS(SELECT 1 FROM tags WHERE type = 'person' AND ("
                    + " OR ".join(f"upper(value) LIKE '% {w}'" for w in sorted(CREDIT_QUALIFIER_WORDS))
                    + "))")).scalar())
        except Exception:
            logger.exception("person_identity: could not check; skipping")
            return False

    def run(self, progress_cb: Callable[[int, int], None],
            is_cancelled: Callable[[], bool], config: "Config | None" = None) -> None:
        self._clean_qualified_names()
        with self._db.session_scope() as session:
            session.execute(text(
                "INSERT INTO tags (type, value) SELECT DISTINCT 'person', o.value FROM tags o"
                " WHERE o.type IN ('cast', 'director') AND NOT EXISTS"
                " (SELECT 1 FROM tags p WHERE p.type = 'person' AND p.value = o.value)"))
        with self._db.engine.connect() as conn:
            top = conn.execute(text("SELECT COALESCE(MAX(channel_key), 0) FROM content_tags")).scalar()
        moved, start = 0, 0
        progress_cb(0, top)
        while start <= top and not is_cancelled():
            rng = {"a": start, "b": start + _SPAN}
            with self._db.session_scope() as session:
                # Cast first, so a credit's character/billing wins the merge.
                for kind in ("cast", "director"):
                    moved += session.execute(text(
                        "INSERT INTO content_tags"
                        " (channel_key, tag_id, source, feeders, detail, ord, qualifier)"
                        f" SELECT ct.channel_key, p.id, ct.source, ct.feeders, ct.detail, ct.ord, {ROLE_BITS[kind]}"
                        " FROM content_tags ct JOIN tags o ON o.id = ct.tag_id AND o.type = :kind"
                        " JOIN tags p ON p.type = 'person' AND p.value = o.value"
                        " WHERE ct.channel_key >= :a AND ct.channel_key < :b AND true" + _UPSERT),
                        {**rng, "kind": kind}).rowcount or 0
                session.execute(text(
                    "DELETE FROM content_tags WHERE channel_key >= :a AND channel_key < :b"
                    " AND tag_id IN (SELECT id FROM tags WHERE type IN ('cast', 'director'))"), rng)
            start += _SPAN
            progress_cb(min(start, top), top)
        if is_cancelled():
            return
        with self._db.session_scope() as session:
            session.execute(text(
                "DELETE FROM tags WHERE type IN ('cast', 'director') AND NOT EXISTS"
                " (SELECT 1 FROM content_tags ct WHERE ct.tag_id = tags.id)"))
        logger.info("person_identity: folded {:,} credit link(s) into person tags", moved)

    def _clean_qualified_names(self) -> None:
        """'Cillian Murphy Uncredited' → 'Cillian Murphy' (merging into it)."""
        with self._db.session_scope() as session:
            rows = session.execute(text("SELECT id, value FROM tags WHERE type = 'person'")).all()
            for pid, value in rows:
                clean = _clean(value)
                if clean == value or not clean:
                    continue
                session.execute(text(
                    "INSERT INTO tags (type, value) SELECT 'person', :v WHERE NOT EXISTS"
                    " (SELECT 1 FROM tags WHERE type = 'person' AND value = :v)"), {"v": clean})
                session.execute(text(
                    "INSERT INTO content_tags (channel_key, tag_id, source, feeders, detail, ord, qualifier)"
                    " SELECT ct.channel_key, (SELECT id FROM tags WHERE type = 'person' AND value = :v),"
                    " ct.source, ct.feeders, ct.detail, ct.ord, ct.qualifier"
                    " FROM content_tags ct WHERE ct.tag_id = :pid AND true" + _UPSERT),
                    {"v": clean, "pid": pid})
                session.execute(text("DELETE FROM content_tags WHERE tag_id = :pid"), {"pid": pid})
                session.execute(text("DELETE FROM tags WHERE id = :pid"), {"pid": pid})

    def on_completed(self, config: "Config") -> None:
        """Nothing to stamp — needs_run() is the presence of a cast/director tag."""
