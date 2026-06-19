"""Behavioral tests for EPG Discover recommendation rows (PR-6, #8).

Covers:
- _make_recommendation_item button label, routing, and row-click wiring
- Expandable matches sub-list: toggle state, lazy-load call, sub-row rendering
- EpgRepository.get_matching_programs: filtering, ordering, plain-data contract
"""
from __future__ import annotations

import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from metatv.core.database import Database, ChannelDB, EpgProgramDB, ProviderDB
from metatv.core.epg_utils import now_utc
from metatv.core.repositories.epg import EpgRepository


# ---------------------------------------------------------------------------
# Fixtures — QApplication (headless) and file-backed DB
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def file_db(tmp_path):
    """File-backed Database so pooled connections share one schema."""
    db_path = tmp_path / "test.db"
    db = Database(f"sqlite:///{db_path}")
    db.create_tables()
    yield db
    db.close()


# ---------------------------------------------------------------------------
# EpgView stub factory
# ---------------------------------------------------------------------------

class _FakeConfig:
    """Minimal config stub for EpgView construction."""
    epg_watchlist_channels: list = []
    epg_watchlist_patterns: list = ["news"]
    epg_dismissed_channels: dict = {}

    # icon attributes expected by _make_recommendation_item / _make_channel_item
    close_icon = "×"
    play_icon = "▶"
    live_indicator_icon = "🟢"
    watchlist_icon = "⏰"
    series_icon = "📺"
    move_up_icon = "▲"
    move_down_icon = "▼"


def _make_view(qapp, db):
    """Build an EpgView via __new__ + minimal stubs — bypasses full __init__."""
    from metatv.gui.epg_view import EpgView
    from PyQt6.QtWidgets import QWidget
    from concurrent.futures import ThreadPoolExecutor

    view = EpgView.__new__(EpgView)
    QWidget.__init__(view)

    view.config = _FakeConfig()
    view.db = db
    view._executor = ThreadPoolExecutor(max_workers=1)
    view._provider_ids = ["p1"]
    view._channel_name_map = {}
    view._channel_quality_map = {}
    view._channel_prefix_map = {}
    view._channel_title_map = {}

    return view


# ---------------------------------------------------------------------------
# Tests — _make_recommendation_item
# ---------------------------------------------------------------------------

