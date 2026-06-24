"""Behavioral tests for Discover-shelf + details Other-Versions dedup on content_key.

Slice 3 of the content-identity dedup plan.  Guards the following invariants:

A1. ``_dedup_cards`` groups cards with the SAME content_key → 1 representative.
A2. ``variant_count`` on the representative == len(group).
A3. Representative is the highest-rated card; ties broken by lowest channel_id.
A4. Cards with DISTINCT content_keys are NOT merged.
A5. Two cards with content_key=None but different channel_ids are NOT merged
    (id: fallback prevents mass-collapse of un-backfilled rows).
A6. Shelf ordering is preserved — the representative keeps the group's original
    first-seen position even when a later card outranks it.
B1. ``get_recently_added`` returns one card for 2 channels sharing content_key
    and the distinct 3rd channel separately (variant_count correct on both).
B2. ``_bg_fetch_versions`` — content_key path returns all 3 rows sharing a key
    and excludes a 4th row with a different key.
B3. ``_bg_fetch_versions`` — null-key fallback path uses normalize_title matching
    (rows with no content_key still group via name normalization).
B4. Existing provider-scoping is preserved in the content_key path (variant on
    a disabled provider is excluded even when content_key matches).

All DB tests use file-backed (tmp_path) SQLite — NOT :memory: (pooled
connections each see an empty schema there).
"""

from __future__ import annotations

import concurrent.futures
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(tmp_path: Path):
    from metatv.core.database import Database
    db = Database(f"sqlite:///{tmp_path / 'ck_dedup_test.db'}")
    db.create_tables()
    return db


def _add_provider(session, pid, *, is_active: bool = True):
    from metatv.core.database import ProviderDB
    session.add(ProviderDB(
        id=pid, name=pid, type="xtream",
        url="http://example.com", username="u", password="p",
        is_active=is_active,
    ))
    session.flush()


def _add_channel(session, cid, name, provider_id, *,
                 media_type: str = "movie",
                 content_key: str | None = None,
                 detected_prefix: str | None = None,
                 detected_title: str | None = None,
                 raw_data: dict | None = None,
                 **kwargs):
    from metatv.core.database import ChannelDB
    session.add(ChannelDB(
        id=cid,
        source_id=cid,
        provider_id=provider_id,
        name=name,
        media_type=media_type,
        content_key=content_key,
        detected_prefix=detected_prefix,
        detected_title=detected_title,
        raw_data=raw_data or {},
        **kwargs,
    ))
    session.flush()


# ---------------------------------------------------------------------------
# Part A — _dedup_cards unit tests
# ---------------------------------------------------------------------------

