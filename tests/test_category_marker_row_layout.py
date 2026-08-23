"""Behavioral tests for the category-marker cleanup + Comfy/Comfy+ row layout
reshuffle (wave7/category-marker-and-row-layout).

Owner report: Comfy rows render the provider's raw category, which carries a
leading pipe marker duplicating info already shown elsewhere (e.g.
"|EN| ANIME", "|AR-SUB| AMAZON PRIME") and crowds the title.

Coverage:
1. ``parse_category_marker`` — the pure parser (channel_name_utils.py):
   plain-language marker, compound sub/dub marker, no-marker passthrough,
   an unrecognized compound suffix left intact.
2. Ingestion routing (``update_detected_prefixes``, real Database on
   tmp_path) — a prefix-less channel adopts the plain marker as its
   language; a channel with its own (disagreeing) prefix keeps it and gets
   a secondary "other language" value instead of losing the marker; a
   channel whose own prefix MATCHES the marker gets no redundant secondary
   value; a compound "-SUB" marker never becomes a language — it feeds the
   existing detected_audio sub/dub facet AND its own chip-ready display
   field, never the other way around.
3. ``CategoryMarkerBackfillTask`` — version gate, populates pre-existing
   rows, and the crash-retry contract (a run() that raises must NOT bump
   the version), modeled on test_detected_genre_backfill.py.
4. V3 row layout (``channel_list_delegate.py`` + ``channel_row_layout.py``,
   offscreen Qt): the cleaned collection reaches the META LINE rather than a
   line-2 chip, ordered after the genres; the language family and quality are
   the row's only boxed cells and sit right-aligned in the rail; and the
   marker-derived fields (secondary language, sub/dub) still paint when a row
   carries all of them at once.

   The pre-V3 shape this section used to assert — quality hugging the title,
   the year as an outline chip in a right-hand group, a separate line-2 badge
   row — is gone by design, not by accident. See the V3 row's own gate,
   ``tests/test_v3_channel_row.py``, for the rules that replaced it.
"""

from __future__ import annotations

import threading
import uuid
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QFont

from metatv.core.channel_name_utils import (
    CategoryMarker,
    collection_display,
    parse_category_marker,
    quality_display,
)
from metatv.core.repositories.dtos import ChannelListDTO
from metatv.gui.channel_list_delegate import (
    DENSITY_COMFY,
    DENSITY_COMPACT,
    ChannelRowDelegate,
    _CELL_GAP,
)
from metatv.gui.channel_list_model import ChannelListModel


# ---------------------------------------------------------------------------
# 1. parse_category_marker — pure parser
# ---------------------------------------------------------------------------

class TestParseCategoryMarker:

    def test_plain_language_marker(self):
        clean, marker = parse_category_marker("|EN| ANIME")
        assert clean == "ANIME"
        assert marker == CategoryMarker(code="EN", kind="language")

    def test_compound_subdub_marker(self):
        clean, marker = parse_category_marker("|AR-SUB| AMAZON PRIME")
        assert clean == "AMAZON PRIME"
        assert marker == CategoryMarker(code="AR", kind="sub")

    def test_no_marker_unchanged(self):
        clean, marker = parse_category_marker("AMAZON PRIME")
        assert clean == "AMAZON PRIME"
        assert marker is None

    def test_marker_with_hyphenated_rest_preserved(self):
        # The hyphen inside "1990-2023" must not be mistaken for a compound
        # suffix separator — only the bracket content right after the code
        # (before the closing pipe) is examined.
        clean, marker = parse_category_marker("|DE| FILME 1990-2023")
        assert clean == "FILME 1990-2023"
        assert marker == CategoryMarker(code="DE", kind="language")

    def test_unrecognized_compound_suffix_left_intact(self):
        # "FOO" is not SUB/DUB — don't guess, leave the whole string alone.
        clean, marker = parse_category_marker("|EN-FOO| Something")
        assert marker is None
        assert clean == "|EN-FOO| Something"

    def test_empty_category(self):
        assert parse_category_marker("") == ("", None)
        assert parse_category_marker(None) == ("", None)


