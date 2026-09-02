"""Filtering by a person must find titles whose NAME carries that person.

Owner: "EN - Adaptation. 4K (2002) NICOLAS CAGE" — the parser strips the actor
into ``detected_title``, and the title has no metadata row at all, so a person
filter returned nothing. Owner's follow-up question was the sharp one: "does it
return as a result if someone filters for that actor?" It did not.

The asymmetry was the bug:

  * free-text SEARCH already matched ``ChannelDB.name`` (see
    ``channel_text_search_predicate``), so searching "Nicolas Cage" FOUND it;
  * the person FILTER checked only ``metadata.cast``/``director`` and
    ``raw_data.$.cast``/``$.director``, so filtering by the same name MISSED it.

Searching a name finding a title while filtering by that name hides it is
indefensible, and on this library most rows have no metadata at all — so the
filter was empty far more often than it was right.
"""

from __future__ import annotations

import uuid

import pytest


@pytest.fixture()
def repo(tmp_path):
    from metatv.core.database import Database, ProviderDB
    from metatv.core.repositories import RepositoryFactory

    db = Database(f"sqlite:///{tmp_path}/person_filter.db")
    db.create_tables()
    session = db.get_session()
    session.add(ProviderDB(
        id="p1", name="p1", type="xtream", url="http://x",
        urls='[{"url": "http://x", "primary": true}]',
        username="u", password="p", is_active=True,
    ))
    session.commit()
    yield RepositoryFactory(session).channels, session
    session.close()


def _add(session, *, name, raw=None):
    from metatv.core.database import ChannelDB

    cid = str(uuid.uuid4())
    session.add(ChannelDB(
        id=cid, provider_id="p1", name=name, source_id=cid,
        media_type="movie", detected_title=name.split("(")[0].strip(),
        # Plain object, NOT json.dumps(): raw_data is a JSONEncoded column and
        # serializes transparently — pre-encoding double-encodes it and the
        # json_extract() match then silently never fires (CLAUDE.md rule).
        raw_data=raw,
    ))
    session.commit()
    return cid


def test_person_filter_finds_an_actor_named_only_in_the_title(repo):
    """The owner's exact case: no metadata row, actor only in the name."""
    channels, session = repo
    target = _add(session, name="EN - Adaptation. 4K (2002) NICOLAS CAGE")
    _add(session, name="EN - Some Other Movie (1999)")

    results = channels.get_all(person_filter="NICOLAS CAGE", limit=50)
    ids = {c.id for c in results}

    assert target in ids, (
        "a title whose NAME contains the actor must be returned — it is visibly "
        "there, and the row has no metadata for the filter to match instead"
    )
    assert len(ids) == 1, f"unrelated titles leaked in: {ids}"


def test_case_insensitive(repo):
    channels, session = repo
    target = _add(session, name="EN - Adaptation. 4K (2002) NICOLAS CAGE")

    results = channels.get_all(person_filter="Nicolas Cage", limit=50)

    assert target in {c.id for c in results}


def test_metadata_backed_match_still_works(repo):
    """Do not regress the path that already worked: raw_data cast."""
    channels, session = repo
    target = _add(
        session,
        name="EN - Unrelated Title (2010)",
        raw={"cast": "Tilda Swinton, Someone Else"},
    )

    results = channels.get_all(person_filter="Tilda Swinton", limit=50)

    assert target in {c.id for c in results}, (
        "raw_data.cast matching must survive — the name match is an ADDITION, "
        "not a replacement"
    )


def test_search_and_filter_now_agree(repo):
    """The asymmetry itself is the regression to guard against.

    Whatever a free-text search for a person finds, filtering by that person
    must also find. They diverged silently before.
    """
    channels, session = repo
    target = _add(session, name="EN - Adaptation. 4K (2002) NICOLAS CAGE")

    searched = {c.id for c in channels.get_all(search_query="NICOLAS CAGE", limit=50)}
    filtered = {c.id for c in channels.get_all(person_filter="NICOLAS CAGE", limit=50)}

    assert target in searched, "search regressed"
    assert target in filtered, "filter still misses what search finds"


def test_live_actor_channel_is_included(repo):
    """Curated 24/7 actor channels are the point, not noise.

    Verified against the real corpus, which carries provider categories named
    "24/7 MOVIES/ACTORS VIP" and "AR| ACTORS 4K" holding entries like
    "24/7 TOM HANKS" and "BS| NICOLAS CAGE COLLECTION". Someone filtering for
    Tom Hanks wants those. An earlier version of this filter excluded live rows
    on the assumption that such names were coincidences; they are not.
    """
    from metatv.core.database import ChannelDB

    channels, session = repo
    cid = str(uuid.uuid4())
    session.add(ChannelDB(
        id=cid, provider_id="p1", name="24/7 TOM HANKS",
        source_id=cid, media_type="live", detected_title="24/7 TOM HANKS",
        category="24/7 MOVIES/ACTORS VIP",
    ))
    session.commit()

    results = channels.get_all(person_filter="Tom Hanks", limit=50)

    assert cid in {c.id for c in results}, (
        "a 24/7 channel devoted to this actor must appear — hiding it is "
        "censorial, not precise"
    )
