"""Series data-anomaly transparency: gap-range labels + the de-doubled toast.

Covers the user-facing de-confusion for genuine provider catalog gaps (a series
whose seasons jump, e.g. 1-4 then 10-25): the muted "Seasons N not provided"
note's range compression, and the fix for the doubled "Loaded Loaded N seasons"
toast (the load message must not repeat the word the view prepends).
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from metatv.core.database import Database
from metatv.core.models import Provider
from metatv.core.provider_loader import SeriesLoadThread
from metatv.gui.main_window_series import _fmt_missing_ranges


@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------------------
# _fmt_missing_ranges — the gap-label compression (the breakable new logic)
# ---------------------------------------------------------------------------

def test_fmt_missing_ranges_single_run():
    """A consecutive run renders as one dash range (the South Park 5-9 case)."""
    assert _fmt_missing_ranges([5, 6, 7, 8, 9]) == "5–9"


def test_fmt_missing_ranges_mixed_runs_and_singletons():
    assert _fmt_missing_ranges([5, 6, 7, 8, 9, 12]) == "5–9, 12"
    assert _fmt_missing_ranges([2, 4, 6]) == "2, 4, 6"
    assert _fmt_missing_ranges([5]) == "5"


def test_fmt_missing_ranges_two_separate_runs():
    assert _fmt_missing_ranges([3, 4, 5, 9, 10]) == "3–5, 9–10"


def test_fmt_missing_ranges_empty():
    assert _fmt_missing_ranges([]) == ""


# ---------------------------------------------------------------------------
# Load message must not double "Loaded" (the toast was "Loaded Loaded N seasons")
# ---------------------------------------------------------------------------

def _series_info() -> dict:
    return {
        "info": {"name": "South Park"},
        "seasons": [],
        "episodes": {
            "1": [{"id": "101", "episode_num": 1, "title": "a", "container_extension": "mp4", "info": {}}],
            "2": [{"id": "201", "episode_num": 1, "title": "b", "container_extension": "mp4", "info": {}}],
        },
    }


class _FakePlugin:
    async def fetch_series_info(self, provider, series_id):  # noqa: D401 - test stub
        return self._info if hasattr(self, "_info") else _series_info()


def test_load_series_message_is_not_doubled(tmp_path, qapp):
    """SeriesLoadThread emits a bare '{n} seasons' so the view's 'Loaded {message}'
    renders 'Loaded 2 seasons', not 'Loaded Loaded 2 seasons'."""
    db = Database(f"sqlite:///{tmp_path / 'msg.db'}")
    db.create_tables()
    try:
        provider = Provider(id="provA", name="A", type="xtream",
                            url="http://h", username="u", password="p")
        captured: list = []

        with patch("metatv.core.provider_loader.get_provider", return_value=_FakePlugin()):
            thread = SeriesLoadThread(provider=provider, series_id="3823",
                                      series_name="South Park", db=db)
            thread.finished.connect(lambda ok, msg, data: captured.append((ok, msg)))
            asyncio.run(thread.load_series())

        assert captured, "finished signal should have fired"
        ok, msg = captured[-1]
        assert ok is True
        assert msg == "2 seasons"                      # two synthetic season groups
        assert not msg.lower().startswith("loaded")    # the view adds 'Loaded ' itself
    finally:
        db.close()
