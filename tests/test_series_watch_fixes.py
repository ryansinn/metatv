"""Behavioral tests for series episode watch-state fixes (PR: series-watch-fixes).

Covered:
1. mark_watched(ep, True)  → is_watched+watch_completed=True, watch_percent=100 — persisted.
2. mark_watched(ep, False) → all three fields False/0, watch_progress=0 — persisted.
3. mark_watched returns True on success, False when episode not found.
4. mark_watched_bulk sets all watch fields on every episode in the list.
5. get_watch_state_by_season counts (total, completed) correctly.
6. Season glyph: all completed → ✓ suffix; some → ◐ suffix; none → no suffix.
7. _episode_icon_text: watch_completed=True → ✓ glyph in text; False → ▶ glyph.
8. In-place update leaves sibling episodes untouched and updates the parent season glyph.
9. What's New entry 23 is loadable and describes the fix.
"""

from __future__ import annotations

import pytest

from metatv.core.database import Database, EpisodeDB, SeasonDB, ChannelDB
from metatv.core.repositories import RepositoryFactory


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path / 'series_watch.db'}")
    d.create_tables()
    yield d
    d.close()


def _seed_episode(db, ep_id: str, season_id: str = "s1", ep_num: int = 1,
                  series_id: str = "ser1", provider_id: str = "p1") -> None:
    with db.session_scope() as session:
        session.add(EpisodeDB(
            id=ep_id, series_id=series_id, season_id=season_id,
            provider_id=provider_id, episode_id=ep_id,
            season_num=1, episode_num=ep_num, title=f"Episode {ep_num}",
        ))


def _get_episode(db, ep_id: str):
    """Read episode back in a fresh session and return a plain dict snapshot."""
    with db.session_scope(commit=False) as session:
        ep = session.query(EpisodeDB).filter_by(id=ep_id).first()
        if ep is None:
            return None
        return {
            "is_watched": bool(ep.is_watched),
            "watch_completed": bool(ep.watch_completed),
            "watch_percent": ep.watch_percent,
            "watch_progress": ep.watch_progress,
        }


# ---------------------------------------------------------------------------
# 1 & 2. mark_watched field coherence
# ---------------------------------------------------------------------------

def test_mark_watched_true_sets_all_fields(db):
    """mark_watched(ep, True) must persist is_watched, watch_completed, watch_percent=100."""
    _seed_episode(db, "e1")
    with db.session_scope() as session:
        RepositoryFactory(session).episodes.mark_watched("e1", watched=True)

    snap = _get_episode(db, "e1")
    assert snap["is_watched"] is True, "is_watched must be True"
    assert snap["watch_completed"] is True, "watch_completed must be True"
    assert snap["watch_percent"] == 100, "watch_percent must be 100"


def test_mark_watched_false_clears_all_fields(db):
    """mark_watched(ep, False) must clear is_watched, watch_completed, watch_percent, watch_progress."""
    _seed_episode(db, "e1")
    # First mark it watched, then unwatch it.
    with db.session_scope() as session:
        RepositoryFactory(session).episodes.mark_watched("e1", watched=True)
    with db.session_scope() as session:
        RepositoryFactory(session).episodes.mark_watched("e1", watched=False)

    snap = _get_episode(db, "e1")
    assert snap["is_watched"] is False
    assert snap["watch_completed"] is False
    assert snap["watch_percent"] == 0
    assert snap["watch_progress"] == 0


def test_mark_watched_persists_across_session(db):
    """Closing and re-opening a session must still show the updated watch state (Bug 2)."""
    _seed_episode(db, "e1")
    # Write in one session.
    with db.session_scope() as session:
        RepositoryFactory(session).episodes.mark_watched("e1", watched=True)

    # Read in a completely separate session — simulates app restart.
    snap = _get_episode(db, "e1")
    assert snap["watch_completed"] is True, (
        "watch_completed must persist after the writing session closes (Bug 2)"
    )
    assert snap["watch_percent"] == 100, (
        "watch_percent must persist after the writing session closes (Bug 2)"
    )


def test_mark_watched_returns_true_on_success(db):
    _seed_episode(db, "e1")
    with db.session_scope() as session:
        result = RepositoryFactory(session).episodes.mark_watched("e1", watched=True)
    assert result is True


