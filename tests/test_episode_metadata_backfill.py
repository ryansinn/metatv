"""Behavioral tests for per-episode plot/air-date/rating/still-image (Wave 4 — #247).

``EpisodeDB.raw_data`` has always stored a provider's full per-episode blob
verbatim, but ingestion only ever lifted title/duration/container_extension/
cover_url into real columns — the episode plot, air date, rating, and still
image were sitting unused in already-stored data. This adds
``EpisodeDB.plot``/``air_date``/``rating``/``still_url``, lifts them at
ingestion via the shared ``episode_metadata_extract`` chokepoint, backfills
pre-existing rows via ``EpisodeMetadataBackfillTask``, carries them on
``EpisodeDTO``, and renders them in ``DetailsPaneWidget.show_episode``.

Coverage:
1. Ingestion (``SeriesLoadThread.load_series``, the real storage path, no
   network) lifts all four fields from a realistic Xtream episode blob —
   including the alternate provider key spellings (``plot`` vs ``overview``,
   ``releaseDate`` vs ``air_date``, ``movie_image`` vs ``still_path``).
2. Junk rating values (``""``, ``"N/A"``, ``None``) coerce to ``None`` without
   raising, at both the extractor level and through real ingestion.
3. ``EpisodeMetadataBackfillTask`` populates pre-existing rows whose
   ``raw_data`` carries the fields and leaves rows without them alone.
4. Crash-retry: a task whose ``run()`` raises must not bump the version
   (modeled on ``test_migration_center.py::test_crashed_task_does_not_bump_version``,
   same pattern as ``test_detected_genre_backfill.py``).
5. ``EpisodeDTO`` carries plot/air_date/rating/still_url across the session
   boundary (``get_episodes_dto_by_season`` reads the stored columns, not
   ``raw_data``, at render time).
6. ``DetailsPaneWidget.show_episode`` renders the EPISODE's own plot rather
   than falling back to the series plot when both exist, and shows/hides the
   rating + air-date chips correctly.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import MagicMock, patch

import pytest

from metatv.core.database import Database, EpisodeDB
from metatv.core.models import Provider
from metatv.core.provider_loader import SeriesLoadThread
from metatv.core.repositories import RepositoryFactory


# ---------------------------------------------------------------------------
# Fixtures / shared helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def file_db(tmp_path):
    """File-backed SQLite Database (not :memory: — see CLAUDE.md tests rule)."""
    db = Database(f"sqlite:///{tmp_path / 'episode_metadata.db'}")
    db.create_tables()
    yield db
    db.close()


@pytest.fixture()
def cfg(tmp_path):
    """Isolated Config instance — never touches the real ~/.config/metatv."""
    from metatv.core.config import Config

    return Config(config_dir=tmp_path / "cfg")


class _FakePlugin:
    """Stand-in provider plugin: returns canned series info, no network."""

    def __init__(self, info: dict) -> None:
        self._info = info

    async def fetch_series_info(self, provider, series_id):  # noqa: D401 - test stub
        return self._info


def _provider(pid: str = "p1") -> Provider:
    return Provider(id=pid, name=f"prov-{pid}", type="xtream",
                     url=f"http://host-{pid}", username="u", password="p")


def _load(db: Database, provider: Provider, series_id: str, info: dict) -> None:
    """Run the REAL storage path (SeriesLoadThread.load_series) for one load,
    mocking only the network call."""
    with patch("metatv.core.provider_loader.get_provider", return_value=_FakePlugin(info)):
        thread = SeriesLoadThread(provider=provider, series_id=series_id,
                                   series_name="Star Trek", db=db)
        asyncio.run(thread.load_series())


def _get_episode(db: Database, episode_db_id: str) -> EpisodeDB:
    session = db.get_session()
    try:
        return session.query(EpisodeDB).filter_by(id=episode_db_id).first()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 1 + 2. Ingestion lifts plot/air_date/rating/still_url — real + alt spellings,
#        junk rating coerces to None without raising.
# ---------------------------------------------------------------------------

class TestIngestionLiftsEpisodeFields:

    def test_realistic_xtream_blob_lifts_all_four_fields(self, file_db, qapp):
        """A realistic Xtream episode blob (docs/xtream_api_schema.md shape) —
        overview under 'info', 'air_date', numeric 'rating', 'still_path' —
        lifts cleanly into the four new columns at ingestion."""
        info = {
            "info": {"name": "Star Trek"},
            "seasons": [],
            "episodes": {
                "3": [{
                    "id": "1004425",
                    "episode_num": 1,
                    "season": 3,
                    "title": "EN - Star Trek (1966) - S03E01",
                    "container_extension": "mkv",
                    "info": {
                        "overview": "Kirk and crew encounter a mysterious alien probe.",
                        "air_date": "1968-09-20",
                        "crew": "Gene L. Coon, Marc Daniels",
                        "rating": 5.8,
                        "id": 253,
                        "movie_image": "https://image.tmdb.org/t/p/w185/fallback.jpg",
                        "still_path": "https://image.tmdb.org/t/p/w185/still.jpg",
                        "duration": "00:56:08",
                    },
                }],
            },
        }
        _load(file_db, _provider("p1"), "3823", info)

        ep = _get_episode(file_db, "p1_1004425")
        assert ep is not None
        assert ep.plot == "Kirk and crew encounter a mysterious alien probe."
        assert ep.air_date == "1968-09-20"
        assert ep.rating == pytest.approx(5.8)
        # still_path takes priority over movie_image when both are present.
        assert ep.still_url == "https://image.tmdb.org/t/p/w185/still.jpg"

    def test_alternate_key_spellings_are_recognized(self, file_db, qapp):
        """A provider using 'plot' (not 'overview'), 'releaseDate' (not
        'air_date'), and only 'movie_image' (no still_path) still lifts
        correctly — the point of the shared extractor's fallback chain."""
        info = {
            "info": {"name": "Alt Show"},
            "seasons": [],
            "episodes": {
                "1": [{
                    "id": "555",
                    "episode_num": 1,
                    "season": 1,
                    "title": "Alt Show S01E01",
                    "container_extension": "mp4",
                    "info": {
                        "plot": "Alternate-spelling plot text.",
                        "releaseDate": "2020-01-15",
                        "rating": "7.2",  # numeric-string rating must also coerce
                        "movie_image": "https://example.com/still.jpg",
                    },
                }],
            },
        }
        _load(file_db, _provider("p2"), "9001", info)

        ep = _get_episode(file_db, "p2_555")
        assert ep is not None
        assert ep.plot == "Alternate-spelling plot text."
        assert ep.air_date == "2020-01-15"
        assert ep.rating == pytest.approx(7.2)
        assert ep.still_url == "https://example.com/still.jpg"

    @pytest.mark.parametrize("junk_rating", ["", "N/A", None])
    def test_junk_rating_coerces_to_none_without_raising(self, file_db, qapp, junk_rating):
        """A junk/missing rating value must never raise during ingestion — it
        simply coerces to NULL on the stored column."""
        info = {
            "info": {"name": "Junk Rating Show"},
            "seasons": [],
            "episodes": {
                "1": [{
                    "id": "junk1",
                    "episode_num": 1,
                    "season": 1,
                    "title": "Junk S01E01",
                    "container_extension": "mp4",
                    "info": {"rating": junk_rating, "overview": "Some plot."},
                }],
            },
        }
        # Must not raise.
        _load(file_db, _provider("p3"), "junk-series", info)

        ep = _get_episode(file_db, "p3_junk1")
        assert ep is not None
        assert ep.rating is None
        assert ep.plot == "Some plot."

    def test_episode_with_no_info_leaves_fields_null(self, file_db, qapp):
        """An episode with no per-episode metadata at all gets NULL on all
        four columns — never a guessed/synthesized value."""
        info = {
            "info": {"name": "Bare Show"},
            "seasons": [],
            "episodes": {
                "1": [{
                    "id": "bare1",
                    "episode_num": 1,
                    "season": 1,
                    "title": "Bare S01E01",
                    "container_extension": "mp4",
                    "info": {},
                }],
            },
        }
        _load(file_db, _provider("p4"), "bare-series", info)

        ep = _get_episode(file_db, "p4_bare1")
        assert ep is not None
        assert ep.plot is None
        assert ep.air_date is None
        assert ep.rating is None
        assert ep.still_url is None


