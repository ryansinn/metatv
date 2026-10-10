"""Credits and alternate titles as tags (cast / director / title).

One vocabulary row per name, a link per channel carrying billing order and the
character played; a re-tag never deletes them (persistent feeders); search and
the person filter find them through the tag index.
"""
import uuid

from metatv.core.database import ChannelDB, ContentTagDB, TagDB
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.channel_lens import person_predicate
from metatv.core.repositories.search_ranking import channel_text_search_predicate
from metatv.core.tag_decomposer import credit_tags, title_tags


def _channel(session, name="Sunny"):
    ch = ChannelDB(id=str(uuid.uuid4()), source_id="1", provider_id="p", name=name, media_type="series")
    session.add(ch)
    session.flush()
    return ch


def test_credit_tags_keep_order_character_and_clean_names():
    items = credit_tags([{"name": "Danny  DeVito", "character": "Frank Reynolds"},
                         {"name": "Charlie Day"}], "Adam Somner, Wes Anderson")
    assert items[0] == ("cast", "Danny DeVito", "metadata_credits", "Frank Reynolds", 0)
    assert items[1][:5] == ("cast", "Charlie Day", "metadata_credits", None, 1)
    assert [i[1] for i in items if i[0] == "director"] == ["Adam Somner", "Wes Anderson"]


def test_links_store_detail_and_survive_a_retag(file_db):
    with file_db.session_scope() as s:
        ch = _channel(s)
        repos = RepositoryFactory(s)
        repos.tags.set_content_tags(ch.id, credit_tags([{"name": "Danny DeVito",
                                                        "character": "Frank Reynolds"}], None)
                                    + title_tags(["Oskyldigt blod"])
                                    + [("genre", "Comedy", "provider_category")])
        cid, key = ch.id, ch.channel_key
    with file_db.session_scope() as s:
        RepositoryFactory(s).tags.delete_generated_for_channels([cid])
    with file_db.session_scope() as s:
        kept = {(t.type, t.value): link.detail for link, t in
                s.query(ContentTagDB, TagDB).join(TagDB, TagDB.id == ContentTagDB.tag_id)
                 .filter(ContentTagDB.channel_key == key)}
    assert kept.get(("cast", "Danny DeVito")) == "Frank Reynolds"
    assert ("title", "Oskyldigt blod") in kept
    assert ("genre", "Comedy") not in kept, "derived tags are rebuilt by the re-tag, not kept"


def test_search_and_person_filter_find_tags(file_db):
    with file_db.session_scope() as s:
        ch = _channel(s, "SE - Innocent Blood")
        RepositoryFactory(s).tags.set_content_tags(
            ch.id, title_tags(["Oskyldigt blod"]) + credit_tags(["Anne Parillaud"], None))
        cid = ch.id
    with file_db.session_scope() as s:
        q = s.query(ChannelDB.id)
        assert q.filter(channel_text_search_predicate("Oskyldigt")).all() == [(cid,)]
        assert q.filter(person_predicate("Anne Parillaud")).all() == [(cid,)]