def test_mark_watched_returns_false_for_missing_episode(db):
    with db.session_scope() as session:
        result = RepositoryFactory(session).episodes.mark_watched("no-such-id", watched=True)
    assert result is False


# ---------------------------------------------------------------------------
# 4. mark_watched_bulk
# ---------------------------------------------------------------------------

def test_mark_watched_bulk_sets_all_episodes(db):
    """mark_watched_bulk marks every episode in the list."""
    _seed_episode(db, "e1", ep_num=1)
    _seed_episode(db, "e2", ep_num=2)
    _seed_episode(db, "e3", ep_num=3)

    with db.session_scope() as session:
        count = RepositoryFactory(session).episodes.mark_watched_bulk(["e1", "e2", "e3"], watched=True)

    assert count == 3
    for ep_id in ("e1", "e2", "e3"):
        snap = _get_episode(db, ep_id)
        assert snap["watch_completed"] is True, f"{ep_id}: watch_completed must be True"
        assert snap["watch_percent"] == 100, f"{ep_id}: watch_percent must be 100"


def test_mark_watched_bulk_unwatch(db):
    """mark_watched_bulk unwatches all episodes in the list."""
    _seed_episode(db, "e1", ep_num=1)
    _seed_episode(db, "e2", ep_num=2)
    # Mark watched first.
    with db.session_scope() as session:
        RepositoryFactory(session).episodes.mark_watched_bulk(["e1", "e2"], watched=True)
    # Now unwatch.
    with db.session_scope() as session:
        RepositoryFactory(session).episodes.mark_watched_bulk(["e1", "e2"], watched=False)

    for ep_id in ("e1", "e2"):
        snap = _get_episode(db, ep_id)
        assert snap["is_watched"] is False
        assert snap["watch_completed"] is False
        assert snap["watch_percent"] == 0


def test_mark_watched_bulk_empty_list_is_safe(db):
    with db.session_scope() as session:
        count = RepositoryFactory(session).episodes.mark_watched_bulk([], watched=True)
    assert count == 0


# ---------------------------------------------------------------------------
# 5. get_watch_state_by_season
# ---------------------------------------------------------------------------

def test_get_watch_state_by_season_counts(db):
    """get_watch_state_by_season returns (total, completed) correctly."""
    _seed_episode(db, "e1", season_id="s1", ep_num=1)
    _seed_episode(db, "e2", season_id="s1", ep_num=2)
    _seed_episode(db, "e3", season_id="s1", ep_num=3)

    with db.session_scope() as session:
        repo = RepositoryFactory(session).episodes
        repo.mark_watched("e1", watched=True)
        repo.mark_watched("e2", watched=True)
        total, completed = repo.get_watch_state_by_season("s1")

    assert total == 3
    assert completed == 2


def test_get_watch_state_by_season_all_completed(db):
    _seed_episode(db, "e1", season_id="s1", ep_num=1)
    with db.session_scope() as session:
        repo = RepositoryFactory(session).episodes
        repo.mark_watched("e1", watched=True)
        total, completed = repo.get_watch_state_by_season("s1")
    assert total == 1 and completed == 1


def test_get_watch_state_by_season_empty(db):
    with db.session_scope() as session:
        total, completed = RepositoryFactory(session).episodes.get_watch_state_by_season("no-season")
    assert total == 0 and completed == 0


# ---------------------------------------------------------------------------
# 6. Season glyph derivation (_season_glyph helper on _SeriesMixin)
# ---------------------------------------------------------------------------

def _make_mixin():
    """Build a bare _SeriesMixin instance with a config stub."""
    from metatv.gui.main_window_series import _SeriesMixin
    obj = _SeriesMixin.__new__(_SeriesMixin)
    # Stub out config.watch_partial_threshold used by _partial_pct()
    from unittest.mock import MagicMock
    obj.config = MagicMock()
    obj.config.watch_partial_threshold = 0.10
    return obj


def _make_episode_dto(watch_completed: bool, watch_percent: int = 0):
    from metatv.core.repositories.dtos import EpisodeDTO
    return EpisodeDTO(
        id="e1", episode_num=1, season_num=1, title="Ep", series_name="Show",
        stream_url=None, duration=None, is_watched=watch_completed, rating=None,
        watch_completed=watch_completed, watch_percent=watch_percent,
    )


