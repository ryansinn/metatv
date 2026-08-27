"""Per-refresh tagging must cost a fixed number of statements, not one set per channel.

``ProviderLoadThread._update_tags_in_thread`` runs on EVERY source refresh, 500
channels to a batch. For each channel it issued a DELETE, then a SELECT and an
upsert, then an UPDATE for the fingerprint — roughly 2,000 round-trips per
batch. The bulk methods already existed and ``TagBackfillTask`` already used
them; this path never adopted them.

The assertion is a STATEMENT COUNT taken off the engine, not a stopwatch: it is
identical on both CI runners, and it fails for the right reason. A count that
grows with the number of channels is the defect, whatever the wall clock says on
the day.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import event

from metatv.core.database import ChannelDB, ContentTagDB, Database, ProviderDB, TagDB
from tests.conftest import make_provider_load_thread


@pytest.fixture
def db(tmp_path):
    """A real on-disk database — this test is about the statements SQLite receives."""
    database = Database(f"sqlite:///{tmp_path}/tags.db")
    database.create_tables()
    yield database
    database.close()


def _seed(database: Database, provider_id: str, count: int) -> None:
    with database.session_scope() as session:
        if not session.query(ProviderDB).filter_by(id=provider_id).first():
            session.add(ProviderDB(
                id=provider_id, name="Test Source", type="xtream",
                url="http://example", is_active=True, account_status="Active",
            ))
        for i in range(count):
            session.add(ChannelDB(
                id=f"{provider_id}-{i}",
                source_id=str(uuid.uuid4()),
                provider_id=provider_id,
                name=f"|EN| Widget {i} (2024) 4K",
                media_type="movie",
                category="MOVIES",
                is_hidden=False,
                detected_prefix="EN",
                detected_quality="4K",
                detected_year="2024",
                detected_title=f"Widget {i}",
            ))


def _run_tagging(database: Database, provider_id: str) -> list[str]:
    """Run the real refresh hook, returning every SQL statement it issued."""
    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(database.engine, "before_cursor_execute", _record)
    try:
        make_provider_load_thread(database, provider_id)._update_tags_in_thread()
    finally:
        event.remove(database.engine, "before_cursor_execute", _record)
    return statements


def _writes(statements: list[str]) -> dict[str, int]:
    """Count the write statements by kind, ignoring reads and transaction control."""
    counts = {"delete": 0, "insert": 0, "update": 0}
    for s in statements:
        head = s.lstrip().split(None, 1)[0].lower() if s.strip() else ""
        if head in counts:
            counts[head] += 1
    return counts


def test_tag_writes_do_not_scale_with_the_number_of_channels(db):
    """Four times the channels must not mean four times the statements."""
    _seed(db, "p-small", 5)
    small = _writes(_run_tagging(db, "p-small"))

    _seed(db, "p-large", 20)
    large = _writes(_run_tagging(db, "p-large"))

    growth = sum(large.values()) - sum(small.values())
    assert growth <= 2, (
        "tag writes scale with channel count: "
        f"5 channels -> {small}, 20 channels -> {large}. "
        "Fifteen more channels added "
        f"{growth} statements; batching should add at most a couple."
    )


def test_one_batch_issues_one_delete_and_one_upsert(db):
    """The shape, stated exactly, so a partial revert is visible."""
    _seed(db, "p1", 12)
    counts = _writes(_run_tagging(db, "p1"))

    assert counts["delete"] <= 1, (
        f"expected at most one bulk DELETE for the batch, got {counts['delete']}"
    )
    assert counts["update"] <= 1, (
        "the fingerprint UPDATE must be one executemany for the batch, got "
        f"{counts['update']} statements"
    )
    # INSERTs are one per NEW tag row (TagDB — bounded by the tag vocabulary,
    # not by the channel count) plus one bulk upsert for all the links. Twelve
    # identically-shaped channels share their tags, so the ceiling is the number
    # of distinct tags the batch created, plus that one upsert.
    with db.session_scope() as session:
        distinct_tags = session.query(TagDB).count()
    assert counts["insert"] <= distinct_tags + 1, (
        f"{counts['insert']} INSERTs for {distinct_tags} distinct tags across 12 "
        "channels — a bulk upsert writes all the links in one statement"
    )


def test_the_batching_still_writes_the_same_tags(db):
    """Fewer statements must not mean fewer tags — the whole point is identical output."""
    _seed(db, "p1", 6)
    _run_tagging(db, "p1")

    with db.session_scope() as session:
        links = session.query(ContentTagDB).filter(
            ContentTagDB.channel_id.like("p1-%")
        ).all()
        tagged = {link.channel_id for link in links}
        assert len(tagged) == 6, f"every channel must be tagged, got {sorted(tagged)}"
        assert all(link.source == "generated" for link in links)
        assert all(link.feeders for link in links), "every link records its feeder"


def test_a_second_pass_rewrites_nothing(db):
    """The fingerprint skip must survive batching, or every refresh re-tags everything."""
    _seed(db, "p1", 8)
    _run_tagging(db, "p1")

    second = _writes(_run_tagging(db, "p1"))
    assert sum(second.values()) == 0, (
        f"unchanged channels were re-tagged on the second pass: {second}"
    )


def test_tag_ids_come_from_the_cache_without_a_select(db):
    """The id cache must not round-trip; that was the larger half of the cost.

    ``get_or_create_tag`` caches the id and then calls
    ``session.get(TagDB, cached_id)`` to return a row. That is a real SELECT
    whenever the object is not already in THIS session's identity map — and the
    tagging path opens a session per batch and commits inside it, so the map is
    empty or expired almost every time. Measured before the fix: 796 identical
    ``SELECT ... FROM tags WHERE tags.id = ?`` for 200 channels.

    Asserted against a WARM cache, because that is the state every batch after
    the first one runs in.
    """
    _seed(db, "p1", 10)
    _run_tagging(db, "p1")          # warms _TAG_ID_CACHE and writes the tag rows

    _seed(db, "p2", 10)             # same tag vocabulary, different channels
    statements = _run_tagging(db, "p2")

    by_id = [s for s in statements if "FROM tags" in s and "tags.id = ?" in s]
    assert not by_id, (
        f"{len(by_id)} primary-key lookups against `tags` with the cache warm; "
        "the writers should be reading ids straight out of _TAG_ID_CACHE"
    )


def test_the_id_only_path_still_creates_a_missing_tag(db):
    """A cache miss must fall through and insert, not hand back a bogus id."""
    from metatv.core.repositories import RepositoryFactory
    from metatv.core.repositories.tag import _clear_tag_cache

    _clear_tag_cache()
    with db.session_scope() as session:
        repos = RepositoryFactory(session)
        first = repos.tags.get_or_create_tag_id("region", "ZZ")
        assert isinstance(first, int) and first > 0
        again = repos.tags.get_or_create_tag_id("region", "ZZ")
        assert again == first, "a second call must return the same id, not a new row"

    with db.session_scope() as session:
        rows = session.query(TagDB).filter_by(type="region", value="ZZ").all()
        assert len(rows) == 1, f"expected exactly one tag row, got {len(rows)}"
        assert rows[0].id == first
