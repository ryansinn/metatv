"""The EPG id already in ``raw_data`` is recovered without a re-ingest.

Fixing the write path does not reach rows already written — 785,163 of them in
the owner's library, of which 20,506 live channels carry a usable id inside
their stored ``raw_data``. Without this the user would have to re-ingest an
entire catalogue to make EPG matching work.

Same lesson as ``detected_restricted`` and the tag merge: a column computed at
ingestion needs a backfill.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from metatv.core.database import ChannelDB, Database, ProviderDB
from metatv.core.migrations.epg_channel_id_backfill import EpgChannelIdBackfillTask


@pytest.fixture
def db(tmp_path: Path):
    d = Database(f"sqlite:///{tmp_path / 'epgid.db'}")
    d.create_tables()
    with d.session_scope() as s:
        s.add(ProviderDB(id="p1", name="P", type="xtream", url="u", is_active=True))
    yield d
    d.close()


def _add(db, cid, raw, *, stored=None):
    with db.session_scope() as s:
        s.add(ChannelDB(id=cid, source_id=str(uuid.uuid4()), provider_id="p1",
                        name=cid, media_type="live", raw_data=raw,
                        epg_channel_id=stored))


def _get(db, cid):
    with db.session_scope() as s:
        return s.get(ChannelDB, cid).epg_channel_id


def test_an_id_in_raw_data_is_recovered(db):
    """THE assertion. 20,506 rows are in exactly this state."""
    _add(db, "c1", {"epg_channel_id": "bbc.one.uk"})

    EpgChannelIdBackfillTask(db).run(lambda a, b: None, lambda: False)

    assert _get(db, "c1") == "bbc.one.uk"


def test_an_existing_value_is_not_overwritten(db):
    """A row written after the fix already has the right value."""
    _add(db, "c1", {"epg_channel_id": "from.raw"}, stored="already.set")

    EpgChannelIdBackfillTask(db).run(lambda a, b: None, lambda: False)

    assert _get(db, "c1") == "already.set"


@pytest.mark.parametrize("raw", [
    {"epg_channel_id": ""},
    {"epg_channel_id": "   "},
    {"epg_channel_id": None},
    {"name": "no epg id at all"},
    None,
])
def test_a_row_with_nothing_to_recover_is_left_alone(db, raw):
    _add(db, "c1", raw)

    EpgChannelIdBackfillTask(db).run(lambda a, b: None, lambda: False)

    assert not _get(db, "c1")


def test_surrounding_whitespace_is_trimmed(db):
    _add(db, "c1", {"epg_channel_id": "  bbc.one.uk  "})

    EpgChannelIdBackfillTask(db).run(lambda a, b: None, lambda: False)

    assert _get(db, "c1") == "bbc.one.uk"


def test_needs_run_is_false_once_there_is_nothing_left(db):
    """It must not rescan a 785k-row table on every launch forever."""
    from types import SimpleNamespace

    _add(db, "c1", {"epg_channel_id": "bbc.one.uk"})
    task = EpgChannelIdBackfillTask(db)
    cfg = SimpleNamespace(epg_channel_id_backfill_version=0)

    assert task.needs_run(cfg) is True
    task.run(lambda a, b: None, lambda: False)

    assert task.needs_run(cfg) is False, "nothing left to recover, yet still armed"


def test_running_twice_changes_nothing(db):
    _add(db, "c1", {"epg_channel_id": "bbc.one.uk"})
    task = EpgChannelIdBackfillTask(db)

    task.run(lambda a, b: None, lambda: False)
    first = _get(db, "c1")
    task.run(lambda a, b: None, lambda: False)

    assert _get(db, "c1") == first == "bbc.one.uk"