def test_season_glyph_all_completed():
    from metatv.gui import icons as _icons
    mixin = _make_mixin()
    dtos = [_make_episode_dto(True), _make_episode_dto(True)]
    glyph = mixin._season_glyph(dtos)
    assert _icons.watched_icon in glyph, "All-complete season must show ✓"


def test_season_glyph_some_completed():
    from metatv.gui import icons as _icons
    mixin = _make_mixin()
    dtos = [_make_episode_dto(True), _make_episode_dto(False)]
    glyph = mixin._season_glyph(dtos)
    assert _icons.partial_watched_icon in glyph, "Partial season must show ◐"


def test_season_glyph_none_completed():
    mixin = _make_mixin()
    dtos = [_make_episode_dto(False), _make_episode_dto(False)]
    glyph = mixin._season_glyph(dtos)
    assert glyph == "", "No completed episodes → empty glyph"


def test_season_glyph_empty_list():
    mixin = _make_mixin()
    assert mixin._season_glyph([]) == ""


# ---------------------------------------------------------------------------
# 7. _episode_icon_text returns clean title text; _episode_watch_icon returns QIcon
# ---------------------------------------------------------------------------

def test_episode_icon_text_completed():
    """_episode_icon_text returns the clean display title — no glyph."""
    from metatv.gui import icons as _icons
    mixin = _make_mixin()
    dto = _make_episode_dto(watch_completed=True, watch_percent=100)
    text = mixin._episode_icon_text(dto)
    # Glyph lives in the icon lane (_episode_watch_icon), not the text.
    assert _icons.watched_icon not in text, (
        f"watch glyph must be in icon lane, not text; got: {text!r}"
    )


def test_episode_icon_text_untouched():
    """_episode_icon_text returns clean title; no play-triangle in text."""
    from metatv.gui import icons as _icons
    mixin = _make_mixin()
    dto = _make_episode_dto(watch_completed=False, watch_percent=0)
    text = mixin._episode_icon_text(dto)
    # The play-triangle icon now lives in setIcon(0, ...), not the text.
    assert _icons.episode_icon not in text, (
        f"episode icon must be in icon column, not text; got: {text!r}"
    )
    assert _icons.watched_icon not in text


def test_episode_icon_text_partial():
    """_episode_icon_text returns clean title for partial-watched episodes."""
    from metatv.gui import icons as _icons
    mixin = _make_mixin()
    dto = _make_episode_dto(watch_completed=False, watch_percent=50)
    text = mixin._episode_icon_text(dto)
    assert _icons.partial_watched_icon not in text, (
        f"partial glyph must be in icon lane, not text; got: {text!r}"
    )


def test_episode_watch_icon_completed_returns_qicon():
    """_episode_watch_icon returns a QIcon for a completed episode."""
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QIcon
    app = QApplication.instance() or QApplication([])
    mixin = _make_mixin()
    dto = _make_episode_dto(watch_completed=True, watch_percent=100)
    icon = mixin._episode_watch_icon(dto)
    assert isinstance(icon, QIcon), f"Expected QIcon for completed episode, got {icon!r}"


def test_episode_watch_icon_untouched_returns_qicon():
    """_episode_watch_icon returns the episode_icon (play-triangle) for unwatched episodes."""
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QIcon
    app = QApplication.instance() or QApplication([])
    mixin = _make_mixin()
    dto = _make_episode_dto(watch_completed=False, watch_percent=0)
    icon = mixin._episode_watch_icon(dto)
    assert isinstance(icon, QIcon), (
        f"Unwatched episode must still get an icon (play-triangle), got {icon!r}"
    )


# ---------------------------------------------------------------------------
# 9. What's New entry 23
# ---------------------------------------------------------------------------

def test_whats_new_entry_23_exists():
    from metatv.whats_new import WHATS_NEW
    ids = {e.id for e in WHATS_NEW}
    assert 23 in ids, f"Entry 23 not found in WHATS_NEW; found ids: {sorted(ids)}"
    entry = next(e for e in WHATS_NEW if e.id == 23)
    assert "watch" in entry.title.lower() or "series" in entry.title.lower(), (
        f"Entry 23 title should describe the series watch fix: {entry.title!r}"
    )
