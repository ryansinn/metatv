"""Collection shelves — Discover surfaces the ingestion-computed
``ChannelDB.detected_collection`` (Apple+ Kids, Hindu Subs, ...) as shelves.

``detected_collection`` is already computed at ingestion by
``update_detected_prefixes()`` (core/repositories/channel.py, #252) — these
tests set it directly on seeded rows (simulating a completed ingestion pass)
rather than re-running the parser, since discovery_engine must only ever READ
the stored field (CLAUDE.md "compute once at ingestion, read everywhere
else").

Guards:
1. ``get_all_collections`` produces shelves for multi-member collections only
   (floor = ``MIN_COLLECTION_SHELF_MEMBERS`` = 2); a single-member collection
   is absent.
2. Channels with a NULL ``detected_collection`` never form a shelf.
3. Content belonging to an excluded/hidden provider is never counted toward a
   collection's member total, and never returned by ``get_by_collection`` —
   even when it shares a collection name with visible content (proves the
   exclusion is enforced by the parameter, not just "no hidden-provider rows
   exist" by fixture accident).
4. Ordering is deterministic across repeated calls: member count descending,
   then name ascending.
5. The ``fetch_cards_for_key`` dispatcher (discover_workers.py) routes
   ``"collection:<name>"`` keys to ``get_by_collection`` and honors the same
   exclusion.
"""

from __future__ import annotations

import uuid

import pytest


# ---------------------------------------------------------------------------
# Fixture — real file-backed Database (never :memory:)
# ---------------------------------------------------------------------------

@pytest.fixture()
def collection_db(tmp_path):
    from metatv.core.database import Database, ChannelDB, ProviderDB

    db = Database(f"sqlite:///{tmp_path / 'collections.db'}")
    db.create_tables()
    session = db.get_session()
    try:
        # p1 — active/visible provider.
        session.add(ProviderDB(
            id="p1", name="Visible Provider", type="xtream",
            url="http://visible.example.com", is_active=True,
        ))
        # p2 — inactive provider; content must be gated out of every
        # forward-looking view (CLAUDE.md "disabled/expired = absolute gate").
        session.add(ProviderDB(
            id="p2", name="Hidden Provider", type="xtream",
            url="http://hidden.example.com", is_active=False,
        ))

        def _add(provider_id: str, collection: str | None, n: int, prefix: str) -> None:
            for i in range(n):
                session.add(ChannelDB(
                    id=str(uuid.uuid4()),
                    source_id=f"{prefix}_{i}",
                    provider_id=provider_id,
                    name=f"{prefix} {i}",
                    media_type="movie",
                    detected_collection=collection,
                    raw_data={"rating": "7.0", "stream_icon": ""},
                ))

        # Visible, multi-member collections (p1).
        _add("p1", "Apple+ Kids", 3, "akids")
        _add("p1", "Hindu Subs", 2, "hindu")          # exactly at the floor
        # Visible, single-member collection — noise, must be excluded.
        _add("p1", "Solo Collection", 1, "solo")
        # Visible channels with NO collection — must never form a shelf.
        _add("p1", None, 2, "nocollection")

        # Hidden-provider content sharing a collection NAME with visible
        # content — must not inflate "Apple+ Kids"'s count nor leak into its
        # cards.
        _add("p2", "Apple+ Kids", 5, "hidden_akids")
        # Hidden-provider-only collection — must never appear as a shelf at all.
        _add("p2", "Hidden Only Collection", 3, "hidden_only")

        session.commit()
    finally:
        session.close()

    yield db
    db.close()


def _hidden_provider_ids(db) -> list[str]:
    from metatv.core.repositories import RepositoryFactory
    session = db.get_session()
    try:
        return RepositoryFactory(session).providers.get_hidden_provider_ids()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# get_all_collections
# ---------------------------------------------------------------------------

def test_multi_member_collections_produce_shelves_excluding_hidden_provider(collection_db):
    from metatv.core.discovery_engine import get_all_collections

    excl_ids = _hidden_provider_ids(collection_db)
    assert "p2" in excl_ids

    session = collection_db.get_session()
    try:
        collections = get_all_collections(session, excluded_provider_ids=excl_ids)
    finally:
        session.close()

    assert collections == ["Apple+ Kids", "Hindu Subs"], (
        f"expected only the two multi-member visible-provider collections in "
        f"count-desc, name-asc order; got {collections}"
    )


def test_single_member_collection_is_absent(collection_db):
    from metatv.core.discovery_engine import get_all_collections

    excl_ids = _hidden_provider_ids(collection_db)
    session = collection_db.get_session()
    try:
        collections = get_all_collections(session, excluded_provider_ids=excl_ids)
    finally:
        session.close()

    assert "Solo Collection" not in collections


def test_null_collection_never_forms_a_shelf(collection_db):
    from metatv.core.discovery_engine import get_all_collections

    excl_ids = _hidden_provider_ids(collection_db)
    session = collection_db.get_session()
    try:
        collections = get_all_collections(session, excluded_provider_ids=excl_ids)
    finally:
        session.close()

    assert None not in collections
    assert "None" not in collections