# ---------------------------------------------------------------------------
# 2b. Direct unit coverage of coerce_episode_rating (never raises)
# ---------------------------------------------------------------------------

class TestCoerceEpisodeRating:

    @pytest.mark.parametrize("value,expected", [
        ("", None),
        ("N/A", None),
        (None, None),
        ("   ", None),
        (5.8, 5.8),
        ("7.2", 7.2),
        (8, 8.0),
        (True, None),   # bool is an int subclass — must NOT become 1.0
        (float("nan"), None),
        ([1, 2], None),  # unsupported type — never raises
    ])
    def test_coercion_matrix(self, value, expected):
        from metatv.core.episode_metadata_extract import coerce_episode_rating

        result = coerce_episode_rating(value)
        if expected is None:
            assert result is None
        else:
            assert result == pytest.approx(expected)


# ---------------------------------------------------------------------------
# 3. EpisodeMetadataBackfillTask
# ---------------------------------------------------------------------------

def _insert_bare_episode(db: Database, *, ep_id: str, raw_data: dict | None) -> None:
    """Insert a pre-migration-shaped EpisodeDB row: raw_data set, the four new
    columns left at their SQLAlchemy default (NULL) — as if ingested before
    this fix shipped."""
    with db.session_scope() as session:
        session.add(EpisodeDB(
            id=ep_id, season_id="s1", series_id="ser1", provider_id="p1",
            episode_id=ep_id, episode_num=1, season_num=1,
            title="Backfill Target", raw_data=raw_data,
        ))


