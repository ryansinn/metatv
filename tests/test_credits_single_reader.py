"""core.credits — the one reader of cast/directing credits.

Tags first (billing order, character), the old metadata text as the fallback
for channels not converted yet; both the batch lookup and the bulk SQL columns
give the same answer.
"""
import uuid

from metatv.core.credits import (cast_column, cast_names, credits_for, director_column,
                                 director_names)
from metatv.core.database import ChannelDB, MetadataDB
from metatv.core.repositories import RepositoryFactory
from metatv.core.tag_decomposer import credit_tags


def _channel(s, *, cast=None, director=None):
    mid = f"meta_{uuid.uuid4()}"
    s.add(MetadataDB(id=mid, title="T", cast=cast, director=director))
    ch = ChannelDB(id=str(uuid.uuid4()), source_id="1", provider_id="p", name="T",
                   media_type="movie", metadata_id=mid)
    s.add(ch)
    s.flush()
    return ch


def test_tags_win_and_keep_order(file_db):
    with file_db.session_scope() as s:
        ch = _channel(s, cast=[{"name": "Old Text"}], director="Old Director")
        RepositoryFactory(s).tags.set_content_tags(ch.id, credit_tags(
            [{"name": "B Second"}, {"name": "A First", "character": "Hero"}][::-1],
            "Wes Anderson, Adam Somner"))
        cid = ch.id
    with file_db.session_scope() as s:
        c = credits_for(s, [cid])[cid]
        assert c.cast == (("A First", "Hero"), ("B Second", None))
        assert c.directors == ("Wes Anderson", "Adam Somner"), "source order kept"
        row = (s.query(cast_column(ChannelDB, MetadataDB), director_column(ChannelDB, MetadataDB))
               .join(MetadataDB, MetadataDB.id == ChannelDB.metadata_id)
               .filter(ChannelDB.id == cid).one())
        assert cast_names(row[0]) == ["A First", "B Second"]
        assert director_names(row[1])[0] == "Wes Anderson"


def test_unconverted_channel_falls_back_to_the_old_text(file_db):
    with file_db.session_scope() as s:
        ch = _channel(s, cast=[{"name": "Ralph Fiennes", "character": "Henry"}], director="Wes Anderson")
        cid = ch.id
    with file_db.session_scope() as s:
        c = credits_for(s, [cid])[cid]
        assert c.cast == (("Ralph Fiennes", "Henry"),) and c.directors == ("Wes Anderson",)
        row = (s.query(cast_column(ChannelDB, MetadataDB))
               .join(MetadataDB, MetadataDB.id == ChannelDB.metadata_id)
               .filter(ChannelDB.id == cid).one())
        assert cast_names(row[0]) == ["Ralph Fiennes"]
