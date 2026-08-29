"""Pasting a channel ID into search finds that channel.

Owner: *"Add being able to search by channel ID... so users can store or share
exact channel ID from sources."*

Two ids are useful to a person and both are accepted:

    ChannelDB.id         the app's own ``{provider_uuid}_{stream_id}``
    ChannelDB.source_id  the provider's own stream id — what a user reads off a
                         source and passes to someone else

Both match **exactly**, never as a substring, and that is the whole design. A
substring match would make an ordinary search for "2024" also return whichever
channel happens to carry stream id 2024 — noise in the common case and
impossible for the user to predict. Equality costs nothing when it does not
match and is unambiguous when it does.

Matching ``source_id`` deliberately returns the channel from EVERY source that
carries that stream id. On the owner's library a single id resolves to two
channels across two providers, and showing both is the point: the id identifies
the stream, not one provider's copy of it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from metatv.core.database import ChannelDB, Database, ProviderDB
from metatv.core.repositories.channel import _channel_text_search_predicate


@pytest.fixture
def session(tmp_path: Path):
    db = Database(f"sqlite:///{tmp_path / 'search.db'}")
    db.create_tables()
    s = db.get_session()
    s.add(ProviderDB(id="p1", name="A", type="xtream", url="u", is_active=True))
    s.add(ProviderDB(id="p2", name="B", type="xtream", url="u", is_active=True))
    s.commit()
    yield s
    s.close()
    db.close()


def _ch(session, cid, *, source_id, provider_id="p1", name="A Channel"):
    session.add(ChannelDB(id=cid, source_id=source_id, provider_id=provider_id,
                          name=name, media_type="movie", detected_title=name))
    session.flush()


def _find(session, term):
    return session.query(ChannelDB).filter(
        _channel_text_search_predicate(term)).all()


def test_the_full_channel_id_finds_exactly_that_channel(session):
    """THE assertion. Nothing matched an id before."""
    _ch(session, "p1_2038450", source_id="2038450", name="Cleopatra")
    _ch(session, "p1_999", source_id="999", name="Something Else")

    hits = _find(session, "p1_2038450")

    assert [c.id for c in hits] == ["p1_2038450"]


def test_the_providers_own_stream_id_finds_it_too(session):
    """What a user actually reads off a source and shares."""
    _ch(session, "p1_2038450", source_id="2038450", name="Cleopatra")

    assert [c.id for c in _find(session, "2038450")] == ["p1_2038450"]


def test_a_stream_id_finds_the_channel_on_every_source_that_has_it(session):
    """The id identifies the stream, not one provider's copy.

    Measured on the owner's library: one stream id resolves to two channels
    across two providers.
    """
    _ch(session, "p1_2038450", source_id="2038450", provider_id="p1", name="Cleopatra")
    _ch(session, "p2_2038450", source_id="2038450", provider_id="p2", name="Cleopatra")

    assert sorted(c.id for c in _find(session, "2038450")) == ["p1_2038450", "p2_2038450"]


def test_whitespace_around_a_pasted_id_is_tolerated(session):
    """Ids arrive via copy-paste, which brings spaces and newlines."""
    _ch(session, "p1_2038450", source_id="2038450", name="Cleopatra")

    assert [c.id for c in _find(session, "  2038450  ")] == ["p1_2038450"]


# ── the exactness that keeps ordinary search clean ──────────────────────────

def test_a_partial_id_does_not_match(session):
    """Substring matching on ids is what this design refuses.

    "204" must not drag in stream id 2038450 — a user typing a year or a
    channel number would otherwise get unpredictable extra rows.
    """
    _ch(session, "p1_2038450", source_id="2038450", name="Cleopatra")

    assert _find(session, "204") == []


def test_a_word_search_is_unchanged(session):
    """The id predicate is an OR — it must not narrow normal search."""
    _ch(session, "p1_1", source_id="1", name="The Matrix")
    _ch(session, "p1_2", source_id="2", name="Matrix Reloaded")

    assert len(_find(session, "matrix")) == 2


def test_a_numeric_search_term_still_matches_names(session):
    """A year in a title keeps working, and does not gain id noise."""
    _ch(session, "p1_500", source_id="500", name="Blade Runner 2049")
    _ch(session, "p1_2049", source_id="2049", name="Unrelated Show")

    hits = {c.id for c in _find(session, "2049")}

    assert "p1_500" in hits, "the title match was lost"
    assert "p1_2049" in hits, "the exact stream-id match was lost"


def test_an_id_that_matches_nothing_returns_nothing(session):
    _ch(session, "p1_1", source_id="1", name="A Channel")

    assert _find(session, "p9_nonexistent") == []
