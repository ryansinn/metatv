"""Behavioral tests for the bulk-upsert channel store path.

These tests drive ``ProviderLoadThread._store_channels`` (extracted helper)
directly with fake Channel objects so they run without a network or Qt event
loop.  The file-backed tmp_path DB (not :memory:) ensures pooled connections
each see the same rows — matching production SQLite behaviour.

Critical regression guarded:
  ON CONFLICT DO UPDATE must NOT overwrite derived/user columns (is_favorite,
  play_count, detected_prefix, user_category, etc.).  The old merge() path
  preserved these silently because it only set the columns it knew about;
  a naive INSERT OR REPLACE would wipe them.  These tests fail if the upsert
  ever clobbers user data.
"""

from unittest.mock import MagicMock

import pytest

from metatv.core.database import Database, ChannelDB
from metatv.core.provider_loader import ProviderLoadThread, _STORE_BATCH
from metatv.core.models import Provider


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path):
    """File-backed SQLite Database — isolated per test, not :memory:."""
    db_path = tmp_path / "test.db"
    db = Database(f"sqlite:///{db_path}")
    db.create_tables()
    yield db
    db.close()


@pytest.fixture
def fake_provider():
    """Minimal Provider instance for testing (no network calls)."""
    p = Provider.__new__(Provider)
    p.id = "test_prov"
    p.name = "Test Provider"
    p.type = "xtream"
    p.url = "http://example.com"
    p.username = "user"
    p.password = "pass"
    p.urls = []
    return p


@pytest.fixture
def store_thread(fake_provider, tmp_db):
    """ProviderLoadThread with signals disconnected (no Qt event loop needed)."""
    thread = ProviderLoadThread(fake_provider, tmp_db)
    return thread


def _make_channel(
    ch_id: str,
    name: str = "Test Channel",
    media_type: str = "live",
    stream_url: str = "http://example.com/stream",
    category: str = "General",
    quality: str = "hd",
    raw_data: dict | None = None,
) -> MagicMock:
    """Return a fake Channel-like object (duck-typing; no import of Channel dataclass)."""
    ch = MagicMock()
    ch.id = ch_id
    ch.source_id = ch_id
    ch.provider_id = "test_prov"
    ch.name = name
    ch.stream_url = stream_url
    ch.category = category
    ch.category_id = "cat_1"
    ch.logo_url = ""
    ch.media_type = media_type
    ch.quality = MagicMock()
    ch.quality.value = quality
    ch.raw_data = raw_data if raw_data is not None else {}
    return ch


def _read_channel(db: Database, ch_id: str) -> dict:
    """Read a single ChannelDB row and return it as a plain dict (session-safe)."""
    session = db.get_session()
    try:
        row = session.query(ChannelDB).filter_by(id=ch_id).one_or_none()
        if row is None:
            return {}
        return {
            "id": row.id,
            "name": row.name,
            "stream_url": row.stream_url,
            "category": row.category,
            "media_type": row.media_type,
            "quality": row.quality,
            "is_adult": row.is_adult,
            "source_category": row.source_category,
            "source_quality_flags": row.source_quality_flags,
            "is_favorite": row.is_favorite,
            "play_count": row.play_count,
            "detected_prefix": row.detected_prefix,
            "user_category": row.user_category,
        }
    finally:
        session.close()


def _count_channels(db: Database) -> int:
    """Return the total number of ChannelDB rows."""
    session = db.get_session()
    try:
        return session.query(ChannelDB).count()
    finally:
        session.close()


def _store(thread: ProviderLoadThread, db: Database, channels: list) -> None:
    """Helper: obtain a session, store channels, and close."""
    session = db.get_session()
    try:
        thread._store_channels(session, channels, total=len(channels))
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Test 1 — Insert: new channels are written with correct catalog fields
# ---------------------------------------------------------------------------

