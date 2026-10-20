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
#: 2 (2026-10-20): also folds vocabulary — genre spellings in other languages
#: and scripts onto canonical genres (``filter_utils.resolve_genres``), and
#: language codes stored as regions onto the language facet
#: (``region_codes.LANGUAGE_ONLY_CODES``). Owner: "dozens of arabic drama and
#: comedy"; "Hindi isn't a region, it's a language".
CURRENT_VERSION: int = 2


class TagCaseMergeTask:
    """Collapse case-variant tag rows into the most-used spelling."""

    id: str = "tag_case_merge"
    label: str = "Tidying duplicate genre and region labels"

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
                for tid, _ in members:
                    if tid != keep_id:
                        _fold_tag(session, tid, [keep_id])
                        merged += 1
            if is_cancelled():
                return
            merged += _fold_vocabulary(session)
            _refold_detected_genres(session)
            session.commit()
        progress_cb(1, 1)
        logger.info("tag_case_merge: folded {} tag row(s)", merged)

    def on_completed(self, config: "Config") -> None:
        """Stamp the version so this does not re-run every launch.

        Args:
            config: Saved with the new version.
        """
        config.tag_case_merge_version = CURRENT_VERSION
        config.save()


def _fold_tag(session, loser_id: int, keep_ids: list[int], *, delete: bool = True) -> None:
    """Move every link on tag *loser_id* to each of *keep_ids*, then delete it.

    ``delete=False`` copies without removing — for a tag that is itself one of
    its own targets (case-insensitively "DRAMA" resolves to its own row).

    The one link-moving step for both folds. ``content_tags``' primary key is
    ``(channel_key, tag_id, source)`` (DB-9), so a channel that already carries
    a keeper under the same source already owns the row a move would create;
    ``INSERT OR IGNORE`` absorbs that collision, and the loser's links are then
    deleted unconditionally — a link it held is either moved or already
    present on the keeper, never lost
    (test_a_channel_carrying_both_variants_does_not_duplicate_or_lose_its_link).
    """
    for keep_id in keep_ids:
        session.execute(text(
            "INSERT OR IGNORE INTO content_tags "
            "  (channel_key, tag_id, source, feeders, detail, ord, qualifier) "
            "SELECT channel_key, :keep, source, feeders, detail, ord, qualifier "
            "  FROM content_tags WHERE tag_id = :loser"
        ), {"keep": int(keep_id), "loser": int(loser_id)})
    if delete:
        session.execute(text("DELETE FROM content_tags WHERE tag_id = :t"), {"t": int(loser_id)})
        session.execute(text("DELETE FROM tags WHERE id = :t"), {"t": int(loser_id)})


def _fold_vocabulary(session) -> int:
    """Fold alias genres onto canonical ones, and language codes off the region facet.

    Uses the INGESTION resolvers, so a library already tagged ends where a
    fresh import now lands. Only folds whose every target is canonical; a
    string the resolver cannot place is left exactly as it was.
    """
    from metatv.core.config import BASE_PREFIX_GROUPS
    from metatv.core.filter_utils import KNOWN_GENRES
    from metatv.core.genre_words import resolve_genres
    from metatv.core.region_codes import LANGUAGE_ONLY_CODES
    from metatv.core.repositories.tag import TagRepository

    # The language a code belongs to is its language GROUP (HI -> "Indian"),
    # exactly what the decomposer tags at ingestion.
    group_of = {c.upper(): g for g, codes in BASE_PREFIX_GROUPS.items() for c in codes}

    def tag_id(ttype: str, value: str) -> int:      # the one tag-creation chokepoint
        return TagRepository(session).get_or_create_tag(ttype, value).id

    folded = 0
    for tid, ttype, value in session.execute(text(
            "SELECT id, type, value FROM tags WHERE type IN ('genre', 'region')")).all():
        if ttype == "genre":
            targets = resolve_genres(value)
            if targets == [value] or not all(g in KNOWN_GENRES for g in targets):
                continue
            keep = [tag_id("genre", g) for g in targets]
        elif value.upper() in LANGUAGE_ONLY_CODES and value.upper() in group_of:
            keep = [tag_id("language", group_of[value.upper()])]
        else:
            continue
        others = [k for k in keep if k != tid]
        if tid in keep:          # its own target: add the others, never delete it
            if others:
                _fold_tag(session, tid, others, delete=False)
            continue
        _fold_tag(session, tid, others)
        folded += 1
    return folded


def _refold_detected_genres(session) -> None:
    """Re-resolve the stored ``detected_genre(s)`` columns the row list reads."""
    import json

    from metatv.core.genre_words import resolve_genres

    for key, raw in session.execute(text(
            "SELECT channel_key, detected_genres FROM channels "
            "WHERE detected_genres IS NOT NULL AND detected_genres != '[]'")).all():
        try:
            old = json.loads(raw) if isinstance(raw, str) else list(raw or [])
        except ValueError:
            continue
        new: list[str] = []
        for g in old:
            for c in resolve_genres(g):
                if c not in new:
                    new.append(c)
        if new != old:
            session.execute(text(
                "UPDATE channels SET detected_genres = :g, detected_genre = :first "
                "WHERE channel_key = :k"),
                {"g": json.dumps(new), "first": new[0] if new else None, "k": key})