class TestEpisodeMetadataBackfillTask:

    def test_needs_run_true_when_version_behind(self, file_db, cfg):
        from metatv.core.migrations.episode_metadata_backfill import (
            CURRENT_VERSION, EpisodeMetadataBackfillTask,
        )

        task = EpisodeMetadataBackfillTask(file_db)
        assert cfg.episode_metadata_backfill_version == 0
        assert task.needs_run(cfg) is True
        cfg.episode_metadata_backfill_version = CURRENT_VERSION
        assert task.needs_run(cfg) is False

    def test_run_populates_rows_whose_raw_data_has_the_fields(self, file_db, cfg):
        from metatv.core.migrations.episode_metadata_backfill import EpisodeMetadataBackfillTask

        _insert_bare_episode(file_db, ep_id="ep_full", raw_data={
            "info": {
                "overview": "A backfilled plot.",
                "air_date": "1999-05-01",
                "rating": 9.1,
                "still_path": "https://example.com/backfilled-still.jpg",
            },
        })

        ep = _get_episode(file_db, "ep_full")
        assert ep.plot is None, "pre-condition: not yet backfilled"

        task = EpisodeMetadataBackfillTask(file_db)
        progress: list[tuple[int, int]] = []
        task.run(lambda d, t: progress.append((d, t)), lambda: False)

        ep = _get_episode(file_db, "ep_full")
        assert ep.plot == "A backfilled plot."
        assert ep.air_date == "1999-05-01"
        assert ep.rating == pytest.approx(9.1)
        assert ep.still_url == "https://example.com/backfilled-still.jpg"

    def test_run_leaves_rows_without_the_fields_alone(self, file_db, cfg):
        """A row whose raw_data carries none of the four fields must come out
        of the backfill with all four columns still NULL — never a sentinel
        or a guessed value."""
        from metatv.core.migrations.episode_metadata_backfill import EpisodeMetadataBackfillTask

        _insert_bare_episode(file_db, ep_id="ep_empty", raw_data={
            "id": "999", "title": "No metadata here", "container_extension": "mp4",
        })
        _insert_bare_episode(file_db, ep_id="ep_none_raw", raw_data=None)

        task = EpisodeMetadataBackfillTask(file_db)
        task.run(lambda d, t: None, lambda: False)

        for ep_id in ("ep_empty", "ep_none_raw"):
            ep = _get_episode(file_db, ep_id)
            assert ep.plot is None
            assert ep.air_date is None
            assert ep.rating is None
            assert ep.still_url is None

    def test_on_completed_bumps_version(self, file_db, cfg):
        from metatv.core.migrations.episode_metadata_backfill import (
            CURRENT_VERSION, EpisodeMetadataBackfillTask,
        )

        task = EpisodeMetadataBackfillTask(file_db)
        task.on_completed(cfg)
        assert cfg.episode_metadata_backfill_version == CURRENT_VERSION


