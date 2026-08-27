"""Titles get a metadata baseline from data already on disk, without a fetch.

Metadata is fetched lazily, per title opened, so on the owner's library the
table covered 2,100 of 417,003 movie/series titles — half a percent — while
72,619 series already carried a plot in their stored ``raw_data``, along with
cast, genre, rating, release date and a TMDb poster. Anything querying the
table in BULK saw an almost-empty table; the channel list's plot line is blank
for 99.5% of rows for exactly this reason.

Measured after this task, on that library:

    metadata rows      2,146 -> 413,355
    with a plot        1,823 ->  73,861
    fetched_at stamped 2,146 ->   2,146   (unchanged)
"""

from __future__ import annotations

import uuid

import pytest

from metatv.core.database import ChannelDB, Database, MetadataDB, ProviderDB
from metatv.core.migrations.offline_metadata_backfill import OfflineMetadataBackfillTask

SERIES_RAW = {
    "plot": "With a documentary style delivery, this drama tells the story.",
    "cast": "Hugo Speer, Sharon Small",
    "genre": "Drama / Crime",
    "rating": "7",
    "releaseDate": "2019-02-25",
    "cover": "http://cdn/rock.jpg",
}


@pytest.fixture
def db(tmp_path):
    database = Database(f"sqlite:///{tmp_path}/meta.db")
    database.create_tables()
    with database.session_scope() as session:
        session.add(ProviderDB(id="p1", name="S", type="xtream", url="u",
                               is_active=True, account_status="Active"))
    yield database
    database.close()


def _add(db, cid, raw, *, media_type="series", metadata_id=None, detected_title=None):
    with db.session_scope() as session:
        session.add(ChannelDB(
            id=cid, source_id=str(uuid.uuid4()), provider_id="p1", name=cid,
            media_type=media_type, is_hidden=False, raw_data=raw,
            detected_title=detected_title, metadata_id=metadata_id,
        ))


def _run(db):
    OfflineMetadataBackfillTask(db).run(lambda d, t: None, lambda: False)


def test_a_series_gets_its_plot_cast_and_genre_from_raw_data(db):
    """The 72,619 rows that had all of this and no metadata row."""
    _add(db, "c1", SERIES_RAW, detected_title="London Kills")
    _run(db)

    with db.session_scope() as session:
        ch = session.get(ChannelDB, "c1")
        assert ch.metadata_id, "no metadata row was linked"
        meta = session.get(MetadataDB, ch.metadata_id)
        assert meta.plot.startswith("With a documentary")
        assert meta.genres == ["Drama", "Crime"]
        assert [c["name"] for c in meta.cast] == ["Hugo Speer", "Sharon Small"]
        assert meta.rating == 7.0
        assert meta.release_date == "2019-02-25"
        assert meta.poster_url == "http://cdn/rock.jpg"
        assert meta.title == "London Kills", "the ingestion-cleaned title should win"


def test_fetched_at_is_left_null_so_enrichment_still_upgrades(db):
    """THE assertion. The column carries ``default=datetime.now``.

    Omitting ``fetched_at`` does not leave it NULL — the default stamps it, and
    a stamped row stops being an enrichment candidate
    (``_metadata_enrichment_filter``). That would have marked 400,000 titles as
    fetched and permanently blocked the network pass from ever adding director,
    runtime or character names. The first version of this task did exactly that
    and the design read as correct.
    """
    _add(db, "c1", SERIES_RAW)
    _run(db)

    with db.session_scope() as session:
        ch = session.get(ChannelDB, "c1")
        meta = session.get(MetadataDB, ch.metadata_id)
        assert meta.fetched_at is None, (
            "fetched_at was stamped — these titles are now invisible to the "
            "enrichment queue and will never be upgraded"
        )


def test_an_existing_enriched_row_is_never_overwritten(db):
    """13 orphaned rows exist in the owner's library — real, enriched, unlinked.

    Adopting one is right; replacing its fetched plot with whatever raw_data
    holds is not. A source that knows less does not erase what is known.
    """
    with db.session_scope() as session:
        session.add(MetadataDB(id="meta_c1", title="Proper Title",
                               plot="A carefully fetched synopsis."))
    _add(db, "c1", SERIES_RAW)
    _run(db)

    with db.session_scope() as session:
        meta = session.get(MetadataDB, "meta_c1")
        assert meta.plot == "A carefully fetched synopsis.", "enriched plot was clobbered"
        assert meta.title == "Proper Title"
        # ...but empty fields on that row still get filled.
        assert meta.genres == ["Drama", "Crime"]


def test_an_adopted_row_keeps_its_fetched_at(db):
    """Clearing it would send a genuinely-fetched row back through the queue."""
    from datetime import datetime

    stamped = datetime(2026, 1, 1, 12, 0, 0)
    with db.session_scope() as session:
        session.add(MetadataDB(id="meta_c1", title="T", fetched_at=stamped))
    _add(db, "c1", SERIES_RAW)
    _run(db)

    with db.session_scope() as session:
        assert session.get(MetadataDB, "meta_c1").fetched_at == stamped


def test_a_title_that_already_has_metadata_is_not_a_candidate(db):
    """Only titles with NO row are touched."""
    with db.session_scope() as session:
        session.add(MetadataDB(id="m-existing", title="T"))
    _add(db, "c1", SERIES_RAW, metadata_id="m-existing")

    assert OfflineMetadataBackfillTask(db).needs_run(None) is False


def test_a_blob_with_nothing_usable_is_not_a_candidate(db):
    """Keys present with empty values must not keep needs_run True forever.

    The poster backfill's bug: the SQL filter matched the KEY, two thirds of
    rows held it empty, and the task could never reach zero.
    """
    _add(db, "c1", {"plot": "", "cover": "", "genre": "   "})

    assert OfflineMetadataBackfillTask(db).needs_run(None) is False


def test_running_twice_writes_nothing_the_second_time(db):
    """Interrupting must be safe, so repeating must be too."""
    _add(db, "c1", SERIES_RAW)
    task = OfflineMetadataBackfillTask(db)
    _run(db)
    assert task.needs_run(None) is False

    _run(db)  # must not raise on the row it already created
    with db.session_scope() as session:
        assert session.query(MetadataDB).count() == 1


def test_live_channels_are_left_alone(db):
    """A live channel's raw_data holds a station logo, not title metadata."""
    _add(db, "c1", {"stream_icon": "http://cdn/logo.png"}, media_type="live")

    assert OfflineMetadataBackfillTask(db).needs_run(None) is False
