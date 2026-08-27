"""The channel list must show the poster the provider already gave us.

Owner report: "posters are still not loading for search results", with a
screenshot of a search for "castle" — 52 rows, three posters, the rest letter
tiles.

Measured on that library, and the two numbers are the whole bug:

    movie/series rows                 416,976
      with an enriched metadata poster  2,073   (0.5%)  <- all the list read
      with a provider poster stored   325,209  (78.0%)  <- what it ignored

Split by type it is worse, and in two different ways:

    movie   334,451   logo_url stored  325,209  (97.2%)
    series   82,525   logo_url stored        0  ( 0.0%)

So movies had a poster in a column nobody queried, and series had none stored at
all because ingestion mapped ``stream_icon`` — which is where MOVIES put it.
Series put it in ``cover``.
"""

from __future__ import annotations

import uuid

import pytest

from metatv.core.database import ChannelDB, Database, MetadataDB, ProviderDB
from metatv.core.discovery_engine import poster_url_from_raw
from metatv.core.repositories.channel import ChannelRepository


@pytest.fixture
def repo(tmp_path):
    db = Database(f"sqlite:///{tmp_path}/posters.db")
    db.create_tables()
    session = db.get_session()
    session.add(ProviderDB(id="p1", name="S", type="xtream", url="u",
                           is_active=True, account_status="Active"))
    session.commit()
    yield ChannelRepository(session), session
    session.close()
    db.close()


def _add(session, name, *, media_type="movie", logo_url=None, meta_poster=None):
    metadata_id = None
    if meta_poster is not None:
        metadata_id = str(uuid.uuid4())
        session.add(MetadataDB(id=metadata_id, title=name, poster_url=meta_poster))
    ch = ChannelDB(
        id=str(uuid.uuid4()), source_id=str(uuid.uuid4()), provider_id="p1",
        name=name, media_type=media_type, is_hidden=False, detected_title=name,
        logo_url=logo_url, metadata_id=metadata_id,
    )
    session.add(ch)
    session.commit()
    return ch.id


def _poster_of(repo_, cid):
    from metatv.core.repositories.dtos import ChannelListDTO
    for ch in repo_.get_all(limit=50):
        if ch.id == cid:
            return ChannelListDTO.from_orm(ch).poster_url
    raise AssertionError("channel not returned by get_all")


def test_a_provider_poster_reaches_the_list_without_enrichment(repo):
    """97% of movies had this and showed a letter tile instead."""
    repo_, session = repo
    cid = _add(session, "Castle Falls", logo_url="http://cdn/castle-falls.jpg")

    assert _poster_of(repo_, cid) == "http://cdn/castle-falls.jpg", (
        "the poster stored at ingestion never reached the list"
    )


def test_enriched_metadata_still_wins(repo):
    """The better poster must keep priority — this is a fallback, not a swap."""
    repo_, session = repo
    cid = _add(session, "Arendelle Castle Yule Log",
               logo_url="http://cdn/provider.jpg",
               meta_poster="http://tmdb/enriched.jpg")

    assert _poster_of(repo_, cid) == "http://tmdb/enriched.jpg"


def test_an_empty_metadata_poster_falls_through(repo):
    """A metadata row can exist with an EMPTY poster; that must not win.

    COALESCE alone returns '' here, because '' is not NULL — which would have
    left exactly the rows that have a metadata row but no poster still blank.
    """
    repo_, session = repo
    cid = _add(session, "Castle Rock", logo_url="http://cdn/rock.jpg", meta_poster="")

    assert _poster_of(repo_, cid) == "http://cdn/rock.jpg"


def test_no_poster_anywhere_is_still_empty(repo):
    """The letter tile is correct when there genuinely is nothing."""
    repo_, session = repo
    cid = _add(session, "Obscure Castle")

    assert _poster_of(repo_, cid) == ""


class TestIngestionStoresBothKeys:
    """Series put the poster in `cover`; movies in `stream_icon`."""

    def test_series_cover_is_resolved(self):
        assert poster_url_from_raw({"cover": "http://cdn/series.jpg"}) == "http://cdn/series.jpg"

    def test_movie_stream_icon_is_resolved(self):
        assert poster_url_from_raw({"stream_icon": "http://cdn/movie.jpg"}) == "http://cdn/movie.jpg"

    def test_stream_icon_wins_when_both_are_present(self):
        assert poster_url_from_raw(
            {"stream_icon": "http://cdn/a.jpg", "cover": "http://cdn/b.jpg"}
        ) == "http://cdn/a.jpg"

    def test_double_slashes_are_collapsed_but_the_scheme_survives(self):
        assert poster_url_from_raw({"cover": "https://cdn//movies//x.jpg"}) == "https://cdn/movies/x.jpg"

    def test_nothing_shipped_is_none(self):
        assert poster_url_from_raw({}) is None
        assert poster_url_from_raw(None) is None
        assert poster_url_from_raw({"cover": "   "}) is None

    def test_the_xtream_parser_stores_a_series_poster(self):
        """The end of the ingestion path, not just the helper.

        This is the assertion that would have caught the bug: every series row
        in the owner's library had an empty ``logo_url`` while its raw record
        carried a perfectly good ``cover``.
        """
        from metatv.core.models import MediaType
        from metatv.providers.xtream import XtreamAPI

        api = XtreamAPI("http://x.example.com", "user", "pass")
        raw = {"series_id": 7, "name": "Castle Rock", "cover": "http://cdn//rock.jpg"}
        channel = api.convert_to_channel(raw, "p1", MediaType.SERIES)

        assert channel.logo_url == "http://cdn/rock.jpg", (
            "a series poster from `cover` never reached ChannelDB.logo_url"
        )

    def test_the_xtream_parser_still_stores_a_movie_poster(self):
        """The path that already worked must keep working."""
        from metatv.core.models import MediaType
        from metatv.providers.xtream import XtreamAPI

        api = XtreamAPI("http://x.example.com", "user", "pass")
        raw = {"stream_id": 9, "name": "Castle Falls", "stream_icon": "http://cdn/falls.jpg"}
        channel = api.convert_to_channel(raw, "p1", MediaType.MOVIE)

        assert channel.logo_url == "http://cdn/falls.jpg"


