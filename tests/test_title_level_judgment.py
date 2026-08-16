"""Preference-engine signals must judge a TITLE, not each provider row.

The same production usually exists as several ChannelDB rows — one per
provider/language variant. Two consequences the collapse-at-read fix (see
CLAUDE.md "Content identity") must close:

  1. ``compute_weights`` used to accumulate one signal per rated/favorited
     ChannelDB row, so rating three language variants of one film tripled its
     genre/director/actor weight and could let a single title's cast alone
     clear the ``actor_min_support`` corroboration gate.
  2. ``disliked_ids`` was channel_id-keyed, so disliking one variant left
     every sibling copy fully recommendable.

Both are fixed by collapsing at read on the canonical stored ``content_key``
(never re-keying ``UserRatingDB`` itself — user ratings stay channel_id-keyed
and untouched). All DB tests use a file-backed tmp_path SQLite, not
``:memory:``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(path: Path):
    from metatv.core.database import Database
    db = Database(f"sqlite:///{path}")
    db.create_tables()
    return db


def _make_metadata(session, title: str, genres=None, year: int | None = None,
                    cast=None):
    from metatv.core.database import MetadataDB
    meta = MetadataDB(
        id=str(uuid.uuid4()),
        title=title,
        genres=genres or [],
        year=year,
        cast=cast,
    )
    session.add(meta)
    session.flush()
    return meta


def _make_channel(session, *, cid: str | None = None, name: str,
                  media_type: str = "movie",
                  content_key: str | None = None,
                  detected_prefix: str | None = None,
                  metadata_id: str | None = None,
                  last_played: datetime | None = None,
                  is_favorite: bool = False,
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
        metadata_id=metadata_id,
        last_played=last_played,
        is_favorite=is_favorite,
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
# 1. Weights do not multiply across variants of one title
# ---------------------------------------------------------------------------

def test_weights_do_not_multiply_across_rated_variants(tmp_path):
    """Three variants of one title, all rated +1, must weigh the same as one."""
    from metatv.core.preference_engine import compute_weights

    # Control: a single rated channel for the title.
    db_ctrl = _make_db(tmp_path / "control.db")
    with db_ctrl.session_scope() as session:
        meta = _make_metadata(session, "Control Movie", genres=["Action"])
        ch = _make_channel(session, name="EN Control Movie",
                           content_key="control|movie", metadata_id=meta.id)
        _make_rating(session, ch.id, 1)
    with db_ctrl.session_scope(commit=False) as session:
        control_weights = compute_weights(session)
    expected = control_weights.genres["Action"]
    assert expected > 0.0
    db_ctrl.close()

    # Test: three provider/language variants of the same title, all rated +1.
    db = _make_db(tmp_path / "variants.db")
    with db.session_scope() as session:
        meta = _make_metadata(session, "Variant Movie", genres=["Action"])
        for i in range(3):
            ch = _make_channel(session, name=f"V{i} Variant Movie",
                               content_key="variant|movie", metadata_id=meta.id)
            _make_rating(session, ch.id, 1)
    with db.session_scope(commit=False) as session:
        weights = compute_weights(session)

    assert weights.genres["Action"] == pytest.approx(expected), (
        f"rating 3 content_key-sharing variants must weigh the SAME as rating "
        f"one (expected {expected}); got {weights.genres['Action']} — genre "
        f"weight is being multiplied by variant count"
    )
    db.close()


# ---------------------------------------------------------------------------
# 2. actor_support corroboration gate survives variant collapse
# ---------------------------------------------------------------------------

def test_actor_corroboration_gate_survives_variant_collapse(tmp_path):
    """An actor seen only in ONE title (via 3 rated rows) must not clear the gate."""
    from metatv.core.preference_engine import compute_weights

    db = _make_db(tmp_path / "actor.db")
    with db.session_scope() as session:
        meta = _make_metadata(session, "One Title", genres=["Action"],
                              cast=[{"name": "Sole Actor"}])
        for i in range(3):
            ch = _make_channel(session, name=f"V{i} One Title",
                               content_key="one-title|movie", metadata_id=meta.id)
            _make_rating(session, ch.id, 1)

    with db.session_scope(commit=False) as session:
        weights = compute_weights(session)

    assert "Sole Actor" not in weights.actors, (
        "an actor appearing in only ONE rated TITLE (default actor_min_support=2) "
        "must be pruned by the corroboration gate even though it was rated via "
        "three provider-row variants — variant collapse must count it as ONE "
        "appearance, not three"
    )
    db.close()


# ---------------------------------------------------------------------------
# 3. Counts describe titles, not rows
# ---------------------------------------------------------------------------

def test_counts_describe_titles_not_rows(tmp_path):
    from metatv.core.preference_engine import compute_weights

    db = _make_db(tmp_path / "counts.db")
    with db.session_scope() as session:
        meta1 = _make_metadata(session, "Title One", genres=["Action"])
        for i in range(3):
            ch = _make_channel(session, name=f"V{i} Title One",
                               content_key="title-one|movie", metadata_id=meta1.id)
            _make_rating(session, ch.id, 1)

    with db.session_scope(commit=False) as session:
        weights = compute_weights(session)

    assert weights.rated_count == 1, (
        f"3 rated variants of ONE title must count as 1 rated title; "
        f"got rated_count={weights.rated_count}"
    )
    assert weights.liked_count == 1
    assert weights.disliked_count == 0

    # A second, genuinely different title — proves the count tracks distinct
    # titles rather than always collapsing to 1.
    with db.session_scope() as session:
        meta2 = _make_metadata(session, "Title Two", genres=["Drama"])
        ch2 = _make_channel(session, name="Title Two",
                            content_key="title-two|movie", metadata_id=meta2.id)
        _make_rating(session, ch2.id, 1)

    with db.session_scope(commit=False) as session:
        weights2 = compute_weights(session)

    assert weights2.rated_count == 2, (
        f"adding a second distinct title must bring rated_count to 2; "
        f"got {weights2.rated_count}"
    )
    assert weights2.liked_count == 2
    db.close()


# ---------------------------------------------------------------------------
# 4. Rows with no content_key stay distinct
# ---------------------------------------------------------------------------

def test_no_content_key_rows_stay_distinct(tmp_path):
    from metatv.core.preference_engine import compute_weights

    db = _make_db(tmp_path / "nock.db")
    with db.session_scope() as session:
        meta = _make_metadata(session, "Unenriched Movie", genres=["Action"])
        ch1 = _make_channel(session, name="Copy A", content_key=None,
                            metadata_id=meta.id)
        ch2 = _make_channel(session, name="Copy B", content_key=None,
                            metadata_id=meta.id)
        _make_rating(session, ch1.id, 1)
        _make_rating(session, ch2.id, 1)

    with db.session_scope(commit=False) as session:
        weights = compute_weights(session)

    assert weights.rated_count == 2, (
        f"two rated channels with content_key=None must stay two DISTINCT "
        f"signals (fallback 'id:'+channel.id key) — over-merging unenriched "
        f"rows would silently drop taste signal; got rated_count={weights.rated_count}"
    )
    db.close()


# ---------------------------------------------------------------------------
# 6. Explicit rating beats an implicit favorite within one title group
# ---------------------------------------------------------------------------

def test_explicit_rating_beats_favorite_in_same_title(tmp_path):
    from metatv.core.preference_engine import compute_weights

    db = _make_db(tmp_path / "explicit_vs_fav.db")
    with db.session_scope() as session:
        meta = _make_metadata(session, "Torn Movie", genres=["Horror"])
        _make_channel(
            session, name="EN Torn Movie", content_key="torn|movie",
            metadata_id=meta.id, is_favorite=True,
        )
        ch_dis = _make_channel(
            session, name="FR Torn Movie", content_key="torn|movie",
            metadata_id=meta.id,
        )
        _make_rating(session, ch_dis.id, -1)

    with db.session_scope(commit=False) as session:
        weights = compute_weights(session)

    assert weights.genres.get("Horror", 0.0) < 0.0, (
        f"an explicit dislike must win over an implicit (+0.5) favorite signal "
        f"within the same title group; got genres['Horror']="
        f"{weights.genres.get('Horror', 0.0)}"
    )
    assert weights.disliked_count == 1
    assert weights.liked_count == 0
    db.close()