# ---------------------------------------------------------------------------
# 4. Crash-retry — modeled on
#    test_migration_center.py::test_crashed_task_does_not_bump_version
# ---------------------------------------------------------------------------

class TestEpisodeMetadataBackfillCrashRetry:

    def test_crashed_run_does_not_bump_version(self, file_db, cfg, monkeypatch):
        """A run() that raises must leave episode_metadata_backfill_version
        unbumped so the task retries on the next launch — the real
        MigrationManager wiring guarantees this (#364): it skips
        on_completed for any task whose run() raised."""
        from metatv.core.migration_manager import MigrationManager
        from metatv.core.migrations.episode_metadata_backfill import EpisodeMetadataBackfillTask

        task = EpisodeMetadataBackfillTask(file_db)

        def _boom(progress_cb, is_cancelled, config=None):
            raise RuntimeError("database is locked")

        monkeypatch.setattr(task, "run", _boom)

        mgr = MigrationManager.__new__(MigrationManager)
        mgr.config = cfg
        import threading
        mgr._cancel_event = threading.Event()
        finished: list[str] = []
        mgr._task_finished = MagicMock(emit=lambda tid: finished.append(tid))
        mgr._task_started = MagicMock(emit=lambda *a: None)
        mgr._task_progress = MagicMock(emit=lambda *a: None)
        mgr._all_finished = MagicMock(emit=lambda *a: None)

        mgr._run_all([task])

        assert cfg.episode_metadata_backfill_version == 0, (
            "a crashed run() must NOT bump the version — it must retry next launch"
        )
        assert finished == ["episode_metadata_backfill"], "widget must still get the finish signal"

    def test_successful_run_bumps_version_after_crash_retry(self, file_db, cfg):
        """After a (simulated) prior crash, a real successful run completes
        normally and bumps the version — proving the task isn't permanently
        broken by the crash path."""
        from metatv.core.migration_manager import MigrationManager
        from metatv.core.migrations.episode_metadata_backfill import (
            CURRENT_VERSION, EpisodeMetadataBackfillTask,
        )

        _insert_bare_episode(file_db, ep_id="ep_retry", raw_data={"info": {"rating": 4.0}})

        task = EpisodeMetadataBackfillTask(file_db)
        assert cfg.episode_metadata_backfill_version == 0

        mgr = MigrationManager.__new__(MigrationManager)
        mgr.config = cfg
        import threading
        mgr._cancel_event = threading.Event()
        mgr._task_finished = MagicMock(emit=lambda tid: None)
        mgr._task_started = MagicMock(emit=lambda *a: None)
        mgr._task_progress = MagicMock(emit=lambda *a: None)
        mgr._all_finished = MagicMock(emit=lambda *a: None)

        mgr._run_all([task])

        assert cfg.episode_metadata_backfill_version == CURRENT_VERSION
        assert _get_episode(file_db, "ep_retry").rating == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# 5. EpisodeDTO carries the new fields across the session boundary
# ---------------------------------------------------------------------------

class TestEpisodeDTOCrossesSessionBoundary:

    def test_dto_carries_plot_air_date_rating_still_url(self, file_db):
        with file_db.session_scope() as session:
            session.add(EpisodeDB(
                id="dto_ep1", season_id="s1", series_id="ser1", provider_id="p1",
                episode_id="dto_ep1", episode_num=1, season_num=1,
                title="DTO Episode",
                plot="A stored plot.",
                air_date="2010-03-14",
                rating=6.5,
                still_url="https://example.com/dto-still.jpg",
            ))

        # Build the DTO inside its own session_scope, then use it AFTER the
        # scope has closed — a DetachedInstanceError here would mean an ORM
        # object leaked across the boundary instead of a frozen DTO.
        with file_db.session_scope(commit=False) as session:
            dto = RepositoryFactory(session).episodes.get_episodes_dto_by_season(
                season_id="s1"
            )[0]

        assert dto.plot == "A stored plot."
        assert dto.air_date == "2010-03-14"
        assert dto.rating == pytest.approx(6.5)
        assert dto.still_url == "https://example.com/dto-still.jpg"