def test_insert_new_channels(store_thread, tmp_db):
    """Storing new channels writes all catalog fields correctly."""
    channels = [
        _make_channel("ch1", name="BBC One", category="News", stream_url="http://ex.com/s/1"),
        _make_channel("ch2", name="CNN", category="News", stream_url="http://ex.com/s/2"),
        _make_channel("ch3", name="Action Movie", media_type="movie", stream_url="http://ex.com/s/3"),
    ]

    _store(store_thread, tmp_db, channels)

    assert _count_channels(tmp_db) == 3, "All three channels must be inserted"

    ch1 = _read_channel(tmp_db, "ch1")
    assert ch1["name"] == "BBC One"
    assert ch1["category"] == "News"
    assert ch1["stream_url"] == "http://ex.com/s/1"
    assert ch1["media_type"] == "live"

    ch2 = _read_channel(tmp_db, "ch2")
    assert ch2["name"] == "CNN"

    ch3 = _read_channel(tmp_db, "ch3")
    assert ch3["media_type"] == "movie"


# ---------------------------------------------------------------------------
# Test 2 — Upsert preserves user/derived data (THE critical test)
# ---------------------------------------------------------------------------

def test_upsert_preserves_user_and_derived_columns(store_thread, tmp_db):
    """ON CONFLICT must NOT overwrite is_favorite, play_count, detected_prefix, user_category.

    Sequence:
      1. Insert channel ch1 via _store_channels.
      2. Set user/derived columns directly in the DB (simulates user interaction + prefix detection).
      3. Store ch1 again via _store_channels with a *changed* catalog field (name, stream_url).
      4. Assert the catalog field updated AND all user/derived columns survived.
    """
    # --- Step 1: initial insert ---
    _store(store_thread, tmp_db, [_make_channel("ch1", name="Old Name", stream_url="http://old.com/stream")])

    # --- Step 2: simulate user interaction + prefix detection ---
    with tmp_db.session_scope() as s:
        row = s.query(ChannelDB).filter_by(id="ch1").one()
        row.is_favorite = True
        row.play_count = 7
        row.detected_prefix = "EN"
        row.user_category = "Faves"

    # --- Step 3: re-store with changed catalog fields ---
    _store(store_thread, tmp_db, [
        _make_channel("ch1", name="New Name", stream_url="http://new.com/stream", category="Updated Category")
    ])

    # --- Step 4: assert catalog updated AND user/derived preserved ---
    row = _read_channel(tmp_db, "ch1")

    # Catalog fields must be updated
    assert row["name"] == "New Name", "name (catalog) must be updated by the upsert"
    assert row["stream_url"] == "http://new.com/stream", "stream_url (catalog) must be updated"
    assert row["category"] == "Updated Category", "category (catalog) must be updated"

    # User/derived fields must be preserved
    assert row["is_favorite"] is True, "is_favorite must survive a provider refresh"
    assert row["play_count"] == 7, "play_count must survive a provider refresh"
    assert row["detected_prefix"] == "EN", "detected_prefix must survive a provider refresh"
    assert row["user_category"] == "Faves", "user_category must survive a provider refresh"


# ---------------------------------------------------------------------------
# Test 3 — Batch boundary: > _STORE_BATCH channels all persist
# ---------------------------------------------------------------------------

def test_batch_boundary_all_channels_persisted(store_thread, tmp_db):
    """Storing more than _STORE_BATCH channels flushes multiple batches correctly.

    Uses _STORE_BATCH + 101 channels so there are two batches: one full batch
    and a non-trivial partial batch of 101 rows.
    """
    count = _STORE_BATCH + 101
    channels = [_make_channel(f"ch{i}", name=f"Channel {i}") for i in range(count)]

    _store(store_thread, tmp_db, channels)

    stored_count = _count_channels(tmp_db)
    assert stored_count == count, (
        f"All {count} channels must be stored across batch boundaries "
        f"(got {stored_count})"
    )


# ---------------------------------------------------------------------------
# Test 4 — Hash-header state: source_category propagates to subsequent live channels
# ---------------------------------------------------------------------------

