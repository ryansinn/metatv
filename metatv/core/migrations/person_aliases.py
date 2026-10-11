"""Merge spelling variants of one person into one tag (owner, 2026-10-10).

Providers spell the same person differently — "Denzel Washigton" in a title,
"Denzel Washington" in the credits; "Andy Garcia" / "Andy García"; "Ryo" /
"Ryou Horikawa". Each spelling was its own person tag, so the cloud, search and
a recipe pick each saw half of them. Measured on the owner's library: 274 pairs
differing only in case/accents/punctuation, 274 close spellings on one title.

Rules (Latin-script names of 5+ letters only — other scripts normalise to
nothing and would all "match"):
* same letters once case, accents, punctuation and spacing are removed → merge;
* a close spelling (≥ 90% similar, length within 2) → merge only when both name
  copies of the SAME title (content_key) — the evidence they are one person.

The spelling with the most links wins (credited spellings first). Each alias's
links move onto it (merging feeders/roles where a title had both), the alias tag
is deleted, and its spelling is recorded in ``tag_aliases`` so the tag writer
maps it to the winner from then on. Versioned: re-run when the rules change.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Callable

from loguru import logger
from sqlalchemy import text

from metatv.core.migrations.person_identity import _UPSERT
from metatv.core.tag_source import FEEDER_CODES, PERSON_TYPE

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database

CURRENT_VERSION: int = 1
_MIN_LETTERS = 5
_SIMILARITY = 0.9


def _letters(name: str) -> str:
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", plain.lower())


def alias_clusters(people: dict[int, str], titles_of: dict[int, set]) -> list[set[int]]:
    """Group person tag ids that are one person (see the module rules)."""
    parent = {pid: pid for pid in people}

    def root(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def join(a, b):
        parent[root(a)] = root(b)

    letters = {pid: _letters(v) for pid, v in people.items()}
    by_letters: dict[str, list[int]] = defaultdict(list)
    for pid, key in letters.items():
        if len(key) >= _MIN_LETTERS:
            by_letters[key].append(pid)
    for group in by_letters.values():
        for other in group[1:]:
            join(group[0], other)
    by_title: dict[str, list[int]] = defaultdict(list)
    for pid, titles in titles_of.items():
        if len(letters.get(pid, "")) >= _MIN_LETTERS:
            for t in titles:
                by_title[t].append(pid)
    for pids in by_title.values():
        if len(pids) > 60:
            continue
        for i, a in enumerate(pids):
            for b in pids[i + 1:]:
                la, lb = letters[a], letters[b]
                if la != lb and abs(len(la) - len(lb)) <= 2 and \
                        difflib.SequenceMatcher(None, la, lb).ratio() >= _SIMILARITY:
                    join(a, b)
    clusters: dict[int, set[int]] = defaultdict(set)
    for pid in people:
        clusters[root(pid)].add(pid)
    return [c for c in clusters.values() if len(c) > 1]


class PersonAliasTask:
    """Merge person spelling variants; record the aliases for the writer."""

    id: str = "person_aliases"
    label: str = "Merging spellings of the same person"

    def __init__(self, db: "Database") -> None:
        self._db = db

    def needs_run(self, config: "Config") -> bool:
        return getattr(config, "person_aliases_version", 0) < CURRENT_VERSION

    def run(self, progress_cb: Callable[[int, int], None],
            is_cancelled: Callable[[], bool], config: "Config | None" = None) -> None:
        credit = str(FEEDER_CODES["metadata_credits"])
        with self._db.engine.connect() as conn:
            people = dict(conn.execute(text(
                "SELECT id, value FROM tags WHERE type = :t"), {"t": PERSON_TYPE}).all())
            titles_of: dict[int, set] = defaultdict(set)
            links: Counter = Counter()
            credited: set[int] = set()
            for tid, key, feeders in conn.execute(text(
                    "SELECT ct.tag_id, COALESCE(c.content_key, 'id:' || c.id), ct.feeders"
                    " FROM content_tags ct JOIN tags t ON t.id = ct.tag_id"
                    " JOIN channels c ON c.channel_key = ct.channel_key WHERE t.type = :t"),
                    {"t": PERSON_TYPE}):
                titles_of[tid].add(key)
                links[tid] += 1
                if feeders and credit in str(feeders).split(","):
                    credited.add(tid)
        clusters = alias_clusters(people, titles_of)
        progress_cb(0, len(clusters))
        merged = 0
        for i, cluster in enumerate(clusters, start=1):
            if is_cancelled():
                return
            keep = max(cluster, key=lambda p: (p in credited, links[p], people[p]))
            with self._db.session_scope() as session:
                for alias in cluster - {keep}:
                    session.execute(text(
                        "INSERT INTO content_tags (channel_key, tag_id, source, feeders, detail, ord, qualifier)"
                        " SELECT channel_key, :keep, source, feeders, detail, ord, qualifier"
                        " FROM content_tags WHERE tag_id = :alias AND true" + _UPSERT),
                        {"keep": keep, "alias": alias})
                    session.execute(text("DELETE FROM content_tags WHERE tag_id = :a"), {"a": alias})
                    session.execute(text("UPDATE tag_aliases SET tag_id = :k WHERE tag_id = :a"),
                                    {"k": keep, "a": alias})
                    session.execute(text(
                        "INSERT OR REPLACE INTO tag_aliases (type, value, tag_id) VALUES (:t, :v, :k)"),
                        {"t": PERSON_TYPE, "v": people[alias], "k": keep})
                    session.execute(text("DELETE FROM tags WHERE id = :a"), {"a": alias})
                    merged += 1
            progress_cb(i, len(clusters))
        from metatv.core.repositories.tag import _clear_tag_cache
        _clear_tag_cache()   # merged-away ids must not be handed out again
        logger.info("person_aliases: merged {} spelling(s) into {} people", merged, len(clusters))

    def on_completed(self, config: "Config") -> None:
        config.person_aliases_version = CURRENT_VERSION
        config.save()