# ---------------------------------------------------------------------------
# 6. DetailsPaneWidget.show_episode renders the EPISODE's own plot/rating/
#    air-date, not the series' fallback.
# ---------------------------------------------------------------------------

def _fake_series_channel():
    ch = MagicMock()
    ch.id = str(uuid.uuid4())
    ch.name = "Test Show"
    ch.media_type = "series"
    ch.is_favorite = False
    ch.is_adult = False
    ch.detected_title = "Test Show"
    ch.detected_year = None
    ch.detected_prefix = None
    ch.detected_quality = None
    ch.detected_region = None
    ch.raw_data = None
    ch.provider_id = None
    ch.watch_completed = False
    ch.watch_progress = 0
    ch.logo_url = None
    return ch


def _episode_dto(*, plot=None, air_date=None, rating=None, still_url=None):
    from metatv.core.repositories.dtos import EpisodeDTO

    return EpisodeDTO(
        id=str(uuid.uuid4()),
        episode_num=1,
        season_num=1,
        title="Pilot",
        series_name="Test Show",
        stream_url="http://stream/ep",
        duration="45:00",
        is_watched=False,
        rating=rating,
        plot=plot,
        air_date=air_date,
        still_url=still_url,
    )


def _make_details_pane(qapp):
    from metatv.gui.details_pane import DetailsPaneWidget
    from metatv.core.config import Config

    cache = MagicMock()
    cache.get_image_sync.return_value = None
    return DetailsPaneWidget(Config(), cache, db=None)


class TestDetailsPaneRendersEpisodeOwnPlot:

    def test_episode_plot_wins_over_series_plot(self, qapp):
        from metatv.metadata_providers.base import MetadataResult

        pane = _make_details_pane(qapp)
        series = _fake_series_channel()
        pane.show_channel(series, metadata=MetadataResult(plot="The series-level summary."))
        assert pane._plot.plot_label.text() == "The series-level summary."

        ep = _episode_dto(plot="This specific episode's own plot.")
        pane.show_episode(ep, series)

        assert pane._plot.plot_label.text() == "This specific episode's own plot.", (
            "show_episode must render the EPISODE's plot, not fall back to the "
            "series-level plot, when the episode DTO carries its own"
        )

    def test_episode_without_plot_keeps_series_plot(self, qapp):
        from metatv.metadata_providers.base import MetadataResult

        pane = _make_details_pane(qapp)
        series = _fake_series_channel()
        pane.show_channel(series, metadata=MetadataResult(plot="The series-level summary."))

        ep = _episode_dto(plot=None)
        pane.show_episode(ep, series)

        assert pane._plot.plot_label.text() == "The series-level summary."

    def test_episode_rating_and_air_date_shown(self, qapp):
        pane = _make_details_pane(qapp)
        series = _fake_series_channel()
        pane.show_channel(series)

        ep = _episode_dto(rating=8.4, air_date="1968-09-20")
        pane.show_episode(ep, series)

        assert pane._episode_rating_lbl.isVisible() or not pane._episode_rating_lbl.isHidden()
        assert "8.4" in pane._episode_rating_lbl.text()
        assert "1968-09-20" in pane._episode_air_date_lbl.text()

    def test_episode_without_rating_hides_rating_chip(self, qapp):
        """A rating of None must hide the chip — never render '0.0 of 10'."""
        pane = _make_details_pane(qapp)
        series = _fake_series_channel()
        pane.show_channel(series)

        ep = _episode_dto(rating=None)
        pane.show_episode(ep, series)

        assert pane._episode_rating_lbl.isHidden()

    def test_reverting_to_series_hides_episode_meta_row(self, qapp):
        pane = _make_details_pane(qapp)
        series = _fake_series_channel()
        pane.show_channel(series)
        ep = _episode_dto(rating=7.0, air_date="2020-01-01")
        pane.show_episode(ep, series)
        assert not pane._episode_meta_row.isHidden()

        pane.show_channel(series)
        assert pane._episode_meta_row.isHidden()
        assert pane._episode_rating_lbl.isHidden()
        assert pane._episode_air_date_lbl.isHidden()
