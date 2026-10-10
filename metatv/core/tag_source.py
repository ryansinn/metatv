"""DB-9: ``content_tags.source`` provenance <-> small-int mapping.

``source`` sits IN the ``content_tags`` WITHOUT ROWID composite primary key
(``channel_key, tag_id, source``), so a 1-byte int key shrinks the whole
content_tags B-tree, not just this column (measured: 100% of 3.16M rows on
the owner's library were the 9-byte string ``"generated"``). The
application-facing API still speaks the two provenance strings everywhere
(``set_content_tags(..., source="user")`` etc.) — ``TagSourceType`` translates
transparently at the ORM boundary (same pattern as ``database.JSONEncoded``),
so none of the call sites naming ``"generated"``/``"user"`` needed to change.

``source`` is a real two-value provenance enum, not incidentally-constant
data: per CLAUDE.md's tags rule ("every tag records its feeder +
read-vs-inference"), a column that is 100% one value TODAY may still be the
model's provenance slot, so this INTERNS the value rather than dropping the
column.
"""

from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.types import TypeDecorator

_TAG_SOURCE_TO_INT = {"generated": 0, "user": 1}
_TAG_SOURCE_FROM_INT = {v: k for k, v in _TAG_SOURCE_TO_INT.items()}


class TagSourceType(TypeDecorator):
    """Maps content_tags' two provenance strings to a small stored int.

    Raises on an unrecognised value at WRITE time (a typo introducing a third
    source is a bug, not new data to accommodate silently). A value that
    somehow was never migrated correctly is not masked on READ either — it
    round-trips as ``"unknown:<n>"`` rather than crashing every tag query.
    """

    impl = Integer
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        try:
            return _TAG_SOURCE_TO_INT[value]
        except KeyError:
            raise ValueError(
                f"content_tags.source must be 'generated' or 'user', got {value!r}"
            ) from None

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return _TAG_SOURCE_FROM_INT.get(value, f"unknown:{value}")


# ── Feeder codes ──────────────────────────────────────────────────────────────
# A content_tags link records which feeders asserted it. Stored as the feeder
# NAMES in JSON ('["provider_category","name_parse"]'), the same few words were
# repeated across ~4M rows; stored as codes ("1,2") they cost a few bytes.
# Readers still see names: the column type translates both ways.
#
# PERMANENT: a code, once written, means its feeder forever. Never renumber or
# reuse one; a new feeder takes the next unused number. A name not listed here
# is stored as its own text (never lost), so forgetting to add one costs bytes,
# not data.

import json as _json

from sqlalchemy import Text, literal, or_

FEEDER_CODES: dict[str, int] = {
    "provider_category": 1, "name_parse": 2, "region_inference": 3,
    "metadata_credits": 4, "genre": 5, "header": 6, "audio_annotation": 7,
    "name_cast": 8, "name_ai_marker": 9, "played_tracks": 10,
    "provider_probe": 11, "provider_detail": 12, "user": 13, "tmdb": 14,
    "metadata": 15,
}
_FEEDER_NAMES = {code: name for name, code in FEEDER_CODES.items()}


def encode_feeders(feeders) -> str | None:
    """``["provider_category", "x"]`` → ``"1,x"``."""
    if feeders is None:
        return None
    return ",".join(str(FEEDER_CODES.get(f, f)) for f in feeders)


def decode_feeders(stored) -> list:
    """Stored codes (or the legacy JSON form) → feeder names."""
    if stored is None or stored == "":
        return [] if stored == "" else None
    if isinstance(stored, list):
        return stored
    if stored.startswith("["):                        # pre-codes JSON, until converted
        try:
            return list(_json.loads(stored))
        except ValueError:
            return []
    return [_FEEDER_NAMES.get(int(t), t) if t.isdigit() else t for t in stored.split(",") if t]


class FeederList(TypeDecorator):
    """``content_tags.feeders``: a list of feeder names, stored as codes."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encode_feeders(value)

    def process_result_value(self, value, dialect):
        return decode_feeders(value)


def feeder_present(column, name: str):
    """SQL: the link's feeders include *name* — matches both stored forms."""
    from sqlalchemy import type_coerce
    text_col = type_coerce(column, Text)
    code = FEEDER_CODES.get(name)
    clauses = [text_col.like(f'%"{name}"%')]                      # legacy JSON form
    if code is not None:
        clauses.append((literal(",") + text_col + literal(",")).like(f"%,{code},%"))
    return or_(*clauses)
