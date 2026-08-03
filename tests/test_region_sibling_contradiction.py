"""Sibling region propagation must not contradict a row's own locale prefix.

Owner report: channel ``|EN| Aladdin 4K`` (category ``|EN| ANIME/MANGAS``) came
back with ``detected_region = "DE"``. Nothing in that row says German.

Cause: ``content_key`` is deliberately generous. The key ``"aladdin|movie|"``
carries no year and no TMDb id, so **15 unrelated Aladdin releases** collapse
into it. The final propagation pass fills an empty ``detected_region`` from the
*most common* sibling region — and since German rows dominate this library, DE
was stamped onto the ``|EN|`` rows and, worse, onto ``|AR| Aladdin``: an Arabic
release reported as German.

The row's empty region was never a gap. ``EN`` is a language-only code
(``CODE_FACETS`` says so explicitly: "there is no place called EN"), so an empty
region is a FACT about that code. Filling it from a sibling majority mislabels
the row. Empty is honest.

Rows with no locale of their own (``MULTI``, ``4K``, no prefix) still inherit —
that is what the propagation is for, and it is unchanged.
"""

from __future__ import annotations

import uuid

import pytest

from metatv.core.repositories.channel import _contradicts_own_locale


class TestContradictionPredicate:

    @pytest.mark.parametrize("own_prefix,candidate", [
        ("EN", "DE"),   # the owner's case — language-only code, foreign region
        ("AR", "DE"),   # the worse one: Arabic release stamped German
        ("IT", "DE"),   # a real region code, contradicted
    ])
    def test_blocks_a_contradicting_region(self, own_prefix, candidate):
        assert _contradicts_own_locale(own_prefix, candidate) is True

    @pytest.mark.parametrize("own_prefix,candidate", [
        ("IT", "IT"),   # sibling agrees with the row's own code
        ("DE", "DE"),
    ])
    def test_allows_an_agreeing_region(self, own_prefix, candidate):
        assert _contradicts_own_locale(own_prefix, candidate) is False

    @pytest.mark.parametrize("own_prefix", ["MULTI", "4K", "", None, "ZZZ"])
    def test_rows_without_a_locale_of_their_own_still_inherit(self, own_prefix):
        """The propagation's actual purpose — do not over-correct it away."""
        assert _contradicts_own_locale(own_prefix, "DE") is False


class TestPropagationEndToEnd:
    """Against a real Database on a tmp_path file, per project convention."""

    @pytest.fixture()
    def repo(self, tmp_path):
        from metatv.core.database import Database, ProviderDB
        from metatv.core.repositories import RepositoryFactory

        db = Database(f"sqlite:///{tmp_path}/region_prop.db")
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

    def _add(self, session, *, name, prefix, region, key):
        from metatv.core.database import ChannelDB

        cid = str(uuid.uuid4())
        session.add(ChannelDB(
            id=cid, provider_id="p1", name=name, source_id=cid,
            media_type="movie", detected_prefix=prefix,
            detected_region=region, content_key=key,
        ))
        session.commit()
        return cid

    def test_the_owner_reported_shape(self, repo):
        """Reproduces the Aladdin key: German majority, mixed-locale siblings."""
        from metatv.core.database import ChannelDB

        channels, session = repo
        key = "aladdin|movie|"
        # German majority — three rows with their own DE region.
        for i in range(3):
            self._add(session, name=f"|DE| Aladdin {i}", prefix="DE",
                      region="DE", key=key)
        en = self._add(session, name=" |EN|  Aladdin 4K", prefix="EN",
                       region="", key=key)
        ar = self._add(session, name="|AR| Aladdin", prefix="AR",
                       region="", key=key)
        multi = self._add(session, name="|MULTI| Aladdin", prefix="MULTI",
                          region="", key=key)

        channels._propagate_region_from_siblings_impl()
        session.commit()

        def region_of(cid):
            return session.query(ChannelDB.detected_region).filter(
                ChannelDB.id == cid).scalar()

        assert region_of(en) in (None, ""), (
            f"|EN| row inherited {region_of(en)!r} — an English release must not "
            f"be relabelled with the library's majority region"
        )
        assert region_of(ar) in (None, ""), (
            f"|AR| row inherited {region_of(ar)!r} — an Arabic release reported "
            f"as German is the exact bug"
        )
        assert region_of(multi) == "DE", (
            "MULTI has no locale of its own, so it SHOULD still inherit — the "
            "fix must not disable propagation wholesale"
        )

    def test_agreeing_sibling_still_fills(self, repo):
        """A row whose own code matches the majority is unaffected."""
        from metatv.core.database import ChannelDB

        channels, session = repo
        key = "sometitle|movie|"
        self._add(session, name="|IT| X", prefix="IT", region="IT", key=key)
        target = self._add(session, name="|IT| X 4K", prefix="IT",
                           region="", key=key)

        channels._propagate_region_from_siblings_impl()
        session.commit()

        got = session.query(ChannelDB.detected_region).filter(
            ChannelDB.id == target).scalar()
        assert got == "IT"
