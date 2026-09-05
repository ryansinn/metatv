"""Behavioral tests for DB-4 — Discover shelves read stored, indexed rating/added.

``get_top_rated``/``get_recently_added`` (and every other rating-sorted Discover
shelf) used to sort/filter with
``json_extract(channels.raw_data, '$.rating'/'$.added')`` evaluated per row over
785k+ rows (1.1-1.9s per shelf, measured). Both are now stored,
ingestion-computed, indexed columns — ``ChannelDB.detected_rating``/
``detected_added``, populated by ``content_identity.rating_from_raw``/
``added_from_raw`` (same shape/placement as ``valid_tmdb_id``).

Covers:
  1. The parsers: unparsable/empty -> None; a real value stores AS-IS (no 0-10
     clamp — the shelf queries keep their own ``< 10``/``>= min`` predicates).
  2. Ingestion (``XtreamAPI.convert_to_channel``) captures both from raw_data.
  3. The Discover shelf queries sort by the STORED column, not raw_data —
     proven with rows whose stored column disagrees with what raw_data alone
     would imply. This is the case that fails against the pre-fix
     json_extract() code (confirmed with ``git stash`` — see PR description).

All DB tests use file-backed (tmp_path) SQLite — never :memory:.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from metatv.core.content_identity import added_from_raw, rating_from_raw


# ---------------------------------------------------------------------------
# 1. Parsers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("7.4", 7.4),
    (7.4, 7.4),
    (7, 7.0),
    ("0", 0.0),
    ("", None),
    (None, None),
    ("garbage", None),
    ("  8.1 ", 8.1),
])
def test_rating_from_raw(raw, expected):
    assert rating_from_raw(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("1725500000", 1725500000),
    (1725500000, 1725500000),
    ("1725500000.0", 1725500000),
    ("", None),
    (None, None),
    ("not-a-number", None),
])
def test_added_from_raw(raw, expected):
    assert added_from_raw(raw) == expected


def test_rating_from_raw_stores_the_float_as_is_not_clamped():
    """Unlike ``provider_metadata._parse_rating`` (the MetadataDB display
    field, clamped to 0-10), this stores exactly what the provider sent — the
    Discover queries carry their own ``< 10`` sentinel filter and ``>=
    min_rating`` floor, so clamping here would hide that distinction from them.
    """
    assert rating_from_raw("10") == 10.0   # Xtream's "no rating" sentinel — not clamped away here
    assert rating_from_raw("-1") == -1.0
    assert rating_from_raw("15") == 15.0


# ---------------------------------------------------------------------------
# 2. Ingestion — XtreamAPI.convert_to_channel
# ---------------------------------------------------------------------------

class TestConvertToChannelCapturesRatingAndAdded:
    def _api(self):
        from metatv.providers.xtream import XtreamAPI
        return XtreamAPI("http://host:8080", "user", "pass")

    def test_captures_valid_rating_and_added(self):
        api = self._api()
        ch = api.convert_to_channel(
            {"stream_id": "7", "name": "A Movie", "rating": "7.4", "added": "1725500000"},
            provider_id="p1", media_type="movie",
        )
        assert ch.detected_rating == 7.4
        assert ch.detected_added == 1725500000

    def test_empty_and_garbage_become_none(self):
        api = self._api()
        ch = api.convert_to_channel(
            {"stream_id": "8", "name": "Junk", "rating": "", "added": "garbage"},
            provider_id="p1", media_type="movie",
        )
        assert ch.detected_rating is None
        assert ch.detected_added is None

    def test_missing_fields_become_none(self):
        api = self._api()
        ch = api.convert_to_channel(
            {"stream_id": "9", "name": "No Fields"},
            provider_id="p1", media_type="movie",
        )
        assert ch.detected_rating is None
        assert ch.detected_added is None


# ---------------------------------------------------------------------------
# 3. Discover shelf queries — sort by the stored column, not raw_data
# ---------------------------------------------------------------------------

def _make_db(tmp_path: Path):
    from metatv.core.database import Database
    db = Database(f"sqlite:///{tmp_path / 'db4_shelf_test.db'}")
    db.create_tables()
    return db


def _add_provider(session, pid: str = "p1") -> None:
    from metatv.core.database import ProviderDB
    session.add(ProviderDB(
        id=pid, name=pid, type="xtream",
        url="http://example.com", username="u", password="p",
        is_active=True,
    ))
    session.flush()


def _add_channel(session, cid, name, provider_id, *, media_type="movie", raw_data=None, **kwargs):
    from metatv.core.database import ChannelDB
    session.add(ChannelDB(
        id=cid, source_id=cid, provider_id=provider_id, name=name,
        media_type=media_type, is_hidden=False, raw_data=raw_data or {}, **kwargs,
    ))
    session.flush()


class TestShelfQueriesReadStoredColumns:
    """Rows below deliberately disagree between raw_data and the stored
    column — the query result proves WHICH one the code actually reads.
    Against the pre-fix json_extract()-based query these both go RED
    (order flips), which is what the PR's ``git stash`` check confirmed.
    """

    def test_get_top_rated_orders_by_stored_column(self, tmp_path):
        db = _make_db(tmp_path)
        with db.session_scope() as session:
            _add_provider(session)
            _add_channel(session, "ch-a", "Movie A", "p1",
                         raw_data={"rating": "9.0"}, detected_rating=2.0)
            _add_channel(session, "ch-b", "Movie B", "p1",
                         raw_data={"rating": "2.0"}, detected_rating=9.0)

        with db.session_scope(commit=False) as session:
            from metatv.core.discovery_engine import get_top_rated
            cards = get_top_rated(session, media_type="movie", limit=10, min_rating=0)

        assert [c.title for c in cards] == ["Movie B", "Movie A"], (
            "must order by the stored detected_rating column, not raw_data['rating']"
        )
        db.close()

    def test_get_recently_added_orders_by_stored_column(self, tmp_path):
        db = _make_db(tmp_path)
        with db.session_scope() as session:
            _add_provider(session)
            _add_channel(session, "ch-a", "Movie A", "p1",
                         raw_data={"added": "2000000000"}, detected_added=1000000000)
            _add_channel(session, "ch-b", "Movie B", "p1",
                         raw_data={"added": "1000000000"}, detected_added=2000000000)

        with db.session_scope(commit=False) as session:
            from metatv.core.discovery_engine import get_recently_added
            cards = get_recently_added(session, limit=10)

        assert [c.title for c in cards] == ["Movie B", "Movie A"], (
            "must order by the stored detected_added column, not raw_data['added']"
        )
        db.close()

    def test_get_top_rated_rating_predicate_reads_stored_column(self, tmp_path):
        """A row whose raw_data implies a passing rating but whose STORED
        column is below the floor must be excluded (and vice versa)."""
        db = _make_db(tmp_path)
        with db.session_scope() as session:
            _add_provider(session)
            _add_channel(session, "ch-below", "Below Floor", "p1",
                         raw_data={"rating": "9.0"}, detected_rating=1.0)
            _add_channel(session, "ch-above", "Above Floor", "p1",
                         raw_data={"rating": "1.0"}, detected_rating=9.0)

        with db.session_scope(commit=False) as session:
            from metatv.core.discovery_engine import get_top_rated
            cards = get_top_rated(session, media_type="movie", limit=10, min_rating=5.0)

        assert [c.title for c in cards] == ["Above Floor"], (
            "min_rating must filter on the stored detected_rating column"
        )
        db.close()

    def test_to_card_rating_reads_stored_column(self, tmp_path):
        """``_to_card`` (the shared card builder) must not fall back to
        parsing raw_data — the None case matters as much as the value case."""
        db = _make_db(tmp_path)
        with db.session_scope() as session:
            _add_provider(session)
            _add_channel(session, "ch-a", "Has Raw Rating Only", "p1",
                         raw_data={"rating": "8.0"})   # detected_rating left NULL

        with db.session_scope(commit=False) as session:
            from metatv.core.database import ChannelDB
            from metatv.core.discovery_engine import _to_card
            channel = session.query(ChannelDB).filter_by(id="ch-a").one()
            card = _to_card(channel)

        assert card.rating is None, (
            "an un-backfilled row (detected_rating NULL) must render no "
            "rating, even though raw_data carries one — compute once at "
            "ingestion, read everywhere else"
        )
        db.close()