class TestDedupCardsContentKey:
    """_dedup_cards must group on stored content_key and set variant_count."""

    def _make_card(self, channel_id: str, content_key: str | None,
                   rating: float | None = None) -> "ContentCard":
        from metatv.core.discovery_engine import ContentCard
        return ContentCard(
            channel_id=channel_id,
            title="Test Title",
            media_type="movie",
            thumbnail_url=None,
            rating=rating,
            year=2020,
            genre="Drama",
            content_key=content_key,
        )

    def test_same_content_key_collapses_to_one_card(self):
        """3 cards with the same content_key → 1 card after dedup."""
        from metatv.core.discovery_engine import _dedup_cards
        key = "dark star|movie|2017"
        cards = [
            self._make_card("ch-1", key, rating=8.0),
            self._make_card("ch-2", key, rating=7.0),
            self._make_card("ch-3", key, rating=6.0),
        ]
        result = _dedup_cards(cards)
        assert len(result) == 1, f"Expected 1 collapsed card, got {len(result)}"

    def test_variant_count_equals_group_size(self):
        """variant_count on the representative must equal 3."""
        from metatv.core.discovery_engine import _dedup_cards
        key = "dark star|movie|2017"
        cards = [
            self._make_card("ch-a", key, rating=9.0),
            self._make_card("ch-b", key, rating=7.0),
            self._make_card("ch-c", key, rating=5.0),
        ]
        result = _dedup_cards(cards)
        assert result[0].variant_count == 3, (
            f"Expected variant_count=3, got {result[0].variant_count}"
        )

    def test_representative_is_highest_rated(self):
        """Representative must be the card with the highest rating."""
        from metatv.core.discovery_engine import _dedup_cards
        key = "dark star|movie|2017"
        cards = [
            self._make_card("ch-low",  key, rating=5.0),
            self._make_card("ch-high", key, rating=9.5),
            self._make_card("ch-mid",  key, rating=7.0),
        ]
        result = _dedup_cards(cards)
        assert len(result) == 1
        assert result[0].channel_id == "ch-high", (
            f"Expected 'ch-high' as representative, got {result[0].channel_id!r}"
        )

    def test_rating_none_treated_as_minus_one(self):
        """A card with rating=None loses to any card with a real rating."""
        from metatv.core.discovery_engine import _dedup_cards
        key = "alpha|movie|2020"
        cards = [
            self._make_card("ch-none", key, rating=None),
            self._make_card("ch-low",  key, rating=0.1),
        ]
        result = _dedup_cards(cards)
        assert result[0].channel_id == "ch-low", (
            f"A real (low) rating must beat None; got {result[0].channel_id!r}"
        )

    def test_tiebreaker_lowest_channel_id(self):
        """When ratings are equal the lowest channel_id wins."""
        from metatv.core.discovery_engine import _dedup_cards
        key = "beta|movie|2021"
        cards = [
            self._make_card("ch-z", key, rating=8.0),
            self._make_card("ch-a", key, rating=8.0),
            self._make_card("ch-m", key, rating=8.0),
        ]
        result = _dedup_cards(cards)
        assert result[0].channel_id == "ch-a", (
            f"Expected lowest channel_id 'ch-a'; got {result[0].channel_id!r}"
        )

    def test_distinct_keys_not_merged(self):
        """Cards with different content_keys must NOT be merged."""
        from metatv.core.discovery_engine import _dedup_cards
        cards = [
            self._make_card("ch-1", "alpha|movie|2020", rating=8.0),
            self._make_card("ch-2", "beta|movie|2020",  rating=7.0),
            self._make_card("ch-3", "gamma|movie|2019", rating=9.0),
        ]
        result = _dedup_cards(cards)
        assert len(result) == 3, (
            f"Distinct content_keys must not be merged; got {len(result)} cards"
        )
        for card in result:
            assert card.variant_count == 1

    def test_null_content_key_cards_not_merged(self):
        """Two cards with content_key=None and different channel_ids are NOT merged."""
        from metatv.core.discovery_engine import _dedup_cards
        cards = [
            self._make_card("ch-null-1", None, rating=8.0),
            self._make_card("ch-null-2", None, rating=7.0),
        ]
        result = _dedup_cards(cards)
        assert len(result) == 2, (
            "Two None-key cards with different channel_ids must remain separate"
        )
        for card in result:
            assert card.variant_count == 1

    def test_shelf_order_preserved_when_later_card_wins(self):
        """Group keeps original first-seen position even when a later card outranks it."""
        from metatv.core.discovery_engine import ContentCard, _dedup_cards
        key_a = "alpha|movie|2020"
        key_b = "beta|movie|2021"
        # alpha appears at position 0, beta at 1.
        # Within alpha, ch-later (rating 9.5) comes after ch-first (rating 5.0).
        cards = [
            self._make_card("ch-first-a",  key_a, rating=5.0),   # first alpha
            self._make_card("ch-first-b",  key_b, rating=8.0),   # first beta
            self._make_card("ch-later-a",  key_a, rating=9.5),   # later alpha — should win
        ]
        result = _dedup_cards(cards)
        # Two groups → 2 results
        assert len(result) == 2
        # First result must be the alpha group (original insertion position 0)
        assert result[0].channel_id == "ch-later-a", (
            "alpha group representative must be ch-later-a (higher rating)"
        )
        assert result[0].variant_count == 2
        # Second result must be beta
        assert result[1].channel_id == "ch-first-b"
        assert result[1].variant_count == 1


# ---------------------------------------------------------------------------
# Part B1 — shelf end-to-end with content_key dedup
# ---------------------------------------------------------------------------

