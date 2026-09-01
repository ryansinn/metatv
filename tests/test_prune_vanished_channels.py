"""Rows a source has stopped listing are removed; engaged ones never are.

Ingestion has always been upsert-only. Nothing removed a row the source dropped,
so they accumulated for ever — measured on the owner's library, their provider
re-issues each event slot with a NEW stream id per fixture, leaving **1,960 rows
for 980 slots, exactly 2:1**. 1,358 of the orphans carry no event time and land
in the Sports "Channels" lane, which is part of why it read 6,523.

The dangerous direction here is deletion, so most of this file is about what must
NOT be deleted:

* **engaged rows** — favourited, played, queued. The settled rule is flag
  engaged-unavailable, never delete it, and they stay reachable in History and
  Favourites.
* **rows never observed** (``last_seen_at IS NULL``). Deleting on an absence of
  evidence is the mistake #642 recorded about inferring a first launch from four
  empty lists.
* **other sources**, obviously.
* **everything, when too much looks vanished at once.** A truncated fetch is
  indistinguishable from a shrunken catalog at the point of the delete.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from metatv.core.database import ChannelDB, Database
from metatv.core.repositories.channel import ChannelRepository

OLD = datetime(2026, 8, 30)
NEW = datetime(2026, 9, 1)


@pytest.fixture
def db(tmp_path):
    """A real Database on a real file — :memory: is forbidden for session work."""
    database = Database(f"sqlite:///{tmp_path / 'prune.db'}")
    database.create_tables()
    return database


def _ch(cid, provider="p", **kw):
    return ChannelDB(id=cid, source_id=cid, provider_id=provider, name=cid, **kw)


def _seed(db, rows):
    with db.session_scope() as session:
        session.add_all(rows)


def _ids(db):
    with db.session_scope() as session:
        return {r.id for r in session.query(ChannelDB).all()}


def _prune(db, provider="p", seen_at=NEW):
    with db.session_scope() as session:
        return ChannelRepository(session).prune_vanished_channels(provider, seen_at)


#: Enough rows that one vanishing is a small fraction — the ceiling is a ratio,
#: and on a five-row fixture every question becomes a question about the ceiling.
def _filler(n=16):
    return [_ch(f"keep{i}", last_seen_at=NEW) for i in range(n)]


def test_a_row_the_source_stopped_listing_is_removed(db):
    _seed(db, _filler() + [_ch("gone", last_seen_at=OLD)])

    counts = _prune(db)

    assert counts["channels"] == 1
    assert "gone" not in _ids(db)
    assert "keep0" in _ids(db), "a still-listed row was taken with it"


@pytest.mark.parametrize("field,value", [
    ("is_favorite", True),
    ("play_count", 3),
    ("last_played", NEW),
])
def test_an_engaged_row_survives_vanishing(db, field, value):
    """Flag engaged-unavailable, never delete it — the settled rule."""
    _seed(db, _filler() + [_ch("engaged", last_seen_at=OLD, **{field: value})])

    _prune(db)

    assert "engaged" in _ids(db), f"a row with {field} set was deleted"


def test_a_never_observed_row_is_never_pruned(db):
    """NULL is not evidence of absence.

    The seed migration stamps every existing row, so a NULL afterwards means
    something wrote a channel without going through the catalog upsert. Guessing
    it is gone would delete rows nothing has ever reported on.

    Two layers protect this and the test pins the OUTCOME rather than either one:
    the explicit ``isnot(None)`` filter, and SQL's own ``NULL < :t`` evaluating to
    NULL. Removing the filter alone leaves the suite green, which is correct —
    the behaviour is unchanged. What would break it is a rewrite to
    ``COALESCE(last_seen_at, 0) < :t``, and that this test would catch.
    """
    _seed(db, _filler() + [_ch("unobserved", last_seen_at=None)])

    _prune(db)

    assert "unobserved" in _ids(db)


def test_another_source_is_untouched(db):
    _seed(db, _filler() + [_ch("other", provider="q", last_seen_at=OLD)])

    _prune(db, provider="p")

    assert "other" in _ids(db)


def test_a_row_seen_in_this_very_refresh_is_not_vanished(db):
    """The boundary is strict: stamped AT `seen_at` means present, not stale."""
    _seed(db, _filler() + [_ch("edge", last_seen_at=NEW)])

    counts = _prune(db, seen_at=NEW)

    assert counts["channels"] == 0
    assert "edge" in _ids(db)


# ── the ceiling ─────────────────────────────────────────────────────────────

def test_a_wholesale_disappearance_is_refused_not_obeyed(db):
    """A truncated fetch and a shrunken catalog look identical here.

    A source answering with a tenth of its channels would otherwise take 90% of
    the library, unrecoverably. Above the ceiling nothing is deleted and the
    refusal is logged — the next refresh can try again with a full answer.
    """
    _seed(db, [_ch(f"gone{i}", last_seen_at=OLD) for i in range(9)]
              + [_ch("survivor", last_seen_at=NEW)])

    counts = _prune(db)

    assert counts["channels"] == 0, "90% of the source was deleted on one bad fetch"
    assert len(_ids(db)) == 10, "rows were removed despite the refusal"


def test_the_ceiling_does_not_block_ordinary_churn(db):
    """Non-degeneracy: a ceiling that refuses everything is not a safety feature.

    The owner's real churn is ~980 of 785,552 rows — about 0.1%. This asserts the
    guard is nowhere near that, so the fix still does its job.
    """
    _seed(db, _filler(19) + [_ch("gone", last_seen_at=OLD)])

    counts = _prune(db)

    assert counts["channels"] == 1, "ordinary churn was refused by the ceiling"


def test_nothing_to_prune_returns_zero_without_touching_anything(db):
    _seed(db, _filler())
    counts = _prune(db)
    assert counts == dict.fromkeys(counts, 0)
    assert len(_ids(db)) == 16


def test_a_missing_provider_or_instant_is_a_no_op(db):
    """Defensive: never let a caller with nothing to say delete something."""
    _seed(db, _filler() + [_ch("gone", last_seen_at=OLD)])

    assert _prune(db, provider="", seen_at=NEW)["channels"] == 0
    assert _prune(db, provider="p", seen_at=None)["channels"] == 0
    assert "gone" in _ids(db)
