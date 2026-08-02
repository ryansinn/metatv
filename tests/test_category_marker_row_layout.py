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
4. Comfy row layout (``channel_list_delegate.py``, offscreen Qt):
   the quality chip sits on line 1 immediately after the title (no
   stretch); line 1's right group is flush right in the order
   year → region → subtitle marker → secondary language → primary
   language, for a row carrying all five at once; line 2 no longer
   carries quality/region/language and instead shows the collection chip
   flush right; compact density's right group is unaffected.
"""

from __future__ import annotations

import threading
import uuid
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QFont

from metatv.core.channel_name_utils import CategoryMarker, parse_category_marker, quality_display
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


class TestComfyLine1Layout:

    def test_quality_chip_hugs_title_no_stretch(self, qapp):
        model = _model([_dto()])
        idx = model.index(0)
        delegate = ChannelRowDelegate()

        drawn_text_calls = []
        cell_calls = []

        def _capture_draw_text(painter, rect, text, color, font):
            drawn_text_calls.append((rect, text))

        def _capture_paint_cell(painter, rect, cell, font):
            cell_calls.append((rect, cell))

        with patch.object(delegate, "_draw_text", side_effect=_capture_draw_text), \
             patch.object(delegate, "_paint_cell", side_effect=_capture_paint_cell):
            line = QRect(0, 0, 600, 20)
            delegate._paint_title_year_line(MagicMock(), line, idx, "#fff", QFont())

        title_rect = next(r for r, t in drawn_text_calls if t == "My Great Show")
        quality_rect = next(r for r, c in cell_calls if c.text == quality_display("4K"))

        # Immediately follows the title TEXT — no stretch between them.
        #
        # This originally asserted ``title_rect.width()`` — the title BOX, which is
        # stretched to every pixel up to the right group — so it locked in the very
        # regression its name describes (chip painted flush against the right group,
        # owner UX report vs 0.21.0). Measure the drawn text instead.
        from PyQt6.QtGui import QFontMetrics
        fm = QFontMetrics(QFont())
        title_text_end = title_rect.left() + min(
            fm.horizontalAdvance("My Great Show"), title_rect.width()
        )
        assert quality_rect.left() == title_text_end + _CELL_GAP

    def test_right_group_full_ordering_flush_right(self, qapp):
        """A row carrying all five right-group values at once: order is
        year -> region -> subtitle marker -> secondary language -> primary
        language, flush right."""
        model = _model([_dto()])
        idx = model.index(0)
        delegate = ChannelRowDelegate()

        cell_calls = []

        def _capture_paint_cell(painter, rect, cell, font):
            cell_calls.append((rect, cell))

        with patch.object(delegate, "_draw_text"), \
             patch.object(delegate, "_paint_cell", side_effect=_capture_paint_cell):
            line = QRect(0, 0, 600, 20)
            delegate._paint_title_year_line(MagicMock(), line, idx, "#fff", QFont())

        rects_by_text = {c.text: r for r, c in cell_calls}
        expected_order = ["2024", "US", "AR-SUB", "FR", "DE"]
        for text in expected_order:
            assert text in rects_by_text, f"expected chip {text!r} missing from line 1"

        lefts = [rects_by_text[t].left() for t in expected_order]
        assert lefts == sorted(lefts), "right-group cells must be in spec order left-to-right"

        # The primary (own/honest) language sits furthest right — flush with
        # the line's own right edge.
        assert rects_by_text["DE"].right() == line.right()

    def test_line1_omits_absent_right_group_cells(self, qapp):
        """A row with no secondary language / subtitle marker doesn't leave
        gaps — those chips are simply absent, not blank."""
        model = _model([_dto(detected_collection_language=None, detected_collection_subdub=None)])
        idx = model.index(0)
        delegate = ChannelRowDelegate()

        cell_calls = []

        def _capture_paint_cell(painter, rect, cell, font):
            cell_calls.append((rect, cell))

        with patch.object(delegate, "_draw_text"), \
             patch.object(delegate, "_paint_cell", side_effect=_capture_paint_cell):
            line = QRect(0, 0, 600, 20)
            delegate._paint_title_year_line(MagicMock(), line, idx, "#fff", QFont())

        texts = {c.text for _, c in cell_calls}
        assert "AR-SUB" not in texts
        assert "FR" not in texts
        assert {"2024", "US", "DE"} <= texts


class TestComfyLine2Layout:

    def test_badge_line_drops_quality_and_region_collection_flush_right(self, qapp):
        model = _model([_dto(user_rating=1)])
        idx = model.index(0)
        delegate = ChannelRowDelegate()

        cell_calls = []

        def _capture_paint_cell(painter, rect, cell, font):
            cell_calls.append((rect, cell))

        with patch.object(delegate, "_paint_cell", side_effect=_capture_paint_cell):
            line = QRect(0, 0, 600, 20)
            delegate._paint_badge_line(MagicMock(), line, idx, QFont())

        texts = [c.text for _, c in cell_calls]
        assert quality_display("4K") not in texts   # moved to line 1
        assert "US" not in texts                    # region moved to line 1
        assert "DE" not in texts                     # primary language moved to line 1

        collection_rect = next(r for r, c in cell_calls if c.text == "4K SERIES")
        assert collection_rect.right() == line.right()  # flush right


class TestCompactUnaffected:

    def test_compact_right_group_unchanged(self, qapp):
        """Compact's right group stays [year, region(LANGUAGE_ROLE), rating] —
        the comfy line1/line2 reshuffle must not leak into compact."""
        model = _model([_dto(user_rating=1)])
        idx = model.index(0)
        delegate = ChannelRowDelegate()
        delegate.set_density(DENSITY_COMPACT)

        cell_calls = []

        def _capture_paint_cell(painter, rect, cell, font):
            cell_calls.append((rect, cell))

        with patch.object(delegate, "_draw_text"), \
             patch.object(delegate, "_paint_cell", side_effect=_capture_paint_cell):
            rect = QRect(0, 0, 600, 20)
            delegate._paint_compact(MagicMock(), rect, idx, "#fff", QFont())

        texts = [c.text for _, c in cell_calls]
        # Region + year still present; the new secondary/subtitle marker
        # chips must NOT appear in compact.
        assert "US" in texts
        assert "2024" in texts
        assert "AR-SUB" not in texts
        assert "FR" not in texts

    def test_density_still_defaults_to_comfy(self, qapp):
        delegate = ChannelRowDelegate()
        assert delegate.density == DENSITY_COMFY


# ---------------------------------------------------------------------------
# Quality-chip POSITION (owner UX report against 0.21.0)
#
# The row grammar says the quality chip hugs the TITLE TEXT. The first
# implementation offset the chip by ``title_box_w`` — the title box is stretched
# to every pixel up to the right-aligned group, so the chip was painted flush
# against that group instead, on the far right of the row.
#
# The cell ORDER was correct throughout, which is why the original suite passed
# green while the rendered row was wrong. These tests assert painted GEOMETRY.
# ---------------------------------------------------------------------------

class TestQualityChipHugsTitle:

    ROW_W = 900  # wide row => large gap between title text and the right group

    def _capture(self, density):
        """Paint one row and return {label: rect} for every painted cell."""
        from PyQt6.QtGui import QFontMetrics

        delegate = ChannelRowDelegate()
        painted: dict[str, QRect] = {}
        delegate._paint_cell = lambda p, rect, cell, font: painted.__setitem__(
            cell.text, QRect(rect)
        )
        drawn: list[tuple[QRect, str]] = []
        delegate._draw_text = lambda p, rect, text, color, font: drawn.append(
            (QRect(rect), text)
        )

        index = MagicMock()
        roles = {
            "TITLE_ROLE": "Fallout",
            "QUALITY_TOKEN_ROLE": "4K",
            "YEAR_ROLE": "2024",
            "LANGUAGE_ROLE": "US",
        }
        import metatv.gui.channel_list_delegate as d

        def data(role):
            for name, value in roles.items():
                if role == getattr(d, name, object()):
                    return value
            return None

        index.data.side_effect = data
        font = QFont()
        rect = QRect(0, 0, self.ROW_W, 40)
        if density == DENSITY_COMPACT:
            delegate._paint_compact(None, rect, index, None, font)
        else:
            delegate._paint_title_year_line(None, rect, index, None, font)
        return painted, drawn, QFontMetrics(font)

    def _assert_hugs(self, density):
        painted, drawn, fm = self._capture(density)
        chip = painted.get(quality_display("4K"))
        assert chip is not None, "quality chip was never painted"

        title_draw = next((r for r, t in drawn if t.startswith("Fallout")), None)
        assert title_draw is not None, "title was never drawn"
        title_text_end = title_draw.left() + fm.horizontalAdvance("Fallout")

        # The chip starts right after the title TEXT, not after the stretched box.
        assert chip.left() <= title_text_end + 2 * _CELL_GAP, (
            f"quality chip drifted right: chip.left()={chip.left()} but the title "
            f"text ends at {title_text_end} (row width {self.ROW_W})"
        )
        # And it is nowhere near the right edge — the regression's signature.
        assert chip.left() < self.ROW_W // 2, (
            f"quality chip parked on the right half ({chip.left()}) — it must hug "
            "the title on the left"
        )

    def test_comfy_quality_chip_hugs_title(self, qapp):
        self._assert_hugs(DENSITY_COMFY)

    def test_compact_quality_chip_hugs_title(self, qapp):
        self._assert_hugs(DENSITY_COMPACT)

    def test_year_stays_plain_text_right_aligned(self, qapp):
        """Year stays unboxed plain text in the right group (owner call, 0.22.0)."""
        from PyQt6.QtGui import QFontMetrics  # noqa: F401

        delegate = ChannelRowDelegate()
        cells: list = []
        delegate._paint_cell = lambda p, rect, cell, font: cells.append((QRect(rect), cell))
        delegate._draw_text = lambda p, rect, text, color, font: None

        index = MagicMock()
        import metatv.gui.channel_list_delegate as d
        roles = {"TITLE_ROLE": "Fallout", "QUALITY_TOKEN_ROLE": "4K",
                 "YEAR_ROLE": "2024", "LANGUAGE_ROLE": "US"}

        def data(role):
            for name, value in roles.items():
                if role == getattr(d, name, object()):
                    return value
            return None

        index.data.side_effect = data
        delegate._paint_title_year_line(
            None, QRect(0, 0, self.ROW_W, 40), index, None, QFont()
        )
        year = next(((r, c) for r, c in cells if c.text == "2024"), None)
        assert year is not None, "year was never painted"
        assert year[1].is_chip is False, "year must stay plain text, not a chip"
        assert year[0].left() > self.ROW_W // 2, "year must be right-aligned"
