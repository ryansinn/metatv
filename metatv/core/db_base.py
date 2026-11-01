"""The declarative ``Base`` every model registers on, and the JSON column type.

Their own module so a model file outside ``database.py`` (``playback_models``)
can import them without importing ``database.py`` — which itself imports those
model files to register their tables, so going through it would be circular.
``database.py`` re-exports both, so ``from metatv.core.database import Base``
keeps working everywhere.
"""

import json as _json

from sqlalchemy import Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.types import TypeDecorator

Base = declarative_base()


class JSONEncoded(TypeDecorator):
    """Stores any JSON-serializable Python object as TEXT in SQLite.

    Use instead of Column(JSON) to avoid SQLite JSON-type quirks. Assign plain
    Python objects (lists, dicts, None); serialization is transparent.

        cast = Column(JSONEncoded)   # assign/read a Python list — no json.dumps/loads needed
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return _json.dumps(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return _json.loads(value)


def unicode_lower(value):
    """SQLite's ``lower()`` folds ASCII only: ``lower('ÉCOLE')`` is ``'École'``.

    ``Database`` registers this over the built-in on every connection (ledger
    F55), so every ``func.lower`` and every ``.ilike()`` — SQLAlchemy renders it
    on SQLite as ``lower(a) LIKE lower(b)`` — folds the way Python's
    ``str.lower`` does. Searching "école" found 22 of the owner's 33 matching
    titles before. No index is built on ``lower()``, so none can disagree with
    it; the cost is ~70 ms per full scan of ~490k channel names, on queries
    that already run off the main thread.
    """
    return value.lower() if isinstance(value, str) else value