# ---------------------------------------------------------------------------
# Shared DB fixtures/helpers (real file-backed Database — CLAUDE.md tests rule)
# ---------------------------------------------------------------------------

@pytest.fixture()
def file_db(tmp_path):
    from metatv.core.database import Database

    db = Database(f"sqlite:///{tmp_path / 'category_marker.db'}")
    db.create_tables()
    yield db
    db.close()


@pytest.fixture()
def cfg(tmp_path):
    from metatv.core.config import Config

    return Config(config_dir=tmp_path / "cfg")


def _add_provider(db) -> None:
    from metatv.core.database import ProviderDB

    session = db.get_session()
    try:
        session.add(ProviderDB(
            id="p1", name="P", type="xtream", url="http://x.example.com", is_active=True,
        ))
        session.commit()
    finally:
        session.close()


def _add_channel(db, *, name: str, category: str | None,
                  media_type: str = "movie") -> str:
    """Insert a bare (pre-ingestion) ChannelDB row and return its id."""
    from metatv.core.database import ChannelDB

    channel_id = str(uuid.uuid4())
    session = db.get_session()
    try:
        session.add(ChannelDB(
            id=channel_id, source_id=channel_id, provider_id="p1",
            name=name, media_type=media_type, category=category,
        ))
        session.commit()
    finally:
        session.close()
    return channel_id


def _run_ingestion(db) -> None:
    from metatv.core.repositories import RepositoryFactory

    with db.session_scope() as session:
        RepositoryFactory(session).channels.update_detected_prefixes(provider_id=None)


def _get(db, channel_id: str):
    from metatv.core.database import ChannelDB

    session = db.get_session()
    try:
        return session.query(ChannelDB).filter(ChannelDB.id == channel_id).one()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 2. Ingestion routing
# ---------------------------------------------------------------------------

class TestIngestionRoutesCategoryMarker:

    def test_prefixless_channel_adopts_plain_marker_as_language(self, file_db):
        _add_provider(file_db)
        cid = _add_channel(file_db, name="Some Anime Show", category="|EN| ANIME")
        _run_ingestion(file_db)

        ch = _get(file_db, cid)
        assert ch.detected_prefix == "EN"
        assert ch.detected_collection == "ANIME"
        assert ch.detected_collection_language is None
        assert ch.detected_collection_subdub is None

    def test_disagreeing_prefix_kept_marker_becomes_secondary(self, file_db):
        _add_provider(file_db)
        cid = _add_channel(file_db, name="DE - Some Anime Show", category="|EN| ANIME")
        _run_ingestion(file_db)

        ch = _get(file_db, cid)
        assert ch.detected_prefix == "DE"           # own prefix wins
        assert ch.detected_collection == "ANIME"
        assert ch.detected_collection_language == "EN"   # kept, not dropped

    def test_agreeing_prefix_no_redundant_secondary(self, file_db):
        _add_provider(file_db)
        cid = _add_channel(file_db, name="EN - Some Anime Show", category="|EN| ANIME")
        _run_ingestion(file_db)

        ch = _get(file_db, cid)
        assert ch.detected_prefix == "EN"
        assert ch.detected_collection_language is None  # no duplicate chip

    def test_subdub_marker_never_becomes_language(self, file_db):
        _add_provider(file_db)
        cid = _add_channel(
            file_db, name="Amazon Prime Show", category="|AR-SUB| AMAZON PRIME"
        )
        _run_ingestion(file_db)

        ch = _get(file_db, cid)
        assert ch.detected_prefix is None
        assert ch.detected_collection == "AMAZON PRIME"
        assert ch.detected_collection_subdub == "AR-SUB"
        assert ch.detected_collection_language is None

    def test_subdub_marker_feeds_existing_audio_facet(self, file_db):
        _add_provider(file_db)
        cid = _add_channel(
            file_db, name="Amazon Prime Show", category="|AR-SUB| AMAZON PRIME"
        )
        _run_ingestion(file_db)

        ch = _get(file_db, cid)
        assert ch.detected_audio is not None
        assert ch.detected_audio["sub"] == ["Arabic"]
        assert ch.detected_audio["dub"] == []

    def test_no_marker_category_untouched_and_collection_set(self, file_db):
        _add_provider(file_db)
        cid = _add_channel(file_db, name="Some Show", category="AMAZON PRIME")
        _run_ingestion(file_db)

        ch = _get(file_db, cid)
        assert ch.detected_collection == "AMAZON PRIME"
        assert ch.detected_collection_language is None
        assert ch.detected_collection_subdub is None

    def test_no_category_leaves_fields_null(self, file_db):
        _add_provider(file_db)
        cid = _add_channel(file_db, name="Some Show", category=None)
        _run_ingestion(file_db)

        ch = _get(file_db, cid)
        assert ch.detected_collection is None
        assert ch.detected_collection_language is None
        assert ch.detected_collection_subdub is None


