"""Credits — cast and directing — read from ONE place.

Every reader of "who is in this" (the Details Cast section, taste weights,
recommendation scoring, copy matching, search ranking, Similar Content) goes
through here; none of them knows where credits are stored. They are stored ONLY as
``cast`` / ``director`` tags (``tag_decomposer.credit_tags``: one vocabulary
row per name, a link per channel with billing order and character); the old
``metadata.cast`` / ``metadata.director`` text was dropped after conversion
(``credits_text_drop``).

Two forms, same answer:

* :func:`credits_for` — a batch lookup for a handful of channels.
* :func:`cast_column` / :func:`director_column` — SQL columns for bulk queries
  (the recommendation candidate pool), selected in place of the old metadata
  columns and read back with :func:`cast_names` / :func:`director_names`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy import func, select

#: Separator inside a bulk cast column (never appears in a name).
_SEP = "\x1f"


@dataclass(frozen=True)
class Credits:
    """One channel's credits. ``cast`` is billing order: ``(name, character)``."""

    cast: tuple = field(default_factory=tuple)
    directors: tuple = field(default_factory=tuple)

    def cast_names(self) -> list[str]:
        return [name for name, _character in self.cast]


def _split_directors(value):
    from metatv.core.preference_engine import _split_directors as split
    return split(value) if value else []


def _legacy(cast_json, director) -> Credits:
    """Credits from the old metadata text (fallback until converted)."""
    cast = []
    try:
        raw = json.loads(cast_json) if isinstance(cast_json, str) else (cast_json or [])
    except ValueError:
        raw = []
    for person in raw or []:
        name = person.get("name") if isinstance(person, dict) else person
        if name:
            cast.append((name, person.get("character") if isinstance(person, dict) else None))
    return Credits(tuple(cast), tuple(_split_directors(director)))


def credits_for(session, channel_ids) -> dict:
    """``{channel_id: Credits}`` for *channel_ids*; channels with none are absent."""
    from metatv.core.database import ChannelDB, ContentTagDB, TagDB

    ids = list(dict.fromkeys(channel_ids or []))
    if not ids:
        return {}
    rows = (session.query(ChannelDB.id, TagDB.type, TagDB.value, ContentTagDB.detail,
                          ContentTagDB.ord)
            .join(ContentTagDB, ContentTagDB.channel_key == ChannelDB.channel_key)
            .join(TagDB, TagDB.id == ContentTagDB.tag_id)
            .filter(ChannelDB.id.in_(ids), TagDB.type.in_(("cast", "director")))
            .all())
    cast: dict = {}
    directors: dict = {}
    for cid, kind, value, detail, ord_ in rows:
        if kind == "cast":
            cast.setdefault(cid, []).append((ord_ if ord_ is not None else 1 << 30, value, detail))
        else:
            directors.setdefault(cid, []).append((ord_ if ord_ is not None else 1 << 30, value))
    out = {}
    for cid in ids:
        if cid in cast or cid in directors:
            people = tuple((name, detail) for _o, name, detail in sorted(cast.get(cid, [])))
            out[cid] = Credits(people, tuple(name for _o, name in sorted(directors.get(cid, []))))
    return out


def _tag_names(kind: str, sep: str, channel_cls):
    from metatv.core.database import ContentTagDB, TagDB
    inner = (select(TagDB.value)
             .join(ContentTagDB, ContentTagDB.tag_id == TagDB.id)
             .where(ContentTagDB.channel_key == channel_cls.channel_key, TagDB.type == kind)
             .order_by(ContentTagDB.ord)
             .correlate(channel_cls)
             .subquery())
    return select(func.group_concat(inner.c.value, sep)).scalar_subquery()


def cast_column(channel_cls, metadata_cls, label: str = "cast"):
    """SQL column: the channel's cast names (tags, else the old metadata JSON)."""
    return _tag_names("cast", _SEP, channel_cls).label(label)


def director_column(channel_cls, metadata_cls, label: str = "director"):
    """SQL column: the channel's directing credits, comma-separated."""
    return _tag_names("director", ", ", channel_cls).label(label)


def cast_names(value) -> list[str]:
    """Names from a :func:`cast_column` value (tag-joined or legacy JSON)."""
    if not value:
        return []
    if isinstance(value, list):
        return [p.get("name") if isinstance(p, dict) else p for p in value if p]
    if value.startswith("["):
        return _legacy(value, None).cast_names()
    return [n for n in value.split(_SEP) if n]


def director_names(value) -> list[str]:
    """Names from a :func:`director_column` value."""
    return _split_directors(value)