def test_hidden_provider_only_collection_never_appears(collection_db):
    """A collection whose members exist SOLELY under an excluded provider must
    never surface as a shelf at all (not merely under-counted)."""
    from metatv.core.discovery_engine import get_all_collections

    excl_ids = _hidden_provider_ids(collection_db)
    session = collection_db.get_session()
    try:
        collections = get_all_collections(session, excluded_provider_ids=excl_ids)
    finally:
        session.close()

    assert "Hidden Only Collection" not in collections


def test_hidden_provider_content_not_counted_toward_shared_collection(collection_db):
    """Without exclusion, hidden-provider rows WOULD inflate the "Apple+ Kids"
    count from 3 to 8 — proving the exclusion parameter (not fixture luck) is
    what keeps the count correct when it's passed.
    """
    from metatv.core.discovery_engine import get_all_collections
    from metatv.core.database import ChannelDB
    from sqlalchemy import func

    excl_ids = _hidden_provider_ids(collection_db)
    session = collection_db.get_session()
    try:
        scoped_collections = get_all_collections(session, excluded_provider_ids=excl_ids)
        assert scoped_collections == ["Apple+ Kids", "Hindu Subs"]

        # Confirm the raw (unscoped) count really is 8 — i.e. the fixture does
        # contain leak-risk rows, so the scoped result above is a real guard,
        # not a vacuous pass.
        raw_count = (
            session.query(func.count(ChannelDB.id))
            .filter(ChannelDB.detected_collection == "Apple+ Kids")
            .scalar()
        )
        assert raw_count == 8

        # And when excluded_provider_ids is NOT passed, the unscoped call
        # would rank hidden-provider-inflated collections above Hindu Subs —
        # demonstrating the parameter is load-bearing, not decorative.
        unscoped_collections = get_all_collections(session, excluded_provider_ids=None)
        assert unscoped_collections[0] == "Apple+ Kids"
    finally:
        session.close()


def test_ordering_is_deterministic_across_repeated_calls(collection_db):
    from metatv.core.discovery_engine import get_all_collections

    excl_ids = _hidden_provider_ids(collection_db)
    session = collection_db.get_session()
    try:
        first = get_all_collections(session, excluded_provider_ids=excl_ids)
        second = get_all_collections(session, excluded_provider_ids=excl_ids)
    finally:
        session.close()

    assert first == second == ["Apple+ Kids", "Hindu Subs"]


def test_min_collection_shelf_members_is_a_named_constant():
    from metatv.core import discovery_engine

    assert discovery_engine.MIN_COLLECTION_SHELF_MEMBERS == 2


# ---------------------------------------------------------------------------
# get_by_collection
# ---------------------------------------------------------------------------

def test_get_by_collection_excludes_hidden_provider_cards(collection_db):
    from metatv.core.discovery_engine import get_by_collection

    excl_ids = _hidden_provider_ids(collection_db)
    session = collection_db.get_session()
    try:
        cards = get_by_collection(session, "Apple+ Kids", limit=50,
                                   excluded_provider_ids=excl_ids)
    finally:
        session.close()

    assert len(cards) == 3, f"expected only p1's 3 Apple+ Kids cards; got {len(cards)}"
    assert all(c.title.startswith("akids") for c in cards), (
        f"a hidden-provider (p2) card leaked into the shelf: {[c.title for c in cards]}"
    )


def test_get_by_collection_without_exclusion_leaks_hidden_provider_cards(collection_db):
    """Contrast case proving the exclusion in the test above is load-bearing:
    omitting excluded_provider_ids really does let p2's cards through."""
    from metatv.core.discovery_engine import get_by_collection

    session = collection_db.get_session()
    try:
        cards = get_by_collection(session, "Apple+ Kids", limit=50)
    finally:
        session.close()

    assert len(cards) == 8
    assert any(c.title.startswith("hidden_akids") for c in cards)


# ---------------------------------------------------------------------------
# fetch_cards_for_key dispatch (discover_workers.py control-layer seam)
# ---------------------------------------------------------------------------

def test_fetch_cards_for_key_routes_collection_prefix(collection_db):
    from metatv.gui.discover_workers import fetch_cards_for_key
    from metatv.core.config import Config

    excl_ids = _hidden_provider_ids(collection_db)
    session = collection_db.get_session()
    try:
        config = Config()
        cards = fetch_cards_for_key(
            session, config, "collection:Apple+ Kids", 50,
            sk={}, fk={}, af={}, ek={"excluded_provider_ids": excl_ids},
        )
    finally:
        session.close()

    assert len(cards) == 3
    assert all(c.title.startswith("akids") for c in cards)


def test_fetch_cards_for_key_unknown_collection_returns_empty(collection_db):
    from metatv.gui.discover_workers import fetch_cards_for_key
    from metatv.core.config import Config

    session = collection_db.get_session()
    try:
        config = Config()
        cards = fetch_cards_for_key(
            session, config, "collection:Nonexistent Shelf", 50,
            sk={}, fk={}, af={}, ek={},
        )
    finally:
        session.close()

    assert cards == []
