"""Recommendations + Similar collapse localized-title / MULTI variants via stored content_key.

Phase-2 of the content-identity dedup plan (QA flag 1ebe93bb).  Recommendations and the
details-pane "Similar Titles" surface used the runtime title fingerprint
(``content_dedup.build_dedup_key`` = norm_title/media_type/year/director), which keys off
the *raw name* and therefore split same-production variants whose titles differ
(English vs Scandinavian) or carry a bare "MULTI" audio token.  Both now prefer the
**stored** ``content_key`` (the same identity Discover/Other-Versions use), collapsing
those variants into one card; the runtime fingerprint remains the fallback only for rows
with no ``content_key``.

Coverage (all DB tests use a file-backed tmp_path SQLite, not :memory:):
  1. Recommendations: two candidates with the SAME content_key but DIFFERENT titles
     collapse to one ScoredChannel (variant_count==2); with content_key=None they split.
  2. Similar: two candidates sharing a content_key but with different titles collapse to a
     single Similar row; a distinct-key sibling stays separate; null-key rows fall back
     to title grouping.
  3. MULTI: a "MULTI"-tokened title and its plain sibling resolve to the SAME content_key
     (pure function + real backfill path); real-word "Multiplicity"/"Dual" are preserved.
"""

from __future__ import annotations

import concurrent.futures
import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(path: Path):
    from metatv.core.database import Database
    db = Database(f"sqlite:///{path}")
    db.create_tables()
    return db


def _make_metadata(session, title: str, genres=None, year: int | None = None):
    from metatv.core.database import MetadataDB
    meta = MetadataDB(
        id=str(uuid.uuid4()),
        title=title,
        genres=genres or [],
        year=year,
    )
    session.add(meta)
    session.flush()
    return meta


def _make_channel(session, *, cid: str | None = None, name: str,
                  media_type: str = "movie",
                  content_key: str | None = None,
                  detected_prefix: str | None = None,
                  detected_title: str | None = None,
                  detected_year: str | None = None,
                  metadata_id: str | None = None,
                  last_played: datetime | None = None,
                  provider_id: str = "p1"):
    from metatv.core.database import ChannelDB
    ch = ChannelDB(
        id=cid or str(uuid.uuid4()),
        source_id=str(uuid.uuid4()),
        provider_id=provider_id,
        name=name,
        media_type=media_type,
        content_key=content_key,
        detected_prefix=detected_prefix,
        detected_title=detected_title,
        detected_year=detected_year,
        metadata_id=metadata_id,
        last_played=last_played,
    )
    session.add(ch)
    session.flush()
    return ch


def _make_rating(session, channel_id: str, rating: int):
    from metatv.core.database import UserRatingDB
    r = UserRatingDB(channel_id=channel_id, rating=rating)
    session.add(r)
    session.flush()
    return r


# ---------------------------------------------------------------------------
# 1. Recommendations — content_key collapses localized-title variants
# ---------------------------------------------------------------------------

