"""One person tag per identity; the role rides on the link (owner, 2026-10-10).

An actor who also directed is ONE tag, and a name read off the title joins the
same tag — so a recipe pick matches every title the person is attached to.
"""
from sqlalchemy import text

from metatv.core.credits import credits_for
from metatv.core.database import ChannelDB
from metatv.core.migrations.person_identity import PersonIdentityTask
from metatv.core.repositories import RepositoryFactory
from metatv.core.tag_source import FEEDER_CODES


def _channels(s, *ids):
    for cid in ids:
        s.add(ChannelDB(id=cid, source_id=cid, provider_id="p", name=cid, media_type="movie"))
    s.flush()


def test_acting_and_directing_are_one_person(db):
    with db.session_scope() as s:
        _channels(s, "unforgiven")
        RepositoryFactory(s).tags.set_content_tags("unforgiven", [
            ("cast", "Clint Eastwood", "metadata_credits", "Will Munny", 0),
            ("director", "Clint Eastwood", "metadata_credits", None, 0),
        ])
    with db.session_scope() as s:
        types = s.execute(text("SELECT type FROM tags WHERE value = 'Clint Eastwood'")).scalars().all()
        assert types == ["person"], "one identity, not a cast tag and a director tag"
        c = credits_for(s, ["unforgiven"])["unforgiven"]
        assert c.cast == (("Clint Eastwood", "Will Munny"),) and c.directors == ("Clint Eastwood",)


def test_a_person_pick_matches_every_role_and_a_role_pick_narrows(db):
    with db.session_scope() as s:
        _channels(s, "acted", "directed", "named")
        tags = RepositoryFactory(s).tags
        tags.set_content_tags("acted", [("cast", "Cillian Murphy", "metadata_credits", None, 0)])
        tags.set_content_tags("directed", [("director", "Cillian Murphy", "metadata_credits", None, 0)])
        tags.set_content_tags("named", [("person", "Cillian Murphy", "name_cast")])
    with db.session_scope() as s:
        tags = RepositoryFactory(s).tags
        def ids(facet):
            return {r[0] for r in tags._faceted_channel_id_query({facet: {"Cillian Murphy"}}).all()}
        assert len(ids("person")) == 3, "any role, named in the title included"
        assert len(ids("cast")) == 1 and len(ids("director")) == 1


def test_the_migration_folds_cast_and_director_into_one_person(db):
    with db.session_scope() as s:
        _channels(s, "a", "b")
    code = str(FEEDER_CODES["metadata_credits"])
    with db.engine.begin() as conn:   # the pre-change shape
        conn.execute(text("INSERT INTO tags (type, value) VALUES ('cast', 'Kevin Costner'),"
                          " ('director', 'Kevin Costner'), ('person', 'Kevin Costner Uncredited')"))
        for cid, typ in (("a", "cast"), ("a", "director"), ("b", "person")):
            value = "Kevin Costner Uncredited" if typ == "person" else "Kevin Costner"
            conn.execute(text(
                "INSERT INTO content_tags (channel_key, tag_id, source, feeders)"
                " SELECT c.channel_key, t.id, 0, :f FROM channels c, tags t"
                " WHERE c.id = :cid AND t.type = :typ AND t.value = :v"),
                {"cid": cid, "typ": typ, "v": value, "f": code})
    task = PersonIdentityTask(db)
    assert task.needs_run(None)
    task.run(lambda *_: None, lambda: False)
    assert not task.needs_run(None)
    with db.engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT c.id, t.type, t.value, ct.qualifier FROM content_tags ct"
            " JOIN tags t ON t.id = ct.tag_id JOIN channels c ON c.channel_key = ct.channel_key"
            " ORDER BY c.id")).all()
    assert [tuple(r) for r in rows] == [("a", "person", "Kevin Costner", 3),
                                        ("b", "person", "Kevin Costner", None)]