def test_hash_header_source_category_propagates(store_thread, tmp_db):
    """##SPORTS## header must set source_category on all subsequent live channels.

    This guards the stateful hash-header logic: a header line must carry
    forward to every following channel until the next header appears.
    """
    channels = [
        _make_channel("h1", name="## SPORTS ##", media_type="live"),    # header
        _make_channel("ch1", name="Match 1", media_type="live"),
        _make_channel("ch2", name="Match 2", media_type="live"),
        _make_channel("h2", name="## NEWS ##", media_type="live"),      # new header
        _make_channel("ch3", name="Evening News", media_type="live"),
        _make_channel("ch4", name="Movie Night", media_type="movie"),   # movie — no source_category
    ]

    _store(store_thread, tmp_db, channels)

    ch1 = _read_channel(tmp_db, "ch1")
    ch2 = _read_channel(tmp_db, "ch2")
    ch3 = _read_channel(tmp_db, "ch3")
    ch4 = _read_channel(tmp_db, "ch4")

    assert ch1["source_category"] == "SPORTS", (
        "ch1 must inherit source_category from the preceding ## SPORTS ## header"
    )
    assert ch2["source_category"] == "SPORTS", (
        "ch2 must inherit source_category from the preceding ## SPORTS ## header"
    )
    assert ch3["source_category"] == "NEWS", (
        "ch3 must inherit source_category from the ## NEWS ## header"
    )
    assert ch4["source_category"] is None, (
        "movie channels must NOT get source_category (live-only field)"
    )


def test_hash_header_channels_are_not_stored(store_thread, tmp_db):
    """##...## header rows are positional markers (bumper/loop streams), not
    content — they must NOT be stored as channels, while their label still
    propagates as source_category to the channels that follow.  Covers the
    trailing-token form (``#### X ##### · UHD``) the old end-anchored regex missed.
    """
    channels = [
        _make_channel("h1", name="## SPORTS ##", media_type="live"),                   # header
        _make_channel("ch1", name="Match 1", media_type="live"),
        _make_channel("h2", name="#### BAMBINI HD/4K ##### · UHD", media_type="live"),  # trailing-token header
        _make_channel("ch2", name="Cartoon", media_type="live"),
    ]

    _store(store_thread, tmp_db, channels)

    # Header rows are skipped — never stored as browsable channels.
    assert _read_channel(tmp_db, "h1") == {}, "## SPORTS ## header must not be stored"
    assert _read_channel(tmp_db, "h2") == {}, (
        "trailing-token header '#### BAMBINI HD/4K ##### · UHD' must not be stored"
    )

    # …but the channels that follow still inherit each header's label.
    assert _read_channel(tmp_db, "ch1").get("source_category") == "SPORTS"
    assert _read_channel(tmp_db, "ch2").get("source_category") == "BAMBINI HD/4K"


def test_parse_hash_header_matches_trailing_token_form():
    """Regex guard: a closing-hash run may be followed by a trailing token."""
    from metatv.core.provider_loader import _parse_hash_header
    assert _parse_hash_header("#### BAMBINI HD/4K ##### · UHD") == ("BAMBINI HD/4K", "")
    assert _parse_hash_header("### M. LIGA DE CAMPEONES ###")[0] == "M. LIGA DE CAMPEONES"
    assert _parse_hash_header("Real Channel HD") is None       # not a header
    assert _parse_hash_header("CNN ## breaking") is None        # leading text, not a header


# ---------------------------------------------------------------------------
# Test 5 — is_adult extracted from raw_data correctly
# ---------------------------------------------------------------------------

def test_is_adult_extracted_from_raw_data(store_thread, tmp_db):
    """is_adult must be derived from raw_data['is_adult'] (int 1 / string '1' / bool True)."""
    channels = [
        _make_channel("adult_int",  raw_data={"is_adult": 1}),
        _make_channel("adult_str",  raw_data={"is_adult": "1"}),
        _make_channel("adult_bool", raw_data={"is_adult": True}),
        _make_channel("not_adult",  raw_data={"is_adult": 0}),
        _make_channel("no_field",   raw_data={}),
    ]

    _store(store_thread, tmp_db, channels)

    assert _read_channel(tmp_db, "adult_int")["is_adult"] is True
    assert _read_channel(tmp_db, "adult_str")["is_adult"] is True
    assert _read_channel(tmp_db, "adult_bool")["is_adult"] is True
    assert _read_channel(tmp_db, "not_adult")["is_adult"] is False
    assert _read_channel(tmp_db, "no_field")["is_adult"] is False