class TestRecommendationsContentKeyDedup:
    """score_candidates groups same-content_key candidates even when their titles differ."""

    def _seed(self, session, *, with_content_key: bool):
        """Liked Action signal + two same-content_key Action candidates with different titles."""
        from sqlalchemy.orm import sessionmaker  # noqa: F401 (kept for clarity)
        meta = _make_metadata(session, "Action", genres=["Action"], year=2011)

        # Watched + liked signal so compute_weights produces a positive Action weight.
        # Its content_key differs from the candidates so it doesn't suppress them.
        signal = _make_channel(
            session, name="EN Liked Action (2020)", media_type="movie",
            content_key="liked action|movie|2020" if with_content_key else None,
            detected_prefix="EN", metadata_id=meta.id,
            last_played=datetime(2024, 1, 1),
        )
        _make_rating(session, signal.id, 1)

        shared = "shared killing|movie|2011" if with_content_key else None
        ch_en = _make_channel(
            session, cid="ch-en", name="EN The Killing (2011)", media_type="movie",
            content_key=shared, detected_prefix="EN", detected_title="The Killing",
            metadata_id=meta.id,
        )
        ch_se = _make_channel(
            session, cid="ch-se", name="SE Forbrydelsen (2011)", media_type="movie",
            content_key=shared, detected_prefix="SE", detected_title="Forbrydelsen",
            metadata_id=meta.id,
        )
        return ch_en, ch_se

    def test_same_content_key_diff_titles_collapse_to_one(self, tmp_path):
        from metatv.core.preference_engine import compute_weights, score_candidates

        db = _make_db(tmp_path / "recs_ck.db")
        with db.session_scope() as session:
            self._seed(session, with_content_key=True)

        with db.session_scope(commit=False) as session:
            weights = compute_weights(session)
            assert weights.genres.get("Action", 0.0) > 0.0
            results = score_candidates(session, weights, limit=30)

        cand_results = [r for r in results if r.channel_id in ("ch-en", "ch-se")]
        assert len(cand_results) == 1, (
            f"localized-title variants sharing a content_key must collapse to one card; "
            f"got {[r.channel_id for r in cand_results]}"
        )
        assert cand_results[0].variant_count == 2, (
            f"variant_count must reflect both copies; got {cand_results[0].variant_count}"
        )
        db.close()

    def test_without_content_key_titles_split(self, tmp_path):
        """Contrast: with no content_key the runtime fingerprint splits the two titles."""
        from metatv.core.preference_engine import compute_weights, score_candidates

        db = _make_db(tmp_path / "recs_nock.db")
        with db.session_scope() as session:
            self._seed(session, with_content_key=False)

        with db.session_scope(commit=False) as session:
            weights = compute_weights(session)
            results = score_candidates(session, weights, limit=30)

        ids = {r.channel_id for r in results if r.channel_id in ("ch-en", "ch-se")}
        assert ids == {"ch-en", "ch-se"}, (
            f"without content_key the differing titles must NOT collapse (fallback path); got {ids}"
        )
        db.close()


# ---------------------------------------------------------------------------
# 2. Similar Titles — content_key collapses variants in _bg_fetch_similar_titles
# ---------------------------------------------------------------------------

class TestSimilarContentKeyDedup:
    """_bg_fetch_similar_titles groups candidates on stored content_key when present."""

    def _fake_config(self):
        return SimpleNamespace(
            preferred_version_prefixes=[],
            preferred_version_provider_ids=[],
            preferred_version_quality=None,
        )

    def _make_mixin(self, db):
        from metatv.gui.main_window_metadata import _MetadataMixin

        emitted: list[tuple] = []

        class _FakeSignal:
            def emit(self, cid, titles):
                emitted.append((cid, titles))

        obj = _MetadataMixin.__new__(_MetadataMixin)
        obj.db = db
        obj.config = self._fake_config()
        obj._similar_titles_loaded = _FakeSignal()
        obj._emitted = emitted
        return obj

    def _seed(self, session, *, variant_content_key: str | None):
        # Origin has its own (distinct) content_key so it isn't filtered as "same as current".
        _make_channel(
            session, cid="ch-origin", name="EN The Bridge Origin", media_type="series",
            content_key="origin|series", detected_prefix="EN",
            detected_title="The Bridge Origin",
        )
        # Two variants of one production: different titles, SAME content_key.  Both names
        # contain "Bridge" so both surface as similar-title candidates.
        _make_channel(
            session, cid="ch-a", name="EN The Bridge Saga", media_type="series",
            content_key=variant_content_key, detected_prefix="EN",
            detected_title="The Bridge Saga",
        )
        _make_channel(
            session, cid="ch-b", name="SE The Bridge Bron", media_type="series",
            content_key=variant_content_key, detected_prefix="SE",
            detected_title="The Bridge Bron",
        )
        # A genuinely distinct production (different content_key) that must stay separate.
        _make_channel(
            session, cid="ch-c", name="EN The Bridge Other", media_type="series",
            content_key="other bridge|series" if variant_content_key else None,
            detected_prefix="EN", detected_title="The Bridge Other",
        )

    def _run(self, obj):
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(obj._bg_fetch_similar_titles, "ch-origin").result(timeout=10)
        assert obj._emitted, "No similar-titles signal was emitted"
        _, titles = obj._emitted[0]
        return {v.channel_id for v in titles}

    def test_shared_content_key_variants_collapse(self, tmp_path):
        db = _make_db(tmp_path / "sim_ck.db")
        with db.session_scope() as session:
            self._seed(session, variant_content_key="bridge|series")

        ids = self._run(self._make_mixin(db))

        assert ("ch-a" in ids) ^ ("ch-b" in ids), (
            f"the two same-content_key variants must collapse to exactly one Similar row; got {ids}"
        )
        assert "ch-c" in ids, "a distinct-content_key sibling must remain separate"
        db.close()

    def test_null_content_key_falls_back_to_title_grouping(self, tmp_path):
        """With no content_key the differing titles split (runtime fingerprint fallback)."""
        db = _make_db(tmp_path / "sim_nock.db")
        with db.session_scope() as session:
            self._seed(session, variant_content_key=None)

        ids = self._run(self._make_mixin(db))

        assert "ch-a" in ids and "ch-b" in ids, (
            f"null-content_key variants with different titles must NOT collapse; got {ids}"
        )
        db.close()


