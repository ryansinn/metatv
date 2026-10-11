"""Spelling variants of one person merge into one tag; the writer remembers them."""
from sqlalchemy import text

from metatv.core.database import ChannelDB
from metatv.core.migrations.person_aliases import PersonAliasTask, alias_clusters
from metatv.core.repositories import RepositoryFactory


def test_the_clustering_rules():
    people = {1: "Andy Garcia", 2: "Andy García", 3: "Denzel Washigton",
              4: "Denzel Washington", 5: "Denzel Washingtown", 6: "محسن تنابنده", 7: "علیرضا خمسه"}
    titles = {3: {"t1"}, 4: {"t1", "t2"}, 5: {"t9"}, 6: {"t3"}, 7: {"t3"}}
    groups = {frozenset(c) for c in alias_clusters(people, titles)}
    assert frozenset({1, 2}) in groups, "same letters merge anywhere"
    assert frozenset({3, 4}) in groups, "a close spelling merges when it shares a title"
    assert not any(5 in g for g in groups), "a close spelling on other titles does not"
    assert not any(6 in g or 7 in g for g in groups), "non-Latin names are never guessed"


def test_the_merge_moves_links_and_the_writer_follows_the_alias(db):
    with db.session_scope() as s:
        for cid in ("a", "b"):
            s.add(ChannelDB(id=cid, source_id=cid, provider_id="p", name=cid, media_type="movie",
                            content_key="tmdb:1|movie"))
        s.flush()
        tags = RepositoryFactory(s).tags
        tags.set_content_tags("a", [("cast", "Denzel Washington", "metadata_credits", None, 0)])
        tags.set_content_tags("b", [("person", "Denzel Washigton", "name_cast")])
    PersonAliasTask(db).run(lambda *_: None, lambda: False)
    with db.engine.connect() as conn:
        assert conn.execute(text("SELECT value FROM tags WHERE type='person'")).scalars().all() \
            == ["Denzel Washington"]
        assert conn.execute(text("SELECT count(*) FROM content_tags")).scalar() == 2
    with db.session_scope() as s:
        from metatv.core.database import TagDB
        tid = RepositoryFactory(s).tags.get_or_create_tag_id("person", "Denzel Washigton")
        assert s.get(TagDB, tid).value == "Denzel Washington"
