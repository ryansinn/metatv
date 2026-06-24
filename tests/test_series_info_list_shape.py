"""Regression: list-shaped episode 'info' field must not crash SeriesLoadThread.

Bug: double-clicking a SERIES card in the Recipe view triggered
  AttributeError: 'list' object has no attribute 'get'
inside SeriesLoadThread.load_series().  The crash site was:
  info = episode_data.get("info", {})
  duration = info.get("duration", ...)    # <- AttributeError when info is a list

Some Xtream providers return ``"info": [...]`` (a list) instead of a dict for
certain episode records.  The fix adds a type check and degrades non-dict info
to an empty dict with a debug log, so the episode is stored (with empty
duration/cover) rather than crashing the whole series load.

Tests drive SeriesLoadThread.load_series() directly with:
  1. A list-shaped episode ``info`` field — must not raise, must succeed.
  2. A top-level series_data whose overall response is a list — must emit
     finished(False, ...) cleanly (existing guard, not broken by the fix).
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from metatv.core.database import Database
from metatv.core.models import Provider
from metatv.core.provider_loader import SeriesLoadThread


@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _provider() -> Provider:
    return Provider(
        id="prov1",
        name="Test",
        type="xtream",
        url="http://example.com",
        username="u",
        password="p",
    )


def _series_data_with_list_info() -> dict:
    """Series response where an episode's 'info' field is a list, not a dict.

    This is the shape that triggered the AttributeError in production.
    """
    return {
        "info": {"name": "Crash Show"},
        "seasons": [
            {"season_number": 1, "name": "Season 1", "cover": "", "episodes": 1}
        ],
        "episodes": {
            "1": [
                {
                    "id": "101",
                    "episode_num": 1,
                    "title": "Pilot",
                    "container_extension": "mp4",
                    # info is a list — the offending shape
                    "info": ["some", "bad", "data"],
                }
            ]
        },
    }


class _FakePlugin:
    """Provider plugin stub: returns the configured series data."""

    def __init__(self, series_data):
        self._data = series_data

    async def fetch_series_info(self, provider, series_id):
        return self._data


# ---------------------------------------------------------------------------
# Test 1: list-shaped episode info does NOT crash — episode stored successfully
# ---------------------------------------------------------------------------

def test_list_info_does_not_raise(tmp_path, qapp):
    """A list-shaped episode 'info' field must not raise AttributeError.

    The series load should succeed and finish(True, ...) — the episode is
    stored with empty duration/cover rather than crashing the load.
    """
    db = Database(f"sqlite:///{tmp_path / 'list_info.db'}")
    db.create_tables()
    try:
        provider = _provider()
        captured: list = []

        plugin = _FakePlugin(_series_data_with_list_info())
        with patch("metatv.core.provider_loader.get_provider", return_value=plugin):
            thread = SeriesLoadThread(
                provider=provider,
                series_id="999",
                series_name="Crash Show",
                db=db,
            )
            thread.finished.connect(lambda ok, msg, data: captured.append((ok, msg)))
            asyncio.run(thread.load_series())

        assert captured, "finished signal should have fired"
        ok, msg = captured[-1]
        assert ok is True, f"Expected success but got: {msg}"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Test 2: top-level list-shaped series_data emits finished(False, ...) cleanly
# ---------------------------------------------------------------------------

def test_top_level_list_response_emits_error_not_crash(tmp_path, qapp):
    """When the whole series_data is a list (not a dict), the thread emits
    finished(False, ...) without raising an exception.

    This exercises the existing top-level guard added before the fix.
    """
    db = Database(f"sqlite:///{tmp_path / 'top_list.db'}")
    db.create_tables()
    try:
        provider = _provider()
        captured: list = []

        plugin = _FakePlugin([{"bad": "shape"}])  # top-level list, not dict
        with patch("metatv.core.provider_loader.get_provider", return_value=plugin):
            thread = SeriesLoadThread(
                provider=provider,
                series_id="888",
                series_name="Bad Shape Show",
                db=db,
            )
            thread.finished.connect(lambda ok, msg, data: captured.append((ok, msg)))
            asyncio.run(thread.load_series())

        assert captured, "finished signal should have fired"
        ok, msg = captured[-1]
        assert ok is False
        assert "Unexpected API response format" in msg or "format" in msg.lower()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Test 3: dict-shaped episode info continues to work (no regression)
# ---------------------------------------------------------------------------

def test_normal_dict_info_still_works(tmp_path, qapp):
    """A normal dict-shaped episode 'info' field must still be parsed correctly."""
    db = Database(f"sqlite:///{tmp_path / 'dict_info.db'}")
    db.create_tables()
    try:
        provider = _provider()
        captured: list = []

        series_data = {
            "info": {"name": "Normal Show"},
            "seasons": [
                {"season_number": 1, "name": "Season 1", "cover": "", "episodes": 1}
            ],
            "episodes": {
                "1": [
                    {
                        "id": "201",
                        "episode_num": 1,
                        "title": "Episode One",
                        "container_extension": "mp4",
                        "info": {"duration": "42:00", "movie_image": "http://img/1.jpg"},
                    }
                ]
            },
        }
        plugin = _FakePlugin(series_data)
        with patch("metatv.core.provider_loader.get_provider", return_value=plugin):
            thread = SeriesLoadThread(
                provider=provider,
                series_id="777",
                series_name="Normal Show",
                db=db,
            )
            thread.finished.connect(lambda ok, msg, data: captured.append((ok, msg)))
            asyncio.run(thread.load_series())

        assert captured
        ok, msg = captured[-1]
        assert ok is True, f"Normal dict-info load should succeed, got: {msg}"
    finally:
        db.close()
