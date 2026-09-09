"""D52: the channel-delete cascade keys Season/EpisodeDB the wrong way.

``SeasonDB``/``EpisodeDB.series_id`` hold the provider's own series id
(``ChannelDB.source_id``), never ``ChannelDB.id`` — the same key mismatch
SERIES-2 (#822) fixed in ``series_monitor.py``'s baseline fast path.
``channel_pruning.py`` had the identical mistake in two places:

* ``_delete_channel_cascade`` (shared by ``prune_vanished_channels`` and
  ``prune_provider_content``'s channel-level step) filtered
  ``EpisodeDB``/``SeasonDB.series_id`` against a ``ChannelDB.id`` subquery,
  which can never match — so a deleted channel's seasons/episodes were
  silently LEAKED (never removed), a latent bug (0 orphans measured in the
  owner's real library at the time this was found).

* ``prune_provider_content``'s Step 4 ("kept" series are spared) had the
  SAME id-vs-source_id mismatch in its ``kept_series_subq`` — and this one is
  ACTIVELY DANGEROUS, not latent: because the "this episode's series is
  still around, so keep it" check could never match, a provider delete would
  strip seasons/episodes from an ENGAGED (favorited) series that survived the
  delete, unless the individual episode itself happened to carry watch-state
  (the one floor that DOES work regardless of the key bug).

Both are fixed via one correlated-``EXISTS`` helper,
``_ChannelPruningMixin._series_channel_exists()``, keyed on
``(ChannelDB.source_id, ChannelDB.provider_id)`` — never ``source_id`` alone,
because ``source_id`` collides across providers (confirmed in the owner's
real library, same finding SERIES-2 recorded). Every test below that matters
pairs a "this table" case with a same-``source_id``-different-``provider_id``
collision case, proving the fix doesn't just start matching — it matches the
right row.

Per CLAUDE.md: real file-backed ``Database`` (``tmp_path``, never
``:memory:``).
"""

from __future__ import annotations

from datetime import datetime

import pytest

from metatv.core.database import ChannelDB, Database, EpisodeDB, SeasonDB
from metatv.core.repositories.channel import ChannelRepository

OLD = datetime(2026, 8, 30)
NEW = datetime(2026, 9, 1)


@pytest.fixture
def db(tmp_path):
    """A real Database on a real file — :memory: is forbidden for session work."""
    database = Database(f"sqlite:///{tmp_path / 'd52.db'}")
    database.create_tables()
    return database


def _channel(cid, source_id, provider="p", **kw):
    return ChannelDB(
        id=cid, source_id=source_id, provider_id=provider, name=cid,
        media_type="series", **kw,
    )


def _season_id(series_id, provider="p", num=1):
    """Pure id builder — never read ``.id`` off a SeasonDB after its seeding
    session closes (DetachedInstanceError, CLAUDE.md 'ORM objects must not
    outlive their session'); compute the same string independently instead."""
    return f"{provider}_{series_id}_s{num}"


def _season(series_id, provider="p", num=1):
    return SeasonDB(
        id=_season_id(series_id, provider, num), series_id=series_id,
        provider_id=provider, season_number=num,
    )


def _episode(eid, series_id, season_id, provider="p", num=1, **kw):
    return EpisodeDB(
        id=eid, season_id=season_id, series_id=series_id, provider_id=provider,
        episode_id=eid, episode_num=num, season_num=1, title=f"ep{num}", **kw,
    )


def _seed(db, rows):
    with db.session_scope() as session:
        session.add_all(rows)


def _season_ids(db):
    with db.session_scope() as session:
        return {s.id for s in session.query(SeasonDB).all()}


def _episode_ids(db):
    with db.session_scope() as session:
        return {e.id for e in session.query(EpisodeDB).all()}


# ── _delete_channel_cascade, via prune_vanished_channels ────────────────────
# Enough filler rows that one vanishing is a small fraction of the provider's
# catalog — prune_vanished_channels refuses a wholesale disappearance.


