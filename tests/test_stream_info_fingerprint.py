"""Recycled stream ids: a measurement belongs to the title it measured.

Providers reuse stream ids, so after a catalog refresh the same channel id can
name a different film. StreamInfoRepository.invalidate_changed discards a
measurement (and its measured language tags) only when the name changed —
never for a rating/timestamp change, and never an old record that predates the
fingerprint (it adopts the current name instead).
"""
import uuid

from metatv.core.database import ChannelDB, ContentTagDB, StreamInfoDB
from metatv.core.repositories import RepositoryFactory

INFO = {"video": None, "audio": [{"lang": "eng", "codec": "aac"}], "subs": [], "container": None}


def _channel(session, name):
    ch = ChannelDB(id=str(uuid.uuid4()), source_id="1", provider_id="p", name=name, media_type="movie")
    session.add(ch)
    session.flush()
    return ch


def test_a_renamed_channel_loses_its_measurement_and_tags(file_db):
    with file_db.session_scope() as s:
        ch = _channel(s, "Innocent Blood")
        repos = RepositoryFactory(s)
        repos.stream_info.upsert(ch.id, INFO, source="played")
        cid = ch.id
    with file_db.session_scope() as s:
        s.get(ChannelDB, cid).name = "Some Other Film"
        assert RepositoryFactory(s).stream_info.invalidate_changed([cid]) == 1
    with file_db.session_scope() as s:
        assert s.get(StreamInfoDB, cid) is None
        key = s.get(ChannelDB, cid).channel_key
        assert not s.query(ContentTagDB).filter_by(channel_key=key).all(), (
            "the measured language tag belongs to the old title")


def test_same_name_keeps_it_and_old_records_adopt_the_name(file_db):
    with file_db.session_scope() as s:
        ch = _channel(s, "Innocent Blood")
        RepositoryFactory(s).stream_info.upsert(ch.id, INFO, source="played")
        cid = ch.id
    with file_db.session_scope() as s:
        s.get(StreamInfoDB, cid).fingerprint = None          # written before the guard existed
    with file_db.session_scope() as s:
        assert RepositoryFactory(s).stream_info.invalidate_changed([cid]) == 0
    with file_db.session_scope() as s:
        rec = s.get(StreamInfoDB, cid)
        assert rec is not None and rec.fingerprint == "Innocent Blood"