# ---------------------------------------------------------------------------
# 3. CategoryMarkerBackfillTask
# ---------------------------------------------------------------------------

class TestCategoryMarkerBackfillTask:

    def test_needs_run_true_when_version_behind(self, file_db, cfg):
        from metatv.core.migrations.category_marker_backfill import (
            CURRENT_VERSION, CategoryMarkerBackfillTask,
        )

        task = CategoryMarkerBackfillTask(file_db)
        assert cfg.category_marker_backfill_version == 0
        assert task.needs_run(cfg) is True
        cfg.category_marker_backfill_version = CURRENT_VERSION
        assert task.needs_run(cfg) is False

    def test_run_populates_pre_existing_rows(self, file_db, cfg):
        from metatv.core.migrations.category_marker_backfill import CategoryMarkerBackfillTask

        _add_provider(file_db)
        cid = _add_channel(file_db, name="Some Anime Show", category="|EN| ANIME")

        ch = _get(file_db, cid)
        assert ch.detected_collection is None, "pre-condition: not yet backfilled"

        task = CategoryMarkerBackfillTask(file_db)
        progress: list[tuple[int, int]] = []
        task.run(lambda d, t: progress.append((d, t)), lambda: False)

        ch = _get(file_db, cid)
        assert ch.detected_collection == "ANIME"
        assert ch.detected_prefix == "EN"

    def test_on_completed_bumps_version(self, file_db, cfg):
        from metatv.core.migrations.category_marker_backfill import (
            CURRENT_VERSION, CategoryMarkerBackfillTask,
        )

        task = CategoryMarkerBackfillTask(file_db)
        task.on_completed(cfg)
        assert cfg.category_marker_backfill_version == CURRENT_VERSION

    def test_crashed_run_does_not_bump_version(self, file_db, cfg, monkeypatch):
        """A run() that raises must leave category_marker_backfill_version
        unbumped so the task retries next launch — the real MigrationManager
        wiring guarantees this (#364)."""
        from metatv.core.migration_manager import MigrationManager
        from metatv.core.migrations.category_marker_backfill import CategoryMarkerBackfillTask

        task = CategoryMarkerBackfillTask(file_db)

        def _boom(progress_cb, is_cancelled, config=None):
            raise RuntimeError("database is locked")

        monkeypatch.setattr(task, "run", _boom)

        mgr = MigrationManager.__new__(MigrationManager)
        mgr.config = cfg
        mgr._cancel_event = threading.Event()
        finished: list[str] = []
        mgr._task_finished = MagicMock(emit=lambda tid: finished.append(tid))
        mgr._task_started = MagicMock(emit=lambda *a: None)
        mgr._task_progress = MagicMock(emit=lambda *a: None)
        mgr._all_finished = MagicMock(emit=lambda *a: None)

        mgr._run_all([task])

        assert cfg.category_marker_backfill_version == 0, (
            "a crashed run() must NOT bump the version — it must retry next launch"
        )
        assert finished == ["category_marker_backfill"]

    def test_successful_run_bumps_version_after_crash_retry(self, file_db, cfg):
        """A real successful run (simulating a retry after a prior crash)
        completes normally and bumps the version."""
        from metatv.core.migration_manager import MigrationManager
        from metatv.core.migrations.category_marker_backfill import (
            CURRENT_VERSION, CategoryMarkerBackfillTask,
        )

        _add_provider(file_db)
        _add_channel(file_db, name="Some Show", category="|FR| FILMS")

        task = CategoryMarkerBackfillTask(file_db)
        assert cfg.category_marker_backfill_version == 0

        mgr = MigrationManager.__new__(MigrationManager)
        mgr.config = cfg
        mgr._cancel_event = threading.Event()
        mgr._task_finished = MagicMock(emit=lambda tid: None)
        mgr._task_started = MagicMock(emit=lambda *a: None)
        mgr._task_progress = MagicMock(emit=lambda *a: None)
        mgr._all_finished = MagicMock(emit=lambda *a: None)

        mgr._run_all([task])

        assert cfg.category_marker_backfill_version == CURRENT_VERSION