class TestGetRecentlyAddedContentKeyDedup:
    """get_recently_added collapses same-content_key rows into one card."""

    def test_two_shared_key_collapse_distinct_stays(self, tmp_path):
        """2 channels sharing a content_key collapse to 1; a distinct 3rd is separate."""
        db = _make_db(tmp_path)

        with db.session_scope() as session:
            _add_provider(session, "p1")
            key = "dark star|movie|2017"
            _add_channel(
                session, "ch-a", "EN Dark Star (2017)", "p1",
                content_key=key,
                raw_data={"rating": "8.5", "added": "1700000002"},
            )
            _add_channel(
                session, "ch-b", "FR Dark Star (2017)", "p1",
                content_key=key,
                raw_data={"rating": "7.0", "added": "1700000001"},
            )
            # Distinct production
            _add_channel(
                session, "ch-c", "Another Movie", "p1",
                content_key="another movie|movie|",
                raw_data={"rating": "6.0", "added": "1700000000"},
            )

        with db.session_scope(commit=False) as session:
            from metatv.core.discovery_engine import get_recently_added
            cards = get_recently_added(session, limit=30)

        assert len(cards) == 2, (
            f"Expected 2 collapsed cards (1 group + 1 distinct), got {len(cards)}"
        )

        # The dark star group should have variant_count==2
        dark_star_cards = [c for c in cards if "dark star" in (c.content_key or "")]
        assert len(dark_star_cards) == 1
        assert dark_star_cards[0].variant_count == 2, (
            f"Expected variant_count=2 for dark star group; got {dark_star_cards[0].variant_count}"
        )
        # The distinct card should have variant_count==1
        other_cards = [c for c in cards if "another" in (c.content_key or "")]
        assert len(other_cards) == 1
        assert other_cards[0].variant_count == 1

        db.close()

    def test_null_key_rows_each_stay_separate(self, tmp_path):
        """Two channels with content_key=None remain separate cards (no mass-collapse)."""
        db = _make_db(tmp_path)

        with db.session_scope() as session:
            _add_provider(session, "p1")
            _add_channel(
                session, "ch-null-a", "Unknown Alpha", "p1",
                content_key=None,
                raw_data={"rating": "7.0", "added": "1700000002"},
            )
            _add_channel(
                session, "ch-null-b", "Unknown Beta", "p1",
                content_key=None,
                raw_data={"rating": "6.0", "added": "1700000001"},
            )

        with db.session_scope(commit=False) as session:
            from metatv.core.discovery_engine import get_recently_added
            cards = get_recently_added(session, limit=30)

        assert len(cards) == 2, (
            f"Two None-key channels must remain separate; got {len(cards)} cards"
        )
        for card in cards:
            assert card.variant_count == 1

        db.close()


# ---------------------------------------------------------------------------
# Part B2 — _bg_fetch_versions: content_key primary path
# ---------------------------------------------------------------------------