def _filler(n=16, provider="p"):
    return [_channel(f"keep{i}", f"src-keep{i}", provider=provider, last_seen_at=NEW)
            for i in range(n)]


def test_vanished_channel_takes_its_seasons_and_episodes_with_it(db):
    """The leak: a non-engaged channel's Season/EpisodeDB rows, correctly keyed
    by (source_id, provider_id), must actually be deleted alongside it."""
    sid, eid = _season_id("gone-src", "p"), "ep1"
    seas = _season("gone-src", provider="p")
    ep = _episode(eid, "gone-src", sid, provider="p")
    _seed(db, _filler() + [
        _channel("gone", "gone-src", provider="p", last_seen_at=OLD),
        seas, ep,
    ])

    with db.session_scope() as session:
        counts = ChannelRepository(session).prune_vanished_channels("p", NEW)

    assert counts["channels"] == 1
    assert counts["seasons"] == 1, "the vanished channel's season was not pruned"
    assert counts["episodes"] == 1, "the vanished channel's episode was not pruned"
    assert sid not in _season_ids(db)
    assert eid not in _episode_ids(db)


def test_a_colliding_source_id_on_another_provider_survives(db):
    """source_id collides across providers (confirmed in the owner's real
    library) — pruning provider p's vanished series must never reach across
    and delete provider q's same-source_id season/episode rows."""
    # Provider p: vanishing, non-engaged series with source_id "100".
    sid_p, eid_p = _season_id("100", "p"), "p_ep1"
    seas_p = _season("100", provider="p")
    ep_p = _episode(eid_p, "100", sid_p, provider="p")
    # Provider q: an unrelated, currently-listed series that happens to share
    # the SAME bare source_id "100".
    sid_q, eid_q = _season_id("100", "q"), "q_ep1"
    seas_q = _season("100", provider="q")
    ep_q = _episode(eid_q, "100", sid_q, provider="q")

    _seed(db, _filler() + [
        _channel("gone", "100", provider="p", last_seen_at=OLD),
        seas_p, ep_p,
        _channel("other", "100", provider="q", last_seen_at=NEW),
        seas_q, ep_q,
    ])

    with db.session_scope() as session:
        ChannelRepository(session).prune_vanished_channels("p", NEW)

    assert sid_p not in _season_ids(db), "provider p's season should be gone"
    assert eid_p not in _episode_ids(db), "provider p's episode should be gone"
    assert sid_q in _season_ids(db), \
        "provider q's same-source_id season was wrongly deleted"
    assert eid_q in _episode_ids(db), \
        "provider q's same-source_id episode was wrongly deleted"


@pytest.mark.parametrize("field,value", [
    ("is_favorite", True),
    ("play_count", 3),
    ("last_played", NEW),
])
def test_an_engaged_vanished_channels_seasons_and_episodes_survive(db, field, value):
    """Flag engaged-unavailable, never delete it — applies to the child rows too."""
    sid, eid = _season_id("eng-src", "p"), "eng_ep1"
    seas = _season("eng-src", provider="p")
    ep = _episode(eid, "eng-src", sid, provider="p")
    _seed(db, _filler() + [
        _channel("engaged", "eng-src", provider="p", last_seen_at=OLD, **{field: value}),
        seas, ep,
    ])

    with db.session_scope() as session:
        ChannelRepository(session).prune_vanished_channels("p", NEW)

    assert sid in _season_ids(db), f"engaged (via {field}) channel's season was pruned"
    assert eid in _episode_ids(db), f"engaged (via {field}) channel's episode was pruned"


# ── prune_provider_content Step 4: the actively-dangerous direction ─────────


