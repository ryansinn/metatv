"""Tests for the details pane's Resume button following saved watch progress.

RESUME-1: The details pane's Resume button updates via the channel state bus
when watch progress is saved, so a position written after the pane rendered
still reaches the button (not just on pane re-open).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from metatv.core.models import MediaType
from metatv.gui.details_actions import ChannelActionState, resume_state


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_config():
    from metatv.core.config import Config
    return Config()


def _details_pane(cfg, qtbot):
    from metatv.gui.details_pane import DetailsPaneWidget
    pane = DetailsPaneWidget(cfg, image_cache=MagicMock(), db=None)
    qtbot.addWidget(pane)
    return pane


def _stub_channel(**kw):
    """Mock channel with watch progress fields."""
    ch = MagicMock()
    ch.id = kw.get("id", "chan-1")
    ch.name = kw.get("name", "Test Title")
    ch.media_type = kw.get("media_type", MediaType.MOVIE)
    ch.is_favorite = False
    ch.is_adult = False
    ch.detected_title = kw.get("detected_title", "Test Title")
    ch.detected_year = None
    ch.detected_prefix = None
    ch.detected_quality = None
    ch.detected_region = None
    ch.raw_data = None
    ch.provider_id = None
    ch.watch_completed = kw.get("watch_completed", False)
    ch.watch_progress = kw.get("watch_progress", 0)
    return ch


# ─────────────────────────────────────────────────────────────────────────────
# 1. ActionBar.load() wiring tests (via ActionBar directly to avoid widget leaks)
# ─────────────────────────────────────────────────────────────────────────────

def test_load_sets_resume_with_movie_progress():
    """When load() receives watch_progress > 0 for a movie, set_resume is called."""
    from metatv.gui.details_actions import _ActionBar
    from unittest.mock import MagicMock

    ab = _ActionBar(_make_config())
    ab.set_resume = MagicMock()

    state = ChannelActionState(
        channel_id="chan-1",
        media_type=str(MediaType.MOVIE),
        watch_progress=234,
        watch_completed=False,
    )
    ab.load(state)

    ab.set_resume.assert_called_with(True, 234)




# ─────────────────────────────────────────────────────────────────────────────
# 3. The resume_state() helper is the one predicate for "show Resume"
# ─────────────────────────────────────────────────────────────────────────────

def test_resume_state_is_the_one_predicate(qapp):
    """resume_state() is the single source of truth for Resume button logic."""
    # Movie with progress, not completed → show at that position
    can_resume, pos = resume_state(str(MediaType.MOVIE), 234, False)
    assert can_resume is True
    assert pos == 234

    # Movie with no progress → hide
    can_resume, pos = resume_state(str(MediaType.MOVIE), 0, False)
    assert can_resume is False
    assert pos == 0

    # Movie with progress, but completed → hide
    can_resume, pos = resume_state(str(MediaType.MOVIE), 100, True)
    assert can_resume is False
    assert pos == 100

    # Live with progress → hide (never resume for live)
    can_resume, pos = resume_state(str(MediaType.LIVE), 50, False)
    assert can_resume is False
    assert pos == 50

    # None values → hide and return 0
    can_resume, pos = resume_state(None, None, None)
    assert can_resume is False
    assert pos == 0


def test_load_hides_resume_for_completed_movie():
    """When watch_completed is True, set_resume(False, ...) is called."""
    from metatv.gui.details_actions import _ActionBar
    from unittest.mock import MagicMock

    ab = _ActionBar(_make_config())
    ab.set_resume = MagicMock()

    state = ChannelActionState(
        channel_id="chan-1",
        media_type=str(MediaType.MOVIE),
        watch_progress=234,
        watch_completed=True,
    )
    ab.load(state)

    ab.set_resume.assert_called_with(False, 234)


def test_load_hides_resume_for_live_content():
    """For live media, set_resume(False, ...) is called regardless of progress."""
    from metatv.gui.details_actions import _ActionBar
    from unittest.mock import MagicMock

    ab = _ActionBar(_make_config())
    ab.set_resume = MagicMock()

    state = ChannelActionState(
        channel_id="chan-1",
        media_type=str(MediaType.LIVE),
        watch_progress=50,
        watch_completed=False,
    )
    ab.load(state)

    ab.set_resume.assert_called_with(False, 50)
