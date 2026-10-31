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
