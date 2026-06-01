"""Tests for the legacy double-encoded JSON normalization migration (B3-3 follow-up).

Pre-B3-3 code wrote ``json.dumps(obj)`` into ``Column(JSON)``, double-encoding the
value on disk as a JSON *string* (text begins with a quote, e.g. ``"[{...}]"``).
The B3-3 ``JSONEncoded`` TypeDecorator decodes exactly once, so those legacy rows
read back as ``str``. ``Database._normalize_double_encoded_json`` peels the extra
layer in place; these tests pin that it fixes double-encoded rows, leaves correctly
single-encoded rows untouched, and is gated to run at most once.
"""

import json
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import text

from metatv.core.database import Database, MetadataDB, ProviderDB


@pytest.fixture()
def file_db():
    """A real file-backed Database (in-memory won't share state across connections)."""
    with tempfile.TemporaryDirectory() as d:
        db = Database(f"sqlite:///{Path(d) / 'test.db'}")
        db.create_tables()  # runs _migrate, which sets user_version = 1 on the empty DB
        yield db
        db.close()


def _raw_insert(db, table, columns: dict):
    cols = ", ".join(f'"{c}"' for c in columns)
    binds = ", ".join(f":{c}" for c in columns)
    with db.engine.connect() as conn:
        conn.execute(text(f"INSERT INTO {table} ({cols}) VALUES ({binds})"), columns)
        conn.commit()


def _reset_migration_gate(db):
    with db.engine.connect() as conn:
        conn.execute(text("PRAGMA user_version = 0"))
        conn.commit()


# ---------------------------------------------------------------------------
# Core behavior
# ---------------------------------------------------------------------------

def test_double_encoded_cast_is_normalized(file_db):
    """A legacy double-encoded metadata.cast must read back as a list after migration."""
    real = [{"name": "Karl Urban", "character": "Billy Butcher"}]
    # double-encoded on-disk text: json.dumps applied twice (manual dumps + Column(JSON))
    _raw_insert(file_db, "metadata", {
        "id": "m1", "title": "The Boys", "cast": json.dumps(json.dumps(real)),
    })

    _reset_migration_gate(file_db)
    file_db._normalize_double_encoded_json()

    with file_db.session_scope() as s:
        got = s.query(MetadataDB).filter_by(id="m1").first().cast
    assert got == real, f"Expected list {real}, got {got!r} ({type(got).__name__})"


def test_double_encoded_provider_urls_is_normalized(file_db):
    """A legacy double-encoded providers.urls must read back as a list of dicts."""
    real = [{"url": "http://a.test", "priority": 0, "success_count": 6}]
    _raw_insert(file_db, "providers", {
        "id": "p1", "name": "P", "type": "xtream", "url": "http://a.test",
        "urls": json.dumps(json.dumps(real)),
    })

    _reset_migration_gate(file_db)
    file_db._normalize_double_encoded_json()

    with file_db.session_scope() as s:
        got = s.query(ProviderDB).filter_by(id="p1").first().urls
    assert got == real


def test_single_encoded_row_is_left_untouched(file_db):
    """Correctly single-encoded values must not be altered (idempotency safety)."""
    real = ["Drama", "Thriller"]
    _raw_insert(file_db, "metadata", {
        "id": "m2", "title": "Show", "genres": json.dumps(real),  # single-encoded
    })

    _reset_migration_gate(file_db)
    file_db._normalize_double_encoded_json()

    with file_db.session_scope() as s:
        got = s.query(MetadataDB).filter_by(id="m2").first().genres
    assert got == real


def test_migration_is_idempotent(file_db):
    """Running the normalization twice must not corrupt already-fixed rows."""
    real = [{"name": "Alice"}]
    _raw_insert(file_db, "metadata", {
        "id": "m3", "title": "T", "cast": json.dumps(json.dumps(real)),
    })

    _reset_migration_gate(file_db)
    file_db._normalize_double_encoded_json()
    _reset_migration_gate(file_db)
    file_db._normalize_double_encoded_json()  # second pass — row is now single-encoded

    with file_db.session_scope() as s:
        got = s.query(MetadataDB).filter_by(id="m3").first().cast
    assert got == real


def test_migration_gate_prevents_rerun(file_db):
    """With user_version already >= 1, the normalization is a no-op (gate respected)."""
    real = [{"name": "Bob"}]
    _raw_insert(file_db, "metadata", {
        "id": "m4", "title": "T", "cast": json.dumps(json.dumps(real)),
    })

    # Do NOT reset the gate (create_tables left it at 1) — migration should skip.
    file_db._normalize_double_encoded_json()

    with file_db.session_scope() as s:
        got = s.query(MetadataDB).filter_by(id="m4").first().cast
    # Still double-encoded → JSONEncoded yields a string (proves the gate held).
    assert isinstance(got, str)
