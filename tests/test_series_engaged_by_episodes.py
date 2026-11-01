"""A series watched episode by episode survives a source delete (ledger F60 gap).

The series row never records a play when you watch its episodes, so the engaged
rule — favourited / played / queued / rated — missed it: a delete dropped the
series and stranded its watched episodes (13 such rows on the owner's library).
"""

from __future__ import annotations

from metatv.core.database import ChannelDB, EpisodeDB, ProviderDB
from metatv.core.repositories import RepositoryFactory


def _seed(db):
    with db.session_scope() as s:
        s.add(ProviderDB(id="p", name="P", type="xtream", url="http://p", username="u", password="p"))
        for cid, src in (("watched-series", "s1"), ("untouched-series", "s2")):
            s.add(ChannelDB(id=cid, source_id=src, provider_id="p", name=cid, media_type="series"))
        s.add(EpisodeDB(id="e1", season_id="x", series_id="s1", provider_id="p", episode_id="e1",
                        episode_num=1, season_num=1, title="Pilot", is_watched=True, play_count=1))
        s.add(EpisodeDB(id="e2", season_id="y", series_id="s2", provider_id="p", episode_id="e2",
                        episode_num=1, season_num=1, title="Pilot"))


def test_a_series_watched_by_episode_is_kept_with_its_episodes(db):
    _seed(db)
    with db.session_scope() as s:
        RepositoryFactory(s).channels.prune_provider_content(["p"])
    with db.session_scope() as s:
        assert {c.id for c in s.query(ChannelDB)} == {"watched-series"}
        assert {e.id for e in s.query(EpisodeDB)} == {"e1"}


def test_the_series_is_engaged_by_the_shared_predicate(db):
    _seed(db)
    with db.session_scope() as s:
        repo = RepositoryFactory(s).channels
        engaged = {c.id for c in s.query(ChannelDB).filter(repo._engaged_channel_predicate())}
    assert engaged == {"watched-series"}
