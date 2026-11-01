"""SQL case-insensitive matching folds non-ASCII capitals (ledger F55, F56)."""

from __future__ import annotations

from sqlalchemy import func

from metatv.core.database import ChannelDB


def test_ilike_finds_an_accented_capital(db):
    """Searching "école" missed "ÉCOLE": SQLite's lower() folded ASCII only."""
    with db.session_scope() as s:
        for cid, name in (("a", "ÉCOLE DES FEMMES"), ("b", "école buissonnière"), ("c", "School")):
            s.add(ChannelDB(id=cid, source_id=cid, provider_id="p", name=name))
    with db.session_scope() as s:
        found = {c.id for c in s.query(ChannelDB).filter(ChannelDB.name.ilike("%école%"))}
        assert found == {"a", "b"}
        assert s.query(func.lower("ŞAŞMAZ")).scalar() == "şaşmaz"
        assert s.query(func.lower(None)).scalar() is None


def test_one_tag_for_two_spellings_differing_in_a_non_ascii_capital(db):
    """F56: "ŞAŞMAZ" and "Şaşmaz" used to be able to become two tags."""
    from metatv.core.repositories import RepositoryFactory
    from metatv.core.repositories.tag import _clear_tag_cache
    with db.session_scope() as s:
        first = RepositoryFactory(s).tags.get_or_create_tag("person", "Necati Şaşmaz").id
    _clear_tag_cache()                      # make the second call go to the database
    with db.session_scope() as s:
        again = RepositoryFactory(s).tags.get_or_create_tag("person", "NECATI ŞAŞMAZ").id
    assert first == again