def test_provider_delete_prunes_a_nonengaged_series_seasons_and_episodes(db):
    sid, eid = _season_id("doomed-src", "pA"), "d_ep1"
    seas = _season("doomed-src", provider="pA")
    ep = _episode(eid, "doomed-src", sid, provider="pA")
    _seed(db, [
        _channel("doomed", "doomed-src", provider="pA"),
        seas, ep,
    ])

    with db.session_scope() as session:
        counts = ChannelRepository(session).prune_provider_content(["pA"])

    assert counts["seasons"] == 1
    assert counts["episodes"] == 1
    assert sid not in _season_ids(db)
    assert eid not in _episode_ids(db)


def test_provider_delete_spares_a_kept_favorited_series_seasons_and_episodes(db):
    """The actively-dangerous case: a FAVORITED series survives the provider
    delete (it is 'engaged'), and its seasons/episodes — which carry no
    individual watch-state of their own — must survive with it. Pre-fix, the
    id-vs-source_id key mismatch meant the 'is this series kept?' check could
    never match, so these rows were deleted anyway."""
    sid, eid = _season_id("kept-src", "pA"), "k_ep1"
    seas = _season("kept-src", provider="pA")
    ep = _episode(eid, "kept-src", sid, provider="pA")
    _seed(db, [
        _channel("kept", "kept-src", provider="pA", is_favorite=True),
        seas, ep,
    ])

    with db.session_scope() as session:
        counts = ChannelRepository(session).prune_provider_content(["pA"])

    assert counts["seasons"] == 0, "a kept (favorited) series' season was deleted"
    assert counts["episodes"] == 0, "a kept (favorited) series' episode was deleted"
    assert sid in _season_ids(db)
    assert eid in _episode_ids(db)


def test_provider_delete_collision_kept_on_one_provider_doomed_on_another(db):
    """The sharpest case: providers pA (doomed series) and pB (kept, favorited
    series) are purged TOGETHER, and both series share the SAME bare
    source_id. Only pA's rows may go; pB's must survive despite the
    collision."""
    sid_a, eid_a = _season_id("100", "pA"), "a_ep1"
    seas_a = _season("100", provider="pA")
    ep_a = _episode(eid_a, "100", sid_a, provider="pA")
    sid_b, eid_b = _season_id("100", "pB"), "b_ep1"
    seas_b = _season("100", provider="pB")
    ep_b = _episode(eid_b, "100", sid_b, provider="pB")

    _seed(db, [
        _channel("doomed", "100", provider="pA"),
        seas_a, ep_a,
        _channel("kept", "100", provider="pB", is_favorite=True),
        seas_b, ep_b,
    ])

    with db.session_scope() as session:
        counts = ChannelRepository(session).prune_provider_content(["pA", "pB"])

    assert counts["seasons"] == 1
    assert counts["episodes"] == 1
    assert sid_a not in _season_ids(db), "provider pA's season should be gone"
    assert eid_a not in _episode_ids(db), "provider pA's episode should be gone"
    assert sid_b in _season_ids(db), \
        "provider pB's kept series lost its season to a source_id collision"
    assert eid_b in _episode_ids(db), \
        "provider pB's kept series lost its episode to a source_id collision"


def test_provider_delete_still_spares_a_watched_orphan_episode(db):
    """The existing sacrosanct-history floor (Step 4) still applies on top of
    the key fix: an episode with no surviving series channel at all, but with
    user watch-state, is spared regardless."""
    sid, eid = _season_id("truly-gone-src", "pA"), "watched_ep1"
    seas = _season("truly-gone-src", provider="pA")
    ep = _episode(
        eid, "truly-gone-src", sid, provider="pA",
        is_watched=True, last_played=NEW, play_count=1,
    )
    # No ChannelDB row for "truly-gone-src" at all — a pre-existing orphan.
    _seed(db, [seas, ep])

    with db.session_scope() as session:
        counts = ChannelRepository(session).prune_provider_content(["pA"])

    assert counts["episodes"] == 0, "a watched orphan episode must not be deleted"
    assert eid in _episode_ids(db)
    # Seasons carry no such floor — the pre-existing, documented behaviour.
    assert counts["seasons"] == 1
    assert sid not in _season_ids(db)
