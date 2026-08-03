"""content_key fragmented one film into several identities (#284).

The owner: "The Lobster is missing an English version, are you telling me these
titles and chips and tags are accurate?"  It existed as THREE content_keys —
``tmdb:254320|movie`` on the one row a fetch had identified, plus two idless
siblings on ``the lobster|movie|`` — so "Other versions" could never group them.

Measured against the owner's real library (332,772 movie rows), the cause was
NOT the key format.  It was that "same title" had **two** definitions:

  * ``content_identity.normalize_title_for_key`` — computes ``content_key``
  * ``content_dedup.normalize_title``            — bucketed propagation siblings

The second cleans a **raw provider channel name**: it strips provider prefixes,
trailing years and quality tokens.  ``detected_title`` has already had all of
that removed at ingestion, so running it again double-strips real title words
and merges unrelated productions into one bucket.  The bucket then holds several
tmdb ids, and the remake guard — correctly, given what it was shown — refuses to
guess.  The ambiguity was manufactured by the normaliser, not present in the data.

Switching the pass to the key's own normaliser: **+498 adoptions, 0 lost, 0
disagreements** on the owner's library.

The second half: an id learned by a *fetch* never reached its siblings at all.
Propagation ran at ingestion and after a refresh queue drained — never after
enrichment — which is precisely why The Lobster's ``'fetched'`` id sat next to
two idless copies of itself.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from metatv.core.content_dedup import normalize_title
from metatv.core.content_identity import normalize_title_for_key
from metatv.core.database import ChannelDB, Database, ProviderDB
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.tag import _clear_tag_cache


@pytest.fixture()
def db(tmp_path: Path):
    _clear_tag_cache()
    d = Database(f"sqlite:///{tmp_path / 'frag.db'}")
    d.create_tables()
    yield d
    d.close()


def _provider(session, pid: str = "p1") -> str:
    session.add(ProviderDB(id=pid, name="P", type="xtream", url="http://x",
                           username="u", password="p", is_active=True))
    session.flush()
    return pid


def _channel(session, *, title, year=None, tmdb=None, media_type="movie",
             provider_id="p1") -> str:
    """Insert a row the way ingestion would — content_key included.

    The key comes from the real ``content_key_for`` chokepoint rather than a
    literal, so a fixture can never encode a key format the app doesn't produce.
    """
    from metatv.core.content_identity import content_key_for

    cid = str(uuid.uuid4())
    row = ChannelDB(
        id=cid, source_id=str(uuid.uuid4()), provider_id=provider_id,
        name=title, media_type=media_type, detected_title=title,
        detected_year=year, detected_tmdb_id=tmdb,
    )
    row.content_key = content_key_for(row)
    session.add(row)
    session.flush()
    return cid


def _adopted_id(db, cid) -> str | None:
    with db.session_scope(commit=False) as session:
        return session.query(ChannelDB.detected_tmdb_id).filter_by(id=cid).scalar()


# ---------------------------------------------------------------------------
# 1. The two normalisers genuinely disagree — the root cause, isolated
# ---------------------------------------------------------------------------


class TestTheTwoNormalisersDisagree:
    """If these ever converge, the bug class is gone and these tests should go too."""

    @pytest.mark.parametrize("title, eaten", [
        ("Blade Runner 2049", "blade runner"),   # sequel merged into the 1982 film
        ("WWE: Unreal", "unreal"),               # show name eaten as a provider prefix
        ("Hijack 1971", "hijack"),               # year-in-title stripped
    ])
    def test_the_raw_name_cleaner_destroys_title_words(self, title, eaten):
        """normalize_title is right for ChannelDB.name and wrong for detected_title."""
        assert normalize_title(title) == eaten

    @pytest.mark.parametrize("title, kept", [
        ("Blade Runner 2049", "blade runner 2049"),
        ("WWE: Unreal", "wwe unreal"),
        ("Hijack 1971", "hijack 1971"),
    ])
    def test_the_identity_normaliser_keeps_them(self, title, kept):
        assert normalize_title_for_key(title) == kept

    def test_both_still_agree_on_ordinary_titles(self):
        """The fix must not be 'stop normalising' — punctuation/case still collapse."""
        for a, b in [("The  Matrix", "the matrix"), ("Spider-Man", "spider man")]:
            assert normalize_title_for_key(a) == b


# ---------------------------------------------------------------------------
# 2. Adoptions the manufactured ambiguity was blocking
# ---------------------------------------------------------------------------


class TestManufacturedAmbiguityNoLongerBlocks:

    def test_a_sequel_adopts_its_own_id_not_the_originals(self, db):
        """The measured headline case.

        Pre-fix both titles normalised to "blade runner", so the bucket held two
        ids (78 and 335984), the remake guard saw ambiguity and skipped — leaving
        the sequel's copies permanently split from each other.
        """
        with db.session_scope() as session:
            _provider(session)
            _channel(session, title="Blade Runner", year="1982", tmdb="78")
            _channel(session, title="Blade Runner 2049", year="2017", tmdb="335984")
            idless = _channel(session, title="Blade Runner 2049")

        with db.session_scope() as session:
            adopted = RepositoryFactory(session).channels.\
                propagate_tmdb_from_title_siblings()

        assert adopted == 1, "the sequel's idless copy was left unidentified"
        assert _adopted_id(db, idless) == "335984", (
            "adopted the wrong film's id — the 1982 original, not the 2017 sequel"
        )

    def test_a_show_name_is_not_mistaken_for_a_provider_prefix(self, db):
        """'WWE: Unreal' → 'unreal' merged it with an unrelated show called Unreal."""
        with db.session_scope() as session:
            _provider(session)
            _channel(session, title="Unreal", media_type="series", tmdb="61888")
            _channel(session, title="WWE: Unreal", media_type="series", tmdb="289485")
            idless = _channel(session, title="WWE: Unreal", media_type="series")

        with db.session_scope() as session:
            adopted = RepositoryFactory(session).channels.\
                propagate_tmdb_from_title_siblings()

        assert adopted == 1
        assert _adopted_id(db, idless) == "289485"

    def test_the_owners_lobster_collapses_to_one_key(self, db):
        """End to end on the reported shape: 1 identified row, 2 idless siblings."""
        with db.session_scope() as session:
            _provider(session)
            fetched = _channel(session, title="The Lobster", tmdb="254320")
            a = _channel(session, title="The Lobster", year="2015")
            b = _channel(session, title="The Lobster")

        with db.session_scope() as session:
            RepositoryFactory(session).channels.propagate_tmdb_from_title_siblings()

        with db.session_scope(commit=False) as session:
            keys = {
                r.content_key
                for r in session.query(ChannelDB.content_key)
                .filter(ChannelDB.id.in_([fetched, a, b])).all()
            }
        assert keys == {"tmdb:254320|movie"}, (
            f"still fragmented into {len(keys)} identities: {sorted(keys)} — "
            f"'Other versions' cannot group these"
        )


# ---------------------------------------------------------------------------
# 3. The guard must still refuse a genuine ambiguity
# ---------------------------------------------------------------------------


class TestRealAmbiguityIsStillRefused:
    """The fix removes FAKE ambiguity only. Guessing between real remakes is worse
    than leaving a row unidentified — it is the failure that mislabelled the
    owner's '|EN| Aladdin' as German."""

    def test_two_real_productions_of_one_title_are_not_guessed_between(self, db):
        with db.session_scope() as session:
            _provider(session)
            _channel(session, title="A Christmas Carol", year="1984", tmdb="13189")
            _channel(session, title="A Christmas Carol", year="2009", tmdb="17979")
            idless = _channel(session, title="A Christmas Carol")

        with db.session_scope() as session:
            adopted = RepositoryFactory(session).channels.\
                propagate_tmdb_from_title_siblings()

        assert adopted == 0
        assert _adopted_id(db, idless) is None

    def test_a_year_mismatched_remake_is_still_skipped(self, db):
        with db.session_scope() as session:
            _provider(session)
            _channel(session, title="Dune", year="2021", tmdb="438631")
            old = _channel(session, title="Dune", year="1984")

        with db.session_scope() as session:
            adopted = RepositoryFactory(session).channels.\
                propagate_tmdb_from_title_siblings()

        assert adopted == 0
        assert _adopted_id(db, old) is None

    def test_a_genuine_variant_still_adopts(self, db):
        """Regression floor: the pass must not become so strict it stops working."""
        with db.session_scope() as session:
            _provider(session)
            _channel(session, title="The Matrix", year="1999", tmdb="603")
            variant = _channel(session, title="the  matrix", year="1999")

        with db.session_scope() as session:
            adopted = RepositoryFactory(session).channels.\
                propagate_tmdb_from_title_siblings()

        assert adopted == 1
        assert _adopted_id(db, variant) == "603"


# ---------------------------------------------------------------------------
# 4. One definition of "same title" — the drift guard
# ---------------------------------------------------------------------------


def test_propagation_does_not_import_the_raw_name_cleaner():
    """CLAUDE.md single-chokepoint rule, pinned.

    Identity has one definition. A second look-alike normaliser deciding which
    rows are siblings is what produced this bug, and the two functions are similar
    enough that reaching for the wrong one is an easy mistake to repeat.
    """
    import inspect

    from metatv.core.repositories.channel import ChannelRepository

    src = inspect.getsource(
        ChannelRepository._propagate_tmdb_from_title_siblings_impl
    )
    assert "normalize_title_for_key" in src
    assert "from metatv.core.content_dedup import normalize_title" not in src
