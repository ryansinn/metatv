"""Cross-source season-key collision regression — provider-scoped SeasonDB PK.

Two sources can host the same series under the *same* Xtream ``source_id`` (small
per-provider integers — collisions are common). Before the fix, ``SeasonDB`` ids
were ``"{series_id}_s{n}"`` with no provider prefix, so the second source's load
hit the first source's season rows in the UPDATE branch and silently kept the
first provider's ``provider_id`` — and the provider-scoped read
(``get_by_series``) then returned **0** seasons for the second source. That is the
"loaded South Park from one source → 28 seasons; from another → nothing" bug.

These tests drive the real storage path (``SeriesLoadThread.load_series``) with a
mocked provider plugin (no network) against a file-backed DB and assert each
source gets its own season+episode tree — i.e. they execute the changed code,
not a substring of it.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from metatv.core.database import Database, SeasonDB, EpisodeDB
from metatv.core.models import Provider
from metatv.core.provider_loader import SeriesLoadThread
from metatv.core.repositories import RepositoryFactory


@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def _series_info() -> dict:
    """A get_series_info payload with NO season metadata but episodes across two
    groups — the synthetic-season path the reported bug exercised."""
    return {
        "info": {"name": "South Park"},
        "seasons": [],
        "episodes": {
            "1": [
                {"id": "101", "episode_num": 1, "title": "S1E1", "container_extension": "mp4", "info": {}},
                {"id": "102", "episode_num": 2, "title": "S1E2", "container_extension": "mp4", "info": {}},
            ],
            "2": [
                {"id": "201", "episode_num": 1, "title": "S2E1", "container_extension": "mp4", "info": {}},
            ],
        },
    }


class _FakePlugin:
    """Stand-in provider plugin: returns canned series info, no network."""

    def __init__(self, info: dict) -> None:
        self._info = info

    async def fetch_series_info(self, provider, series_id):  # noqa: D401 - test stub
        return self._info


def _provider(pid: str) -> Provider:
    return Provider(id=pid, name=f"prov-{pid}", type="xtream",
                    url=f"http://host-{pid}", username="u", password="p")


def _load(db: Database, provider: Provider, series_id: str, info: dict) -> None:
    """Run the real storage path for one (provider, series) load, mocking the API."""
    with patch("metatv.core.provider_loader.get_provider", return_value=_FakePlugin(info)):
        thread = SeriesLoadThread(provider=provider, series_id=series_id,
                                  series_name="South Park", db=db)
        asyncio.run(thread.load_series())


def test_two_sources_same_source_id_each_keep_their_own_seasons(tmp_path, qapp):
    """The regression: loading the same series_id from two providers must give EACH
    provider its own full season set — not 0 for whichever loads second."""
    db = Database(f"sqlite:///{tmp_path / 'collide.db'}")
    db.create_tables()
    try:
        _load(db, _provider("provA"), "3823", _series_info())
        _load(db, _provider("provB"), "3823", _series_info())

        session = db.get_session()
        try:
            repos = RepositoryFactory(session)
            a = repos.seasons.get_by_series(series_id="3823", provider_id="provA")
            b = repos.seasons.get_by_series(series_id="3823", provider_id="provB")

            # Both sources see their own two synthetic seasons (B was 0 before the fix).
            assert sorted(s.season_number for s in a) == [1, 2]
            assert sorted(s.season_number for s in b) == [1, 2]
            # Keys are provider-scoped and disjoint.
            assert all(s.id.startswith("provA_") for s in a)
            assert all(s.id.startswith("provB_") for s in b)
            # Episodes are linked under each provider's own season rows.
            a_s1 = next(s for s in a if s.season_number == 1)
            assert len(repos.episodes.get_by_season(season_id=a_s1.id)) == 2
            b_s1 = next(s for s in b if s.season_number == 1)
            assert len(repos.episodes.get_by_season(season_id=b_s1.id)) == 2
        finally:
            session.close()
    finally:
        db.close()


def test_legacy_nonscoped_rows_are_healed_on_reload(tmp_path, qapp):
    """A pre-fix non-scoped season row owned by this provider must be healed away on
    reload (no duplicate season) and its episode re-linked to the scoped season id."""
    db = Database(f"sqlite:///{tmp_path / 'legacy.db'}")
    db.create_tables()
    try:
        # Simulate a pre-fix DB: a non-scoped "3823_s1" season + an episode pointing at it.
        session = db.get_session()
        try:
            session.add(SeasonDB(id="3823_s1", series_id="3823", provider_id="provA",
                                 season_number=1, name="Season 1", episode_count=2,
                                 series_name="South Park"))
            session.add(EpisodeDB(id="provA_101", season_id="3823_s1", series_id="3823",
                                  provider_id="provA", episode_id="101", episode_num=1,
                                  season_num=1, title="old-title", stream_url="x",
                                  series_name="South Park"))
            session.commit()
        finally:
            session.close()

        _load(db, _provider("provA"), "3823", _series_info())

        session = db.get_session()
        try:
            repos = RepositoryFactory(session)
            seasons = repos.seasons.get_by_series(series_id="3823", provider_id="provA")
            # Exactly one season 1 (legacy healed) + season 2 — no duplicate, scoped ids only.
            assert sorted(s.season_number for s in seasons) == [1, 2]
            assert all(s.id.startswith("provA_") for s in seasons)
            # The pre-existing episode followed the season to the scoped id.
            ep = session.query(EpisodeDB).filter_by(id="provA_101").first()
            assert ep.season_id == "provA_3823_s1"
            # And the old non-scoped season row is gone.
            assert session.query(SeasonDB).filter_by(id="3823_s1").first() is None
        finally:
            session.close()
    finally:
        db.close()
