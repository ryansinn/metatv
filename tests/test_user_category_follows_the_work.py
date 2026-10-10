"""A user category names WORKS: a title filed under it on any source (even a
disabled one) shows its copies on every active source, once per title."""
from metatv.core.database import ChannelDB
from metatv.core.discovery_engine import get_by_user_category


def _ch(session, cid, provider, *, key, cat=None):
    session.add(ChannelDB(id=cid, source_id=cid, provider_id=provider, name=f"EN - {cid}",
                          media_type="movie", content_key=key, user_category=cat))


def test_a_title_filed_on_a_disabled_source_shows_its_active_copies(db):
    with db.session_scope() as s:
        _ch(s, "filed", "off", key="tmdb:1|movie", cat="Roger Corman")
        _ch(s, "copy_a", "on", key="tmdb:1|movie")
        _ch(s, "copy_b", "on", key="tmdb:1|movie")      # second copy: same work
        _ch(s, "other", "on", key="tmdb:2|movie")       # not filed: stays out
    with db.session_scope() as s:
        cards = get_by_user_category(s, "Roger Corman", excluded_provider_ids=["off"])
    ids = [c.channel_id for c in cards]
    assert len(ids) == 1, f"one card per work, got {ids}"
    assert ids[0] in {"copy_a", "copy_b"}, "the active copy stands in for the filed one"


def test_the_filed_copy_leads_when_it_is_visible(db):
    with db.session_scope() as s:
        _ch(s, "filed", "on", key="tmdb:1|movie", cat="Roger Corman")
        _ch(s, "copy", "on", key="tmdb:1|movie")
    with db.session_scope() as s:
        cards = get_by_user_category(s, "Roger Corman")
    assert [c.channel_id for c in cards] == ["filed"]
