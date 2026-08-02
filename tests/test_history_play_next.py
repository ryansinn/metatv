"""Wave 5 — "Play Next Episode" in the History sidebar.

Covers the three surfaces this feature touches, each proven behaviorally
(never a shape assertion):

1. ``EpisodeRepository.get_resume_targets_for_series`` — the batched sibling of
   ``get_last_played_codes_for_series``: resolves the smart-ladder resume target
   (``get_resume_dto``) per unique ``(series_id, provider_id)`` key, deduping
   repeated keys rather than querying once per History row.
2. ``build_history_dtos`` — populates ``has_next``/``next_episode_id``/
   ``next_episode_code`` from the batched map; non-series rows and series with
   no resume target never get a target.
3. ``chip_row.build_chip_row``'s ``trailing_button`` slot + ``HistorySection``:
   the ">>" button appears ONLY on ``has_next`` rows, is independently
   clickable (proven via real ``QApplication.widgetAt`` hit-testing, not just
   ``.click()``), emits ``playNextClicked`` with the resolved episode id, and
   rows WITHOUT a trailing button stay pixel-identical (still
   ``WA_TransparentForMouseEvents`` — the existing regression this whole
   feature must not break).

All DB tests use a real file-backed ``Database`` (tmp_path), never
``:memory:``, per CLAUDE.md.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLabel, QListWidget, QListWidgetItem, QPushButton

from metatv.core.database import Database, ChannelDB, EpisodeDB, SeasonDB
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.dtos import HistoryDTO, build_history_dtos
from metatv.gui.chip_row import build_chip_row
from metatv.gui.sidebar.history import HistorySection


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def db(tmp_path: Path):
    """File-backed (not :memory:) Database so every pooled connection shares tables."""
    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.create_tables()
    yield d
    d.close()


def _config():
    return SimpleNamespace(
        live_icon="L", movie_icon="M", series_icon="S", unknown_icon="?",
        filter_adult_mode="all",
    )


def _seed_series(db: Database, name: str = "Breaking Bad", provider_id: str = "p1",
                  source_id: str = "series1", last_played=None) -> str:
    from datetime import datetime
    cid = str(uuid.uuid4())
    with db.session_scope() as session:
        session.add(ChannelDB(
            id=cid, source_id=source_id, provider_id=provider_id,
            name=name, media_type="series",
            detected_title=name, last_played=last_played or datetime.now(),
        ))
    return cid


def _seed_episode(db: Database, *, provider_id: str = "p1", series_source_id: str = "series1",
                   season_num: int = 1, episode_num: int = 1, title: str = "Pilot",
                   last_played=None) -> str:
    season_id = f"{provider_id}_{series_source_id}_s{season_num:02d}"
    ep_id = f"{provider_id}_{series_source_id}_e{season_num}_{episode_num}"
    with db.session_scope() as session:
        if not session.get(SeasonDB, season_id):
            session.add(SeasonDB(
                id=season_id, series_id=series_source_id, provider_id=provider_id,
                season_number=season_num, name=f"Season {season_num}",
            ))
        session.add(EpisodeDB(
            id=ep_id, season_id=season_id, series_id=series_source_id,
            provider_id=provider_id, episode_id=str(episode_num),
            episode_num=episode_num, season_num=season_num,
            title=title, stream_url="http://example.com/ep",
            last_played=last_played,
        ))
    return ep_id


def _first_chip_row(list_widget: QListWidget):
    for i in range(list_widget.count()):
        w = list_widget.itemWidget(list_widget.item(i))
        if w is not None:
            return w
    return None


def _new_history_section(dtos) -> HistorySection:
    """Build a HistorySection without full __init__ (mirrors test_sidebar_chip_rows.py's
    established pattern) and populate it from synthetic DTOs.

    Fine for structural assertions (row contents/layout), but PyQt6 refuses any
    signal connect/emit on an object whose QObject base was never constructed —
    use :func:`_real_history_section` instead for anything touching
    ``playNextClicked``.
    """
    obj = HistorySection.__new__(HistorySection)
    obj.history_list = QListWidget()
    obj.config = _config()
    obj.set_empty = lambda *_: None
    obj._populate_rows(dtos)
    return obj


def _real_history_section(db: Database, dtos) -> HistorySection:
    """A fully __init__'d HistorySection (real Config, real QObject base) so its
    signals (playNextClicked) are usable — mirrors the real
    ``WatchQueueSection(config, db)`` / ``FavoritesSection(config, db)``
    construction already used elsewhere (test_episode_grain_queue_favorites.py)."""
    from metatv.core.config import Config

    section = HistorySection(Config(), db)
    section._populate_rows(dtos)
    return section


# ---------------------------------------------------------------------------
# 1. EpisodeRepository.get_resume_targets_for_series — batched, deduped
# ---------------------------------------------------------------------------

class TestGetResumeTargetsForSeries:
    def test_returns_next_episode_for_series_with_a_played_episode(self, db):
        _seed_series(db, source_id="series1")
        ep_id = _seed_episode(db, series_source_id="series1", season_num=1,
                               episode_num=3, title="Ep 3")
        with db.session_scope() as session:
            session.get(EpisodeDB, ep_id).last_played = __import__("datetime").datetime.now()

        with db.session_scope(commit=False) as session:
            targets = RepositoryFactory(session).episodes.get_resume_targets_for_series(
                [("series1", "p1")]
            )
        assert ("series1", "p1") in targets
        assert targets[("series1", "p1")].id == ep_id

    def test_series_with_no_episodes_has_no_target(self, db):
        _seed_series(db, source_id="series_empty")
        with db.session_scope(commit=False) as session:
            targets = RepositoryFactory(session).episodes.get_resume_targets_for_series(
                [("series_empty", "p1")]
            )
        assert ("series_empty", "p1") not in targets

    def test_empty_keys_returns_empty_dict(self, db):
        with db.session_scope(commit=False) as session:
            assert RepositoryFactory(session).episodes.get_resume_targets_for_series([]) == {}

    def test_duplicate_keys_are_deduped_not_requeried(self, db):
        """A key repeated across multiple History rows (e.g. two episodes of the same
        series both in the recent-history window) is resolved ONCE, not once per
        occurrence — the batching this helper exists to provide."""
        from sqlalchemy import event

        _seed_series(db, source_id="series1")
        ep_id = _seed_episode(db, series_source_id="series1", episode_num=1)
        with db.session_scope() as session:
            session.get(EpisodeDB, ep_id).last_played = __import__("datetime").datetime.now()

        with db.session_scope(commit=False) as session:
            engine = session.get_bind()
            counter = {"n": 0}

            def _count(conn, cursor, statement, *a):
                if "FROM episodes" in statement:
                    counter["n"] += 1

            event.listen(engine, "before_cursor_execute", _count)
            try:
                # Same key repeated 5 times, as if 5 History rows shared one series.
                keys = [("series1", "p1")] * 5
                targets = RepositoryFactory(session).episodes.get_resume_targets_for_series(keys)
            finally:
                event.remove(engine, "before_cursor_execute", _count)

        assert ("series1", "p1") in targets
        # get_resume_dto for this key issues exactly 2 queries (get_last_engaged, then
        # the get_last_played_dto fallback since nothing was manually engaged) — NOT
        # 5x that, proving the dedup.
        assert counter["n"] == 2, f"expected the ladder to run once for the deduped key, got {counter['n']} queries"


# ---------------------------------------------------------------------------
# 2. build_history_dtos — has_next / next_episode_id / next_episode_code
# ---------------------------------------------------------------------------

class TestBuildHistoryDtosNextEpisode:
    def test_series_with_played_episode_gets_next_episode_fields(self, db):
        from datetime import datetime

        _seed_series(db, name="My Show", source_id="series1")
        ep_id = _seed_episode(db, series_source_id="series1", season_num=2,
                               episode_num=5, title="Ep 5", last_played=datetime.now())

        with db.session_scope(commit=False) as session:
            dtos = build_history_dtos(RepositoryFactory(session), limit=10)

        dto = next(d for d in dtos if d.name == "My Show")
        assert dto.has_next is True
        assert dto.next_episode_id == ep_id
        assert dto.next_episode_code == "S02E05"

    def test_series_with_no_episodes_has_no_next(self, db):
        _seed_series(db, name="Unwatched Series", source_id="series_empty")

        with db.session_scope(commit=False) as session:
            dtos = build_history_dtos(RepositoryFactory(session), limit=10)

        dto = next(d for d in dtos if d.name == "Unwatched Series")
        assert dto.has_next is False
        assert dto.next_episode_id is None
        assert dto.next_episode_code is None

    def test_non_series_row_never_gets_a_next_episode(self, db):
        from datetime import datetime
        with db.session_scope() as session:
            session.add(ChannelDB(
                id="movie1", source_id="movie1", provider_id="p1",
                name="A Movie", media_type="movie", last_played=datetime.now(),
            ))

        with db.session_scope(commit=False) as session:
            dtos = build_history_dtos(RepositoryFactory(session), limit=10)

        dto = next(d for d in dtos if d.name == "A Movie")
        assert dto.has_next is False
        assert dto.next_episode_id is None


# ---------------------------------------------------------------------------
# 3a. build_chip_row's trailing_button slot — transparency + real hit-testing
# ---------------------------------------------------------------------------

class TestChipRowTrailingButton:
    def test_no_trailing_button_row_stays_mouse_transparent(self, qapp):
        """Regression pin: rows WITHOUT a trailing_button are byte-identical to
        every pre-existing caller — still WA_TransparentForMouseEvents."""
        row = build_chip_row(media_icon="S", title="No Button Here")
        assert row.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        assert row.findChild(QPushButton) is None

    def test_trailing_button_row_is_not_mouse_transparent(self, qapp):
        """The row-wide transparency is dropped ONLY when a trailing_button is
        supplied — WA_TransparentForMouseEvents on an ancestor hides the button's
        entire subtree from hit-testing, so it would never be clickable."""
        btn = QPushButton(">>")
        row = build_chip_row(media_icon="S", title="Has A Button", trailing_button=btn)
        assert not row.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        assert row.findChild(QPushButton) is btn

    def test_trailing_button_is_the_last_widget_in_the_row(self, qapp):
        btn = QPushButton(">>")
        row = build_chip_row(
            media_icon="S", title="Title", year="1998", prefix="EN", trailing_button=btn,
        )
        layout = row.layout()
        last_widget = None
        for i in range(layout.count()):
            it = layout.itemAt(i)
            if it.widget() is not None:
                last_widget = it.widget()
        assert last_widget is btn

    def test_embedded_button_receives_real_click_dispatch_via_hit_testing(self, qapp, qtbot):
        """Not just `.click()` (which bypasses hit-testing entirely) — prove Qt's
        REAL widget-at-position resolution lands on the button itself when the row
        hosts a QListWidget itemWidget, which is what makes it independently
        clickable in the actual running app."""
        lw = QListWidget()
        qtbot.addWidget(lw)
        lw.resize(300, 60)
        item = QListWidgetItem(lw)
        btn = QPushButton(">>")
        btn.setFixedSize(30, 20)
        row = build_chip_row(media_icon="S", title="Some Series", trailing_button=btn)
        item.setSizeHint(row.sizeHint())
        lw.setItemWidget(item, row)
        lw.show()
        qapp.processEvents()

        target = QApplication.widgetAt(btn.mapToGlobal(btn.rect().center()))
        assert target is btn, (
            "a real click at the button's screen position must resolve to the "
            "button itself, not the row or the list viewport"
        )

    def test_non_button_area_still_resolves_toward_the_row_not_swallowed_by_a_sibling(self, qapp, qtbot):
        """The title label area must NOT resolve to the button — confirms the two
        regions are independently hit-testable rather than the button's rect
        accidentally covering the row."""
        lw = QListWidget()
        qtbot.addWidget(lw)
        lw.resize(300, 60)
        item = QListWidgetItem(lw)
        btn = QPushButton(">>")
        btn.setFixedSize(30, 20)
        row = build_chip_row(media_icon="S", title="Some Series", trailing_button=btn)
        item.setSizeHint(row.sizeHint())
        lw.setItemWidget(item, row)
        lw.show()
        qapp.processEvents()

        title_label = row.findChild(QLabel)
        target = QApplication.widgetAt(title_label.mapToGlobal(title_label.rect().center()))
        assert target is not btn


# ---------------------------------------------------------------------------
# 3b. HistorySection — button appears only for has_next rows, wires the signal
# ---------------------------------------------------------------------------

class TestHistorySectionPlayNextButton:
    def test_button_present_only_on_has_next_rows(self, qapp):
        dtos = [
            HistoryDTO(id="c1", name="Has Next", media_type="series", episode_code="S01E01",
                       detected_title="Has Next", has_next=True,
                       next_episode_id="ep-1", next_episode_code="S01E02"),
            HistoryDTO(id="c2", name="No Next", media_type="series", episode_code="S01E01",
                       detected_title="No Next", has_next=False),
            HistoryDTO(id="c3", name="A Movie", media_type="movie", episode_code=None,
                       detected_title="A Movie", has_next=False),
        ]
        section = _new_history_section(dtos)

        rows = [section.history_list.itemWidget(section.history_list.item(i))
                for i in range(section.history_list.count())]
        buttons = [row.findChild(QPushButton) for row in rows]

        assert buttons[0] is not None, "has_next row must show the >> button"
        assert buttons[1] is None, "row with has_next=False must not show a button"
        assert buttons[2] is None, "non-series row must not show a button"

    def test_button_tooltip_names_the_target_episode(self, qapp):
        dtos = [
            HistoryDTO(id="c1", name="Has Next", media_type="series", episode_code="S02E04",
                       detected_title="Has Next", has_next=True,
                       next_episode_id="ep-1", next_episode_code="S02E05"),
        ]
        section = _new_history_section(dtos)
        row = _first_chip_row(section.history_list)
        btn = row.findChild(QPushButton)
        assert "S02E05" in btn.toolTip()

    def test_button_click_emits_play_next_clicked_with_episode_id(self, qapp, db):
        dtos = [
            HistoryDTO(id="c1", name="Has Next", media_type="series", episode_code="S01E01",
                       detected_title="Has Next", has_next=True,
                       next_episode_id="ep-42", next_episode_code="S01E02"),
        ]
        section = _real_history_section(db, dtos)
        row = _first_chip_row(section.history_list)
        btn = row.findChild(QPushButton)

        emitted = []
        section.playNextClicked.connect(lambda eid: emitted.append(eid))
        btn.click()

        assert emitted == ["ep-42"]


# ---------------------------------------------------------------------------
# 3c. End-to-end: playNextClicked's episode id resolves through the existing
#     play_episode_by_id chokepoint (never a new play path).
# ---------------------------------------------------------------------------

class TestPlayNextRoutesThroughPlayEpisodeById:
    def test_emitted_episode_id_resolves_and_plays(self, db, qapp):
        from metatv.gui.main_window_series import _SeriesMixin

        _seed_series(db, source_id="series1")
        ep_id = _seed_episode(db, series_source_id="series1", season_num=1,
                               episode_num=2, title="Cat's in the Bag")

        dtos = [
            HistoryDTO(id="c1", name="Breaking Bad", media_type="series", episode_code="S01E01",
                       detected_title="Breaking Bad", has_next=True,
                       next_episode_id=ep_id, next_episode_code="S01E02"),
        ]
        section = _real_history_section(db, dtos)
        row = _first_chip_row(section.history_list)
        btn = row.findChild(QPushButton)

        emitted = []
        section.playNextClicked.connect(lambda eid: emitted.append(eid))
        btn.click()
        assert emitted == [ep_id]

        host = _SeriesMixin.__new__(_SeriesMixin)
        host.db = db
        host.status_bar = MagicMock()
        played = []
        host.play_episode = lambda episode: played.append(episode)

        host.play_episode_by_id(emitted[0])

        assert len(played) == 1
        assert played[0].id == ep_id
        assert played[0].title == "Cat's in the Bag"
        assert played[0].season_num == 1
        assert played[0].episode_num == 2
