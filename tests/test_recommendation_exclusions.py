"""Recommendations honor the Global Filter exclusions (core-thesis: exclusions everywhere).

Bug: the sidebar Recommended section applied only the category blacklist
(``get_active_category_filter``) and never unioned in the explicit "Block [PREFIX]"
codes (``get_excluded_prefixes``) — so a per-language block (DE/PL) leaked into
recommendations even though the same block is honored by Discover and Similar.

The fix routes both the recommendation call site (``RecommendedSection._bg_refresh``)
and ``get_similar_channels`` through ONE shared, pause-aware chokepoint,
``filter_utils.get_effective_excluded_prefixes``. These tests guard:

1. the helper itself (unit — the exact regression: a prefix-only config must yield the
   blocked prefix, which the pre-fix single-resolver call returned as ``None``), and
2. that the resolved set actually drops the excluded language from real
   ``score_candidates`` output (engine — the recommendation path end to end).

Both are non-Qt (real ``Database`` on a ``tmp_path`` file, per the Tests rule).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy.orm import sessionmaker

from metatv.core.database import ChannelDB, MetadataDB, UserRatingDB
from metatv.core.filter_utils import get_effective_excluded_prefixes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg(*, excluded_categories=None, excluded_prefixes=None,
         include_uncategorized=True, paused=False):
    """Duck-typed Config carrying only the Global-Filter fields the resolvers read."""
    return SimpleNamespace(
        global_filter_paused=paused,
        global_filter_excluded_categories=list(excluded_categories or []),
        global_filter_excluded_prefixes=list(excluded_prefixes or []),
        global_filter_include_uncategorized=include_uncategorized,
    )


def _make_db(path: Path):
    from metatv.core.database import Database
    db = Database(f"sqlite:///{path}")
    db.create_tables()
    return db


def _make_metadata(session, title: str, genres=None, year: int | None = None) -> MetadataDB:
    meta = MetadataDB(id=str(uuid.uuid4()), title=title, genres=genres or [], year=year)
    session.add(meta)
    session.flush()
    return meta


def _make_channel(session, name, metadata_id, detected_prefix=None,
                  last_played=None, provider_id="p1") -> ChannelDB:
    ch = ChannelDB(
        id=str(uuid.uuid4()), source_id=str(uuid.uuid4()), provider_id=provider_id,
        name=name, media_type="movie", metadata_id=metadata_id,
        detected_prefix=detected_prefix, is_hidden=False, last_played=last_played,
    )
    session.add(ch)
    session.flush()
    return ch


# ---------------------------------------------------------------------------
# 1. The shared chokepoint (unit) — the exact regression guard
# ---------------------------------------------------------------------------

class TestEffectiveExcludedPrefixes:
    def test_block_prefix_only_is_included(self):
        """A prefix-only config (empty categories) must still yield the blocked prefix.

        THE regression: the pre-fix call used get_active_category_filter alone, which
        returns None here (no categories) → DE leaked. The union must surface DE.
        """
        excluded, include_uncat = get_effective_excluded_prefixes(
            _cfg(excluded_prefixes=["DE"])
        )
        assert excluded == ["DE"]
        assert include_uncat is True

    def test_unions_categories_and_prefixes(self):
        excluded, _ = get_effective_excluded_prefixes(
            _cfg(excluded_categories=["AR"], excluded_prefixes=["DE"])
        )
        assert set(excluded) == {"AR", "DE"}

    def test_paused_returns_none_even_with_blocks(self):
        """Paused → nothing excluded (a blocked prefix must NOT leak past the pause)."""
        excluded, include_uncat = get_effective_excluded_prefixes(
            _cfg(excluded_categories=["AR"], excluded_prefixes=["DE"], paused=True)
        )
        assert excluded is None
        assert include_uncat is True

    def test_config_none_returns_none(self):
        assert get_effective_excluded_prefixes(None) == (None, True)

    def test_empty_config_returns_none(self):
        assert get_effective_excluded_prefixes(_cfg()) == (None, True)

    def test_include_uncategorized_false_passes_through(self):
        excluded, include_uncat = get_effective_excluded_prefixes(
            _cfg(excluded_categories=["AR"], include_uncategorized=False)
        )
        assert excluded == ["AR"]
        assert include_uncat is False


# ---------------------------------------------------------------------------
# 2. score_candidates honors the resolved set (engine, end to end)
# ---------------------------------------------------------------------------

class TestRecommendationExclusionsApplied:
    def _seed(self, session):
        """One liked Action signal (→ non-empty weights) + an EN and a DE Action candidate.

        Distinct metadata per candidate so they don't dedup-collapse; both share the
        liked 'Action' genre so both score positive. Only detected_prefix distinguishes
        them for the Global-Filter test.
        """
        meta_signal = _make_metadata(session, "Liked Action", genres=["Action"], year=2020)
        meta_en = _make_metadata(session, "English Action Pick", genres=["Action"], year=2021)
        meta_de = _make_metadata(session, "German Action Pick", genres=["Action"], year=2022)

        # Liked signal: watched + rated +1 (a signal, not a candidate).
        signal = _make_channel(session, "EN - Liked Action", meta_signal.id,
                               detected_prefix="EN", last_played=datetime(2024, 1, 1))
        session.add(UserRatingDB(channel_id=signal.id, rating=1))

        cand_en = _make_channel(session, "EN - English Action Pick", meta_en.id,
                                detected_prefix="EN")
        cand_de = _make_channel(session, "DE - German Action Pick", meta_de.id,
                                detected_prefix="DE")
        session.commit()
        return cand_en.id, cand_de.id

    def test_blocked_prefix_dropped_from_recs(self, tmp_path):
        from metatv.core.preference_engine import compute_weights, score_candidates

        db = _make_db(tmp_path / "rec_excl.db")
        session = sessionmaker(bind=db.engine)()
        en_id, de_id = self._seed(session)

        weights = compute_weights(session)
        assert not weights.is_empty()

        # Baseline: no exclusion → the DE candidate is a valid recommendation.
        ids_all = {r.channel_id for r in score_candidates(session, weights, limit=30)}
        assert en_id in ids_all
        assert de_id in ids_all, "DE candidate should appear when nothing is excluded"

        # With DE blocked (the resolved set the fixed call site now produces) → DE gone.
        ids_excl = {
            r.channel_id
            for r in score_candidates(session, weights, limit=30,
                                      excluded_prefixes=["DE"], include_uncategorized=True)
        }
        assert en_id in ids_excl, "an un-excluded language stays recommended"
        assert de_id not in ids_excl, "a globally-excluded language must be dropped from recs"

        session.close()
        db.close()