class TestPosterBackfill:
    """Existing rows must not have to wait for a full catalog refresh."""

    def _db(self, tmp_path):
        from metatv.core.database import Database
        db = Database(f"sqlite:///{tmp_path}/backfill.db")
        db.create_tables()
        return db

    def _seed(self, db, rows):
        with db.session_scope() as session:
            session.add(ProviderDB(id="p1", name="S", type="xtream", url="u",
                                   is_active=True, account_status="Active"))
            for i, (mt, raw, logo) in enumerate(rows):
                session.add(ChannelDB(
                    id=f"c{i}", source_id=str(i), provider_id="p1", name=f"n{i}",
                    media_type=mt, is_hidden=False, logo_url=logo, raw_data=raw,
                ))

    def test_a_series_poster_is_restored_from_stored_raw_data(self, tmp_path):
        """82,525 rows in the owner's library are exactly this shape."""
        from metatv.core.migrations.poster_backfill import PosterBackfillTask
        db = self._db(tmp_path)
        self._seed(db, [("series", {"cover": "http://cdn//rock.jpg"}, None)])
        task = PosterBackfillTask(db)

        assert task.needs_run(None) is True
        task.run(lambda d, t: None, lambda: False)

        with db.session_scope() as session:
            assert session.get(ChannelDB, "c0").logo_url == "http://cdn/rock.jpg"
        assert task.needs_run(None) is False, "a completed backfill must not re-run"
        db.close()

    def test_an_existing_poster_is_left_alone(self, tmp_path):
        """The backfill fills gaps; it must never overwrite."""
        from metatv.core.migrations.poster_backfill import PosterBackfillTask
        db = self._db(tmp_path)
        self._seed(db, [("movie", {"stream_icon": "http://cdn/new.jpg"}, "http://cdn/kept.jpg")])

        PosterBackfillTask(db).run(lambda d, t: None, lambda: False)

        with db.session_scope() as session:
            assert session.get(ChannelDB, "c0").logo_url == "http://cdn/kept.jpg"
        db.close()

    def test_a_barren_row_does_not_stop_the_rows_after_it(self, tmp_path):
        """The bug the real library exposed, and the reason for the cursor.

        The SQL pre-filter matches the KEY; only poster_url_from_raw can say
        whether the VALUE is usable, and two thirds of matching rows hold an
        empty one (`"stream_icon": ""` — 4,027 of the first 6,000 measured).
        Those stay candidates forever, so a cursor-less LIMIT re-selects them,
        and the first version aborted the whole run on the first batch that
        held only barren rows — 1,972 posters restored out of 82,525.

        c0 is barren and sorts FIRST, so a run that stops on it never reaches c1.
        """
        from metatv.core.migrations.poster_backfill import PosterBackfillTask
        db = self._db(tmp_path)
        self._seed(db, [
            ("series", {"cover": "   "}, None),                 # c0 — barren
            ("series", {"cover": "http://cdn/good.jpg"}, None),  # c1 — usable
        ])

        PosterBackfillTask(db).run(lambda d, t: None, lambda: False)

        with db.session_scope() as session:
            assert not session.get(ChannelDB, "c0").logo_url, "barren row must stay empty"
            assert session.get(ChannelDB, "c1").logo_url == "http://cdn/good.jpg", (
                "the row after a barren one was never reached"
            )
        db.close()

    def test_the_run_terminates_when_every_row_is_barren(self, tmp_path):
        """No usable poster anywhere must still finish rather than spin."""
        from metatv.core.migrations.poster_backfill import PosterBackfillTask
        db = self._db(tmp_path)
        self._seed(db, [("movie", {"stream_icon": ""}, None) for _ in range(3)])

        PosterBackfillTask(db).run(lambda d, t: None, lambda: False)  # must return

        with db.session_scope() as session:
            assert not session.get(ChannelDB, "c0").logo_url
        db.close()
