"""A ##…## header labels its own provider group and later groups carrying its
words; the first unrelated group ends it. It never reset, so one header ran over
833 groups (54,144 channels) on one source."""
from metatv.core.database import ChannelDB
from metatv.core.models import Provider
from metatv.core.provider_loader import ProviderLoadThread
from tests.conftest import make_channel_double


def _live(cid, name, category):
    return make_channel_double(id=cid, source_id=cid, provider_id="prov1", name=name,
                               media_type="live", category=category, raw_data={})


def _store(db, channels):
    p = Provider.__new__(Provider)
    p.id, p.name, p.type, p.url, p.username, p.password, p.urls = (
        "prov1", "P", "xtream", "http://x", "u", "p", [])
    session = db.get_session()
    try:
        ProviderLoadThread(p, db)._store_channels(session, channels, total=len(channels))
    finally:
        session.close()


def test_a_header_spans_related_groups_and_stops_at_an_unrelated_one(db):
    _store(db, [
        _live("h1", "##### SOCCER PPV #####", "US| SOCCER PPV"),
        _live("us", "US SOCCER 1", "US| SOCCER PPV"),
        _live("fr", "FR SOCCER 1", "FR| SOCCER PPV"),      # carries the header's words
        _live("h2", "##### FANATIZ #####", "LAT| FANATIZ"),
        _live("fan", "FANATIZ 1", "LAT| FANATIZ"),          # the header's own group
        _live("mx", "MEXICO 1", "LAT| MEXICO VIP"),         # unrelated: the header ends
        _live("cr", "COSTA RICA 1", "LAT| COSTA RICA"),     # and stays ended
    ])
    with db.session_scope(commit=False) as s:
        got = {c.id: c.source_category for c in s.query(ChannelDB).all()}
    assert got["us"] == got["fr"] == "SOCCER PPV"
    assert got["fan"] == "FANATIZ"
    assert got["mx"] is None and got["cr"] is None