class TestMakeRecommendationItem:
    """Behavioral tests for _make_recommendation_item."""

    def test_watch_button_text_is_plus_channel(self, qapp, file_db):
        """The primary action button must say '+ Channel', not '+ Watch'."""
        view = _make_view(qapp, file_db)
        widget = view._make_recommendation_item("ch-1", "EN - News 24", 3)

        from PyQt6.QtWidgets import QPushButton
        btns = widget.findChildren(QPushButton)
        labels = [b.text() for b in btns]
        assert any(t == "+ Channel" for t in labels), (
            f"Expected '+ Channel' button; found buttons: {labels}"
        )
        assert not any("Watch" in t and "Channel" not in t for t in labels), (
            f"Old '+ Watch' label still present: {labels}"
        )

    def test_watch_button_calls_watch_channel_not_add_pattern(self, qapp, file_db):
        """Clicking '+ Channel' must call _watch_channel(channel_db_id)."""
        view = _make_view(qapp, file_db)

        calls_watch: list[str] = []
        calls_pattern: list[str] = []
        view._watch_channel = lambda cid: calls_watch.append(cid)
        view._add_pattern = lambda n: calls_pattern.append(n)

        widget = view._make_recommendation_item("ch-42", "BBC News", 5)

        from PyQt6.QtWidgets import QPushButton
        btns = widget.findChildren(QPushButton)
        watch_btn = next(b for b in btns if b.text() == "+ Channel")
        watch_btn.click()

        assert calls_watch == ["ch-42"], f"_watch_channel not called with channel_db_id: {calls_watch}"
        assert calls_pattern == [], f"_add_pattern was called (should not be): {calls_pattern}"

    def test_play_button_exists_and_calls_play_channel(self, qapp, file_db):
        """A play button must exist and clicking it calls _play_channel(channel_db_id)."""
        from metatv.gui import icons as _icons

        view = _make_view(qapp, file_db)
        calls_play: list[str] = []
        view._play_channel = lambda cid: calls_play.append(cid)

        widget = view._make_recommendation_item("ch-99", "Sky News", 7)

        from PyQt6.QtWidgets import QPushButton
        btns = widget.findChildren(QPushButton)
        play_btn = next((b for b in btns if b.text() == _icons.play_icon), None)
        assert play_btn is not None, (
            f"Play button not found; buttons: {[b.text() for b in btns]}"
        )
        play_btn.click()
        assert calls_play == ["ch-99"]

    def test_row_click_calls_emit_channel_selected(self, qapp, file_db):
        """Clicking the row body calls _emit_channel_selected(channel_db_id)."""
        view = _make_view(qapp, file_db)

        calls_selected: list[str] = []
        view._emit_channel_selected = lambda cid: calls_selected.append(cid)

        widget = view._make_recommendation_item("ch-7", "CNN", 2)

        # The header_w is the first child widget (outer has header + sub_list).
        from PyQt6.QtWidgets import QWidget
        children = [w for w in widget.findChildren(QWidget) if w.parent() is widget]
        # header_w is the first child with a mousePressEvent override
        header_w = children[0]

        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QMouseEvent
        from PyQt6.QtCore import QPointF, QPoint
        evt = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(0, 0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        header_w.mousePressEvent(evt)

        assert calls_selected == ["ch-7"], f"_emit_channel_selected not called: {calls_selected}"

    def test_skip_button_calls_dismiss_channel(self, qapp, file_db):
        """The skip/dismiss button still calls _dismiss_channel (not broken by refactor)."""
        view = _make_view(qapp, file_db)

        calls_dismiss: list[str] = []
        view._dismiss_channel = lambda cid: calls_dismiss.append(cid)

        widget = view._make_recommendation_item("ch-55", "Fox News", 4)

        from PyQt6.QtWidgets import QPushButton
        btns = widget.findChildren(QPushButton)
        skip_btn = next(b for b in btns if "skip" in b.text())
        skip_btn.click()

        assert calls_dismiss == ["ch-55"]

    def test_count_label_toggles_sub_list_and_loads_on_first_expand(self, qapp, file_db):
        """Clicking the matches count label toggles the sub-list and lazy-loads once."""
        from metatv.gui import icons as _icons

        view = _make_view(qapp, file_db)

        # Capture _load_rec_matches calls
        load_calls: list[tuple] = []

        def _fake_load(channel_db_id, sub_layout):
            load_calls.append((channel_db_id,))
            from PyQt6.QtWidgets import QLabel
            lbl = QLabel("Fake News @ 10:00")
            sub_layout.addWidget(lbl)

        view._load_rec_matches = _fake_load

        widget = view._make_recommendation_item("ch-3", "BBC News", 12)

        from PyQt6.QtWidgets import QLabel, QWidget
        # find the count label (contains "matches")
        lbls = widget.findChildren(QLabel)
        count_lbl = next(l for l in lbls if "matches" in l.text())

        # Initially collapsed: sub-list is hidden.
        # Use isHidden() — in headless Qt, isVisible() is False for all unparented widgets
        # even after show(); isHidden() accurately tracks the explicit hide/show state.
        sub_lists = [w for w in widget.findChildren(QWidget) if w.parent() is widget]
        sub_widget = sub_lists[1]  # second child (after header_w)
        assert sub_widget.isHidden(), "Sub-list should be hidden initially"
        assert _icons.expand_icon in count_lbl.text()

        # First expand
        count_lbl.mousePressEvent(None)
        assert not sub_widget.isHidden(), "Sub-list should not be hidden after expand"
        assert _icons.collapse_icon in count_lbl.text()
        assert len(load_calls) == 1, f"_load_rec_matches should be called once on first expand, got {len(load_calls)}"
        assert load_calls[0][0] == "ch-3"

        # Second expand (collapse) — no additional load
        count_lbl.mousePressEvent(None)
        assert sub_widget.isHidden(), "Sub-list should be hidden after collapse"
        assert _icons.expand_icon in count_lbl.text()
        assert len(load_calls) == 1, "Second expand triggered another load (should not)"

        # Third (re-expand) — still no additional load
        count_lbl.mousePressEvent(None)
        assert not sub_widget.isHidden()
        assert len(load_calls) == 1, "Re-expand triggered a second load (lazy flag broken)"

    def test_load_rec_matches_calls_repo_with_correct_args(self, qapp, file_db):
        """_load_rec_matches passes channel_db_id, patterns, and provider_ids to the repo."""
        view = _make_view(qapp, file_db)
        view.config.epg_watchlist_patterns = ["football", "sports"]
        view._provider_ids = ["prov-1", "prov-2"]

        captured: list[dict] = []

        class _FakeRepos:
            class epg:
                @staticmethod
                def get_matching_programs(channel_db_id, patterns, provider_ids, limit=10):
                    captured.append(dict(channel_db_id=channel_db_id, patterns=patterns, provider_ids=provider_ids))
                    return []

        class _FakeDB:
            from contextlib import contextmanager

            @contextmanager
            def session_scope(self, commit=True):
                class _FakeSession:
                    pass
                yield _FakeSession()

        # Patch out RepositoryFactory so we capture args
        import metatv.gui.epg_view as epg_view_mod
        import metatv.core.repositories as repos_mod

        original_factory = repos_mod.RepositoryFactory

        class _FakeFactory:
            def __init__(self, session):
                self.epg = _FakeRepos.epg

        repos_mod.RepositoryFactory = _FakeFactory
        view.db = _FakeDB()

        from PyQt6.QtWidgets import QVBoxLayout, QWidget
        container = QWidget()
        layout = QVBoxLayout(container)

        try:
            view._load_rec_matches("ch-X", layout)
        finally:
            repos_mod.RepositoryFactory = original_factory

        assert len(captured) == 1
        c = captured[0]
        assert c["channel_db_id"] == "ch-X"
        assert c["patterns"] == ["football", "sports"]
        assert c["provider_ids"] == ["prov-1", "prov-2"]

    def test_load_rec_matches_renders_one_sub_row_per_programme(self, qapp, file_db):
        """_load_rec_matches renders one QLabel per returned programme with its title."""
        from datetime import datetime, timezone
        from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

        view = _make_view(qapp, file_db)

        # Provide fake data directly (bypass DB)
        fake_rows = [
            ("BBC News at Six", datetime(2026, 6, 20, 18, 0, tzinfo=timezone.utc)),
            ("BBC News at Ten", datetime(2026, 6, 20, 22, 0, tzinfo=timezone.utc)),
        ]

        import metatv.core.repositories as repos_mod
        original_factory = repos_mod.RepositoryFactory

        class _FakeRepos:
            class epg:
                @staticmethod
                def get_matching_programs(**kwargs):
                    return fake_rows

        class _FakeFactory:
            def __init__(self, session):
                self.epg = _FakeRepos.epg

        class _FakeDB:
            from contextlib import contextmanager

            @contextmanager
            def session_scope(self, commit=True):
                yield None

        repos_mod.RepositoryFactory = _FakeFactory
        view.db = _FakeDB()

        container = QWidget()
        layout = QVBoxLayout(container)

        try:
            view._load_rec_matches("ch-Y", layout)
        finally:
            repos_mod.RepositoryFactory = original_factory

        labels = container.findChildren(QLabel)
        label_texts = [l.text() for l in labels]
        assert any("BBC News at Six" in t for t in label_texts), (
            f"First programme not rendered: {label_texts}"
        )
        assert any("BBC News at Ten" in t for t in label_texts), (
            f"Second programme not rendered: {label_texts}"
        )


# ---------------------------------------------------------------------------
# Tests — EpgRepository.get_matching_programs (DB behavioral)
# ---------------------------------------------------------------------------

def _seed_provider(session, pid: str) -> None:
    session.add(ProviderDB(
        id=pid, name=pid, type="xtream", url="http://example.com",
        username="u", password="p", is_active=True,
        epg_url="http://example.com/epg.xml",
    ))
    session.flush()


def _seed_channel(session, cid: str, pid: str, name: str) -> ChannelDB:
    ch = ChannelDB(
        id=cid, source_id=str(uuid.uuid4()), provider_id=pid, name=name,
        media_type="live",
    )
    session.add(ch)
    session.flush()
    return ch


def _seed_programme(
    session,
    pid: str,
    cid: str,
    title: str,
    *,
    start_offset_hours: float = 1.0,
    duration_hours: float = 1.0,
    epg_id: str = "ch.default",
) -> EpgProgramDB:
    now = now_utc()
    start = now + timedelta(hours=start_offset_hours)
    stop = start + timedelta(hours=duration_hours)
    prog = EpgProgramDB(
        provider_id=pid,
        channel_epg_id=epg_id,
        channel_db_id=cid,
        title=title,
        start_time=start,
        stop_time=stop,
    )
    session.add(prog)
    session.flush()
    return prog


class TestGetMatchingPrograms:
    """Behavioral tests for EpgRepository.get_matching_programs."""

    @pytest.fixture
    def session(self, file_db):
        s = file_db.get_session()
        yield s
        s.close()

    def test_returns_only_title_matching_programmes(self, session):
        """Only programmes whose titles match a pattern are returned."""
        _seed_provider(session, "p1")
        _seed_channel(session, "ch-1", "p1", "BBC News")
        _seed_programme(session, "p1", "ch-1", "BBC News at Six")
        _seed_programme(session, "p1", "ch-1", "Nature Documentary")  # should NOT match

        repo = EpgRepository(session)
        results = repo.get_matching_programs("ch-1", ["news"], ["p1"])

        titles = [r[0] for r in results]
        assert "BBC News at Six" in titles
        assert "Nature Documentary" not in titles

    def test_excludes_programmes_outside_168h_window(self, session):
        """Programmes starting beyond 168 hours from now are excluded."""
        _seed_provider(session, "p2")
        _seed_channel(session, "ch-2", "p2", "News Channel")
        _seed_programme(session, "p2", "ch-2", "News In Range", start_offset_hours=24)
        _seed_programme(session, "p2", "ch-2", "News Out Of Range", start_offset_hours=200)

        repo = EpgRepository(session)
        results = repo.get_matching_programs("ch-2", ["news"], ["p2"])

        titles = [r[0] for r in results]
        assert "News In Range" in titles
        assert "News Out Of Range" not in titles

    def test_excludes_wrong_channel(self, session):
        """Programmes for a different channel_db_id are not returned."""
        _seed_provider(session, "p3")
        _seed_channel(session, "ch-3a", "p3", "Channel A")
        _seed_channel(session, "ch-3b", "p3", "Channel B")
        _seed_programme(session, "p3", "ch-3a", "Sports News")  # correct channel
        _seed_programme(session, "p3", "ch-3b", "Sports News Hour")  # wrong channel

        repo = EpgRepository(session)
        results = repo.get_matching_programs("ch-3a", ["sports"], ["p3"])

        # Only the programme on ch-3a should appear
        assert len(results) == 1
        assert results[0][0] == "Sports News"

    def test_ordered_by_start_time_ascending(self, session):
        """Results are ordered by start_time ascending."""
        _seed_provider(session, "p4")
        _seed_channel(session, "ch-4", "p4", "News 24")
        _seed_programme(session, "p4", "ch-4", "Late News", start_offset_hours=8)
        _seed_programme(session, "p4", "ch-4", "Morning News", start_offset_hours=2)
        _seed_programme(session, "p4", "ch-4", "Midday News", start_offset_hours=5)

        repo = EpgRepository(session)
        results = repo.get_matching_programs("ch-4", ["news"], ["p4"])

        titles = [r[0] for r in results]
        assert titles == ["Morning News", "Midday News", "Late News"]

    def test_respects_limit(self, session):
        """No more than `limit` results are returned."""
        _seed_provider(session, "p5")
        _seed_channel(session, "ch-5", "p5", "All News")
        for i in range(15):
            _seed_programme(session, "p5", "ch-5", f"News Bulletin {i}", start_offset_hours=i + 1)

        repo = EpgRepository(session)
        results = repo.get_matching_programs("ch-5", ["news"], ["p5"], limit=5)

        assert len(results) == 5

    def test_returns_plain_tuples_not_orm_objects(self, session):
        """Results must be plain (title, start_time) tuples accessible after session close."""
        _seed_provider(session, "p6")
        _seed_channel(session, "ch-6", "p6", "CNN")
        _seed_programme(session, "p6", "ch-6", "CNN Breaking News")

        repo = EpgRepository(session)
        results = repo.get_matching_programs("ch-6", ["breaking"], ["p6"])
        session.close()  # simulate session ending

        # Must be indexable as plain tuples (not detached ORM objects)
        assert len(results) == 1
        title, start_time = results[0]
        assert title == "CNN Breaking News"
        from datetime import datetime
        assert isinstance(start_time, datetime)

    def test_empty_patterns_returns_empty(self, session):
        """No patterns → empty result (not an error)."""
        _seed_provider(session, "p7")
        _seed_channel(session, "ch-7", "p7", "Channel 7")

        repo = EpgRepository(session)
        results = repo.get_matching_programs("ch-7", [], ["p7"])

        assert results == []

    def test_empty_provider_ids_returns_empty(self, session):
        """No provider_ids → empty result (not an error)."""
        _seed_provider(session, "p8")
        _seed_channel(session, "ch-8", "p8", "Channel 8")
        _seed_programme(session, "p8", "ch-8", "News Hour")

        repo = EpgRepository(session)
        results = repo.get_matching_programs("ch-8", ["news"], [])

        assert results == []

    def test_past_programmes_excluded(self, session):
        """Programmes that have already started are excluded (start_time >= now)."""
        _seed_provider(session, "p9")
        _seed_channel(session, "ch-9", "p9", "Retro News")
        # start in the past (negative offset)
        now = now_utc()
        past_start = now - timedelta(hours=2)
        past_stop = now - timedelta(hours=1)
        session.add(EpgProgramDB(
            provider_id="p9",
            channel_epg_id="ch.retro",
            channel_db_id="ch-9",
            title="Past News",
            start_time=past_start,
            stop_time=past_stop,
        ))
        session.flush()
        _seed_programme(session, "p9", "ch-9", "Future News", start_offset_hours=1)

        repo = EpgRepository(session)
        results = repo.get_matching_programs("ch-9", ["news"], ["p9"])

        titles = [r[0] for r in results]
        assert "Future News" in titles
        assert "Past News" not in titles
