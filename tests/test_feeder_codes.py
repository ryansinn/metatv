"""content_tags.feeders: stored as codes, read as names, legacy JSON still read."""
import uuid

from sqlalchemy import text

from metatv.core.database import ChannelDB
from metatv.core.repositories import RepositoryFactory
from metatv.core.tag_source import FEEDER_CODES, decode_feeders, encode_feeders


def test_codes_round_trip_and_unknown_names_survive():
    assert encode_feeders(["provider_category", "zz_new"]) == "1,zz_new"
    assert decode_feeders("1,zz_new") == ["provider_category", "zz_new"]
    assert decode_feeders('["header"]') == ["header"]          # legacy form


def test_codes_are_permanent_and_unique():
    assert len(set(FEEDER_CODES.values())) == len(FEEDER_CODES)
    assert FEEDER_CODES["provider_category"] == 1 and FEEDER_CODES["metadata"] == 15, (
        "a code means its feeder forever — never renumber")


def test_written_as_codes_and_read_back_as_names(file_db):
    with file_db.session_scope() as s:
        ch = ChannelDB(id=str(uuid.uuid4()), source_id="1", provider_id="p", name="X")
        s.add(ch)
        s.flush()
        RepositoryFactory(s).tags.set_content_tags(ch.id, [("genre", "Drama", "provider_category")])
        cid = ch.id
    with file_db.engine.connect() as conn:
        raw = conn.execute(text("SELECT feeders FROM content_tags")).scalar()
    assert raw == "1", f"stored as a code, not JSON: {raw!r}"
    with file_db.session_scope() as s:
        dto = RepositoryFactory(s).tags.get_channel_tags_dto(cid)
    assert dto[0].feeders == ("provider_category",)
