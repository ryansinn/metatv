"""Sibling propagation must not hold a cursor open across its own commit.

``_propagate_tmdb_from_title_siblings_impl`` streamed idless rows with
``yield_per`` and committed every 2,000 adoptions *inside* that loop. A commit
hands the connection back to the pool, and the pool CLOSES it when it was an
overflow connection — so the next fetch from the still-open cursor raises::

    sqlite3.ProgrammingError: Cannot operate on a closed database.

Six times in the owner's log, from ``channel_ingestion.py`` under
``_propagate_after_drain``, which catches it, logs it and abandons the pass::

    ERROR | tmdb_enrichment_manager:_propagate_after_drain:384 -
    tmdb_enrich: post-drain sibling propagation failed

The cost is not the traceback. Propagation is what collapses a title's variants
onto one ``content_key`` — what "Other Versions" and cross-source dedup read —
and the owner's library has 237,490 idless VOD rows. A pass that dies at the
first batch boundary adopts 2,000 of them and stops.

WHY NullPool
------------
Whether a commit kills the cursor is a property of POOL STATE, not of the loop:
a returned connection is closed only when it was an overflow connection. The
pass runs on a worker thread beside the EPG fetch, the series monitor and the
UI, so in the app it usually is one — but a single-threaded test checks its
connection back into an empty pool, which keeps it open, and the bug does not
appear. ``NullPool`` closes on every release, which is precisely the state the
loop must survive and the one production keeps reaching. Without it this test
passes against the broken code.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from metatv.core.database import ChannelDB, Database, ProviderDB
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.tag import _clear_tag_cache

#: The loop commits at ``_BATCH`` = 2000 adoptions (channel_ingestion.py).
#: Enough titles to cross that boundary, and no more — the test pays for every
#: row it inserts.
_TITLES = 2_100


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    _clear_tag_cache()
    url = f"sqlite:///{tmp_path / 'prop.db'}"
    d = Database(url)
    d.create_tables()
    with d.session_scope() as session:
        session.add(ProviderDB(id="p1", name="P", type="xtream", url="http://x",
                               username="u", password="p", is_active=True))
        rows = []
        for i in range(_TITLES):
            title = f"Picture Number {i}"
            # One id-bearing row and one idless row per title, so every idless
            # row has exactly one unambiguous sibling and adoption is certain.
            for tmdb in (str(700000 + i), None):
                rows.append({
                    "id": str(uuid.uuid4()), "source_id": str(uuid.uuid4()),
                    "provider_id": "p1", "name": title, "detected_title": title,
                    "detected_year": "2019", "media_type": "movie",
                    "detected_tmdb_id": tmdb, "is_hidden": False,
                })
        session.bulk_insert_mappings(ChannelDB, rows)
    d.close()
    return url


@pytest.fixture()
def pressured_session(db_path: str):
    """A session whose connection is discarded on release — see WHY NullPool."""
    engine = create_engine(db_path, poolclass=NullPool,
                           connect_args={"check_same_thread": False})
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def test_a_pass_larger_than_one_batch_completes(pressured_session):
    """THE assertion. Pre-fix this raises ProgrammingError at the first commit."""
    adopted = RepositoryFactory(pressured_session).channels.\
        propagate_tmdb_from_title_siblings()

    assert adopted == _TITLES, (
        f"the pass adopted {adopted} of {_TITLES} — it stopped early, which is "
        "what committing inside the streaming loop does"
    )


def test_every_idless_row_carries_its_siblings_id_afterwards(pressured_session):
    """Completion is not enough: the writes must have survived the commits."""
    RepositoryFactory(pressured_session).channels.\
        propagate_tmdb_from_title_siblings()
    pressured_session.expire_all()

    stranded = (
        pressured_session.query(ChannelDB)
        .filter(ChannelDB.detected_tmdb_id.is_(None))
        .filter(ChannelDB.media_type == "movie")
        .count()
    )
    propagated = (
        pressured_session.query(ChannelDB)
        .filter(ChannelDB.tmdb_enrich_state == "propagated")
        .count()
    )

    assert stranded == 0, f"{stranded} rows never received their sibling's id"
    assert propagated == _TITLES, (
        f"{propagated} rows are marked propagated, expected {_TITLES}"
    )


def test_the_page_cursor_does_not_skip_rows(pressured_session):
    """Every adopted row is distinct — a paging bug would double-count.

    The loop writes the very column its own filter tests, so rows leave the
    result set while it runs. That is why the cursor is a keyset (``id >
    after``) and not an OFFSET, which would step over their neighbours.
    """
    adopted = RepositoryFactory(pressured_session).channels.\
        propagate_tmdb_from_title_siblings()
    pressured_session.expire_all()

    distinct = (
        pressured_session.query(ChannelDB.id)
        .filter(ChannelDB.tmdb_enrich_state == "propagated")
        .distinct()
        .count()
    )
    assert distinct == adopted == _TITLES, (
        f"adopted {adopted}, but {distinct} distinct rows are marked — the "
        "page cursor revisited or skipped rows"
    )