# ---------------------------------------------------------------------------
# 3. MULTI token → same content_key as the plain sibling (flag 1ebe93bb)
# ---------------------------------------------------------------------------

class TestMultiTokenContentKey:
    """A bare trailing 'MULTI' audio token no longer splits the content_key."""

    def test_pure_function_multi_matches_plain_sibling(self):
        from metatv.core.content_identity import content_key_for

        def _proxy(title, mt, year=""):
            return SimpleNamespace(detected_title=title, media_type=mt,
                                   detected_year=year, id="x")

        # series — year omitted from key
        assert (content_key_for(_proxy("The Bridge MULTI", "series"))
                == content_key_for(_proxy("The Bridge", "series")))
        # movie — year retained, MULTI still stripped
        assert (content_key_for(_proxy("The Killing MULTI", "movie", "2011"))
                == content_key_for(_proxy("The Killing", "movie", "2011")))
        # "MULTI SUB" trailing run also collapses
        assert (content_key_for(_proxy("The Bridge MULTI SUB", "series"))
                == content_key_for(_proxy("The Bridge", "series")))
        # MUTI typo variant collapses too
        assert (content_key_for(_proxy("The Bridge MUTI", "series"))
                == content_key_for(_proxy("The Bridge", "series")))

    def test_real_words_preserved(self):
        from metatv.core.content_identity import content_key_for

        def _proxy(title, mt):
            return SimpleNamespace(detected_title=title, media_type=mt,
                                   detected_year="", id="x")

        # "multi"/"sub"/"dual" as part of a real title (no MULTI anchor at the tail, or
        # the whole title) must NOT be stripped.
        assert content_key_for(_proxy("Multiplicity", "movie")) == "multiplicity|movie|"
        assert content_key_for(_proxy("Dual Survival", "series")) == "dual survival|series"
        assert content_key_for(_proxy("The Sub", "movie")) == "the sub|movie|"
        assert content_key_for(_proxy("Multi", "movie")) == "multi|movie|"  # never empties the title

    def test_backfill_recompute_collapses_multi_variant(self, tmp_path):
        """The real backfill path recomputes content_key so a MULTI row matches its sibling.

        Recomputes only the generated content_key column — user data is untouched.
        """
        from metatv.core.repositories import RepositoryFactory

        db = _make_db(tmp_path / "multi_backfill.db")
        with db.session_scope() as session:
            # Pre-fix stored keys (as they would have been ingested before this change).
            _make_channel(
                session, cid="ch-multi", name="NF The Bridge MULTI", media_type="series",
                detected_title="The Bridge MULTI", content_key="the bridge multi|series",
            )
            _make_channel(
                session, cid="ch-plain", name="NF The Bridge", media_type="series",
                detected_title="The Bridge", content_key="the bridge|series",
            )

        with db.session_scope() as session:
            RepositoryFactory(session).channels.backfill_content_keys(recompute_all=True)

        from metatv.core.database import ChannelDB
        with db.session_scope(commit=False) as session:
            multi = session.get(ChannelDB, "ch-multi").content_key
            plain = session.get(ChannelDB, "ch-plain").content_key

        assert multi == plain == "the bridge|series", (
            f"backfill must recompute the MULTI row onto the plain key; got {multi!r} vs {plain!r}"
        )
        db.close()