class TestBgFetchVersionsContentKeyPath:
    """_bg_fetch_versions uses content_key when set to find all matching variants."""

    def _fake_config(self):
        return SimpleNamespace(
            global_filter_paused=False,
            global_filter_excluded_categories=[],
            global_filter_excluded_prefixes=[],
            preferred_version_prefixes=[],
            preferred_version_provider_ids=[],
            preferred_version_quality=None,
        )

    def _make_mixin(self, db):
        from metatv.gui.main_window_metadata import _MetadataMixin

        emitted: list[tuple] = []

        class _FakeSignal:
            def emit(self, cid, vs):
                emitted.append((cid, vs))

        obj = _MetadataMixin.__new__(_MetadataMixin)
        obj.db = db
        obj.config = self._fake_config()
        obj._versions_loaded = _FakeSignal()
        obj._emitted = emitted
        return obj

    def test_three_shared_key_all_returned(self, tmp_path):
        """3 rows sharing a content_key → all 3 are returned as versions (minus the current)."""
        db = _make_db(tmp_path)

        with db.session_scope() as session:
            _add_provider(session, "p1")
            _add_provider(session, "p2")
            _add_provider(session, "p3")
            key = "dark star|movie|2017"
            _add_channel(session, "ch-main", "EN Dark Star (2017)", "p1",
                         content_key=key, detected_prefix="EN")
            _add_channel(session, "ch-fr",   "FR Dark Star (2017)", "p2",
                         content_key=key, detected_prefix="FR")
            _add_channel(session, "ch-de",   "DE Dark Star (2017)", "p3",
                         content_key=key, detected_prefix="DE")
            # Different key — must NOT appear
            _add_channel(session, "ch-other", "Other Movie", "p1",
                         content_key="other movie|movie|2020")

        obj = self._make_mixin(db)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(obj._bg_fetch_versions, "ch-main").result(timeout=10)

        assert obj._emitted, "No versions signal was emitted"
        _, versions = obj._emitted[0]
        version_ids = {v.channel_id for v in versions}

        assert "ch-fr" in version_ids, "FR variant with same content_key must appear"
        assert "ch-de" in version_ids, "DE variant with same content_key must appear"
        assert "ch-other" not in version_ids, "Different content_key must be excluded"
        assert len(version_ids) == 2, (
            f"Expected 2 versions (ch-fr, ch-de), got {len(version_ids)}: {version_ids}"
        )

        db.close()

    def test_disabled_provider_excluded_in_content_key_path(self, tmp_path):
        """Even with a matching content_key, a variant on a disabled provider is excluded."""
        db = _make_db(tmp_path)

        with db.session_scope() as session:
            _add_provider(session, "p-active",   is_active=True)
            _add_provider(session, "p-disabled", is_active=False)
            key = "dark star|movie|2017"
            _add_channel(session, "ch-main", "EN Dark Star (2017)", "p-active",
                         content_key=key, detected_prefix="EN")
            _add_channel(session, "ch-ok",   "FR Dark Star (2017)", "p-active",
                         content_key=key, detected_prefix="FR")
            _add_channel(session, "ch-dead", "4K Dark Star (2017)", "p-disabled",
                         content_key=key, detected_prefix="4K")

        obj = self._make_mixin(db)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(obj._bg_fetch_versions, "ch-main").result(timeout=10)

        assert obj._emitted
        _, versions = obj._emitted[0]
        version_ids = {v.channel_id for v in versions}

        assert "ch-dead" not in version_ids, (
            "Variant on disabled provider must be excluded even when content_key matches"
        )
        assert "ch-ok" in version_ids, "Active-provider variant must still appear"

        db.close()


# ---------------------------------------------------------------------------
# Part B3 — _bg_fetch_versions: null-key fallback (normalize_title path)
# ---------------------------------------------------------------------------

class TestBgFetchVersionsNullKeyFallback:
    """When content_key is None the fallback uses normalize_title matching."""

    def _fake_config(self):
        return SimpleNamespace(
            global_filter_paused=False,
            global_filter_excluded_categories=[],
            global_filter_excluded_prefixes=[],
            preferred_version_prefixes=[],
            preferred_version_provider_ids=[],
            preferred_version_quality=None,
        )

    def _make_mixin(self, db):
        from metatv.gui.main_window_metadata import _MetadataMixin

        emitted: list[tuple] = []

        class _FakeSignal:
            def emit(self, cid, vs):
                emitted.append((cid, vs))

        obj = _MetadataMixin.__new__(_MetadataMixin)
        obj.db = db
        obj.config = self._fake_config()
        obj._versions_loaded = _FakeSignal()
        obj._emitted = emitted
        return obj

    def test_null_key_rows_use_normalize_title(self, tmp_path):
        """Channels with content_key=None still group via normalize_title matching."""
        db = _make_db(tmp_path)

        with db.session_scope() as session:
            _add_provider(session, "p1")
            _add_provider(session, "p2")
            # No content_key on these rows (simulates pre-backfill state)
            _add_channel(session, "ch-main",  "EN The Matrix (1999)", "p1",
                         content_key=None, detected_prefix="EN", media_type="movie")
            _add_channel(session, "ch-match", "FR The Matrix (1999)", "p2",
                         content_key=None, detected_prefix="FR", media_type="movie")
            # Different title — must NOT appear
            _add_channel(session, "ch-other", "EN Inception (2010)", "p1",
                         content_key=None, detected_prefix="EN", media_type="movie")

        obj = self._make_mixin(db)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(obj._bg_fetch_versions, "ch-main").result(timeout=10)

        assert obj._emitted, "No versions signal was emitted"
        _, versions = obj._emitted[0]
        version_ids = {v.channel_id for v in versions}

        assert "ch-match" in version_ids, (
            "Same-normalized-title null-key channel must appear in versions"
        )
        assert "ch-other" not in version_ids, (
            "Different-title null-key channel must NOT appear"
        )

        db.close()
