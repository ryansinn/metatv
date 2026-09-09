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