# ---------------------------------------------------------------------------
# 4. Comfy row layout (offscreen Qt — QT_QPA_PLATFORM=offscreen set globally
#    in tests/conftest.py)
# ---------------------------------------------------------------------------

@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _dto(**overrides) -> ChannelListDTO:
    base = dict(
        id=str(uuid.uuid4()),
        name="Channel",
        media_type="movie",
        provider_id="p1",
        is_favorite=False,
        category=None,
        quality=None,
        detected_prefix="DE",             # channel's own (honest) language
        detected_region="US",             # region chip
        detected_quality="4K",
        detected_year="2024",
        detected_title="My Great Show",
        user_rating=0,
        detected_collection="4K SERIES",
        detected_collection_language="FR",   # category's disagreeing language
        detected_collection_subdub="AR-SUB",
    )
    base.update(overrides)
    return ChannelListDTO(**base)


def _model(dtos) -> ChannelListModel:
    model = ChannelListModel()
    model.set_channels(
        dtos,
        provider_icon_map={},
        show_provider_icon=False,
        has_more=False,
        query_params={},
        favorite_icon="",
        unfavorite_icon="",
        get_media_type_icon=lambda mt: "",
    )
    return model


class TestV3MetaLine:
    """Where the category-marker fields land in the V3 row.

    Asserted on painted geometry via the shared harness in ``tests/conftest.py``
    — the real ``paint()`` over a real model index, never a density-specific
    private painter.
    """

    ROW = QRect(0, 0, 900, 68)

    def _painted(self, **roles):
        from tests.conftest import paint_channel_row, row_model

        delegate = ChannelRowDelegate()
        delegate.set_density(DENSITY_COMFY)
        delegate.set_thumbnails_enabled(True)
        model = row_model(**roles)
        return delegate, paint_channel_row(delegate, model.index(0), rect=self.ROW)

    def test_cleaned_collection_paints_on_the_meta_line(self, qapp):
        """The whole point of the marker cleanup: the row shows
        ``Korean Drama``, never the provider's raw ``KR | KOREAN DRAMA``."""
        _delegate, painted = self._painted(
            COLLECTION_ROLE="KOREAN DRAMA", CATEGORY_ROLE="KR | KOREAN DRAMA"
        )
        labels = [c.text for _, c in painted.cells]
        assert collection_display("KOREAN DRAMA", None) in labels
        assert "KR | KOREAN DRAMA" not in labels

    def test_collection_follows_the_genres_on_the_meta_line(self, qapp):
        """Order comes from ``ROW_META_ORDER``, and the collection is the last
        taxonomy fact — the one a reader falls back on when the genres did not
        answer the question."""
        _delegate, painted = self._painted(
            GENRES_ROLE=("Drama", "Thriller"), COLLECTION_ROLE="KOREAN DRAMA",
            CATEGORY_ROLE="KR | KOREAN DRAMA",
        )
        genre = painted.rect_of("Drama / Thriller")
        collection = painted.rect_of(collection_display("KOREAN DRAMA", None))
        assert collection.left() > genre.right(), (
            "the collection must read after the genres, not before them"
        )
        assert collection.top() == genre.top(), "both belong to the same line"

    def test_language_family_and_quality_are_the_rows_only_boxed_cells(self, qapp):
        """Tier 1 is the language family; tier 3 is quality. Everything else in
        the row is bare tinted text, which is what stops the row from reading as
        a wall of badges."""
        _delegate, painted = self._painted(
            PRIMARY_LANGUAGE_ROLE="EN", SECONDARY_LANGUAGE_ROLE="AR",
            SUBTITLE_MARKER_ROLE="AR-SUB", QUALITY_TOKEN_ROLE="4K",
            YEAR_ROLE="2024", LANGUAGE_ROLE="US", COLLECTION_ROLE="ANIME",
            CATEGORY_ROLE="ANIME",
        )
        boxed = {c.text for _, c in painted.cells if c.is_chip}
        assert boxed == {"EN", "AR", "AR-SUB", quality_display("4K")}, (
            f"unexpected boxed cells: {sorted(boxed)}"
        )

    def test_rail_is_the_language_family_right_aligned(self, qapp):
        """The channel's OWN language is flush right (owner spec, #298) and the
        optional secondary/sub-dub markers extend LEFTWARD from it — so the
        column a reader tracks never moves when a marker is absent.

        Quality is deliberately NOT in this group: it is optional, and an
        optional member of a right-aligned group shifts every member left of it.
        """
        _delegate, painted = self._painted(
            PRIMARY_LANGUAGE_ROLE="EN", SECONDARY_LANGUAGE_ROLE="AR",
            SUBTITLE_MARKER_ROLE="AR-SUB", QUALITY_TOKEN_ROLE="4K",
        )
        from metatv.gui import channel_row_layout as _layout

        box = _layout.row_layout(self.ROW, has_art=True, art_square=False, rail_w=0)
        rail = sorted((rect.left(), c.text) for rect, c in painted.cells
                      if c.is_chip and rect.left() > self.ROW.width() // 2)
        assert [text for _, text in rail] == ["AR-SUB", "AR", "EN"]
        en = painted.rect_of("EN")
        assert en.right() <= box.action.left(), "the rail runs under the action gutter"
        assert en.right() > self.ROW.width() // 2

        # …and the same row without the optional markers puts EN in the SAME column.
        _d2, bare = self._painted(
            PRIMARY_LANGUAGE_ROLE="EN", SECONDARY_LANGUAGE_ROLE="",
            SUBTITLE_MARKER_ROLE="", QUALITY_TOKEN_ROLE="",
        )
        assert bare.rect_of("EN") == en

    def test_absent_marker_fields_paint_nothing(self, qapp):
        """A row with no secondary language and no sub/dub marker paints
        neither — no empty boxes, no reserved gaps."""
        _delegate, painted = self._painted(
            SECONDARY_LANGUAGE_ROLE="", SUBTITLE_MARKER_ROLE="",
            PRIMARY_LANGUAGE_ROLE="EN", QUALITY_TOKEN_ROLE="",
        )
        boxed = {c.text for _, c in painted.cells if c.is_chip}
        assert boxed == {"EN"}


class TestDensityDefault:

    def test_density_still_defaults_to_comfy(self, qapp):
        assert ChannelRowDelegate().density == DENSITY_COMFY
