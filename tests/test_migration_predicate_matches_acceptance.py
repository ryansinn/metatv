"""``needs_run`` must not offer work that ``run`` will refuse.

The task has two halves that answer the same question in different languages.
``needs_run`` asks it in SQL (``_CANDIDATES``); ``run`` asks it in Python
(``metadata_from_raw(...)`` returning a result with a title). Nothing forced
them to agree, and they drifted: one row in the owner's 417,003-title library
had ``name = ''``, no ``detected_title`` and ``rating = '0'`` — non-blank, so
the SQL admitted it; no title, so ``run`` skipped it and wrote nothing.

Because ``needs_run`` reads the data rather than a completion stamp, that row
re-armed the task at EVERY launch. The owner's own log shows it four launches
running::

    MigrationManager: queuing 1 task(s): ['offline_metadata_backfill']
    MigrationManager: task offline_metadata_backfill finished

- with the "migration in progress" notice each time, for a task that could
never finish. One row, forever.

The guard is the INVARIANT, not that row: **a completed run leaves nothing
pending.** Any future divergence between the two halves fails here, including
shapes nobody has thought of yet — which is the point, since the file's own
history is a list of shapes nobody thought of (a key present with an empty
value, an orphaned metadata row, a blob that parses to nothing).
"""

from __future__ import annotations

import uuid

import pytest

from metatv.core.database import ChannelDB, Database, ProviderDB
from metatv.core.migrations.offline_metadata_backfill import OfflineMetadataBackfillTask


@pytest.fixture
def db(tmp_path):
    database = Database(f"sqlite:///{tmp_path}/meta.db")
    database.create_tables()
    with database.session_scope() as session:
        session.add(ProviderDB(id="p1", name="S", type="xtream", url="u",
                               is_active=True, account_status="Active"))
    yield database
    database.close()


def _add(db, cid, raw, *, name, detected_title=None, media_type="movie"):
    with db.session_scope() as session:
        session.add(ChannelDB(
            id=cid, source_id=str(uuid.uuid4()), provider_id="p1", name=name,
            media_type=media_type, is_hidden=False, raw_data=raw,
            detected_title=detected_title,
        ))


# Every shape is one the SQL filter admits: each carries a non-blank value in
# at least one _HAS_SOMETHING key. They differ in whether a TITLE can be found,
# which is the axis the two halves disagreed on.
SHAPES = {
    "the owner's row: named nothing, rated '0'":
        ({"num": 1, "name": "", "stream_icon": "", "rating": "0"}, "", None),
    "no title anywhere, but a real plot":
        ({"plot": "Something happens.", "name": ""}, "", None),
    "title only in detected_title":
        ({"plot": "A plot.", "name": ""}, "", "The Cleaned Title"),
    "title only in the channel name":
        ({"rating": "7"}, "Some Movie (2019)", None),
    "title only inside info":
        ({"info": {"name": "Nested Title", "plot": "p"}}, "", None),
    "whitespace is not a title":
        ({"cover": "http://cdn/x.jpg", "name": "   "}, "   ", "  "),
    "every field populated":
        ({"plot": "p", "cast": "A, B", "genre": "Drama", "director": "D",
          "rating": "7", "releaseDate": "2019-02-25", "cover": "http://c/x.jpg"},
         "Full Movie", "Full Movie"),
}


def test_a_completed_run_leaves_nothing_pending(db):
    """THE assertion. Run to completion, then ask again: there must be no work.

    This is what failed before the fix and what re-armed the notice forever.
    """
    for i, (raw, name, detected) in enumerate(SHAPES.values()):
        _add(db, f"c{i}", raw, name=name, detected_title=detected)

    task = OfflineMetadataBackfillTask(db)
    assert task.needs_run(None), "nothing was offered, so the test proves nothing"
    task.run(lambda d, t: None, lambda: False)

    assert not task.needs_run(None), (
        "the task ran to completion and still reports work pending — every "
        "launch will re-announce a migration that can never finish"
    )


@pytest.mark.parametrize("label", list(SHAPES))
def test_each_offered_row_is_actually_filled(db, label):
    """Per shape, so a failure names WHICH blob the two halves disagree on."""
    raw, name, detected = SHAPES[label]
    _add(db, "c0", raw, name=name, detected_title=detected)

    task = OfflineMetadataBackfillTask(db)
    offered = task.needs_run(None)
    task.run(lambda d, t: None, lambda: False)

    with db.session_scope() as session:
        linked = session.get(ChannelDB, "c0").metadata_id is not None

    assert offered == linked, (
        f"{label!r}: needs_run said {offered}, run linked {linked}. The SQL "
        "filter and metadata_from_raw disagree about this blob."
    )


def test_a_titleless_row_is_never_offered(db):
    """The specific row, kept as a regression anchor for the report."""
    _add(db, "c0", {"num": 1, "name": "", "stream_icon": "", "rating": "0"}, name="")

    assert not OfflineMetadataBackfillTask(db).needs_run(None), (
        "a row with no title anywhere is work the task cannot do; offering it "
        "is what announced a migration at every launch"
    )


def test_a_real_title_is_still_offered_and_filled(db):
    """The tightened filter must not stop the task doing its actual job."""
    _add(db, "c0", {"plot": "A plot.", "genre": "Drama"}, name="Real Movie")

    task = OfflineMetadataBackfillTask(db)
    assert task.needs_run(None)
    task.run(lambda d, t: None, lambda: False)

    with db.session_scope() as session:
        assert session.get(ChannelDB, "c0").metadata_id, "the backfill stopped working"
