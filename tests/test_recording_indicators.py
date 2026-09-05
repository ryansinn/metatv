"""``recording_indicators.indicator_for`` — the shared overlap test (REC-2).

On Now, Browse and Watch Alerts all ask the same question: does a channel's
RecordingManager.progress() snapshot overlap THIS row's guide window? The
overlap test is a plain function so it can be pinned here once, rather than
re-derived per surface (and per surface's own fixture soup).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from metatv.core.recording_manager import RecordingProgress
from metatv.gui.recording_indicators import (
    RECORD_TOOLTIP, glyph_for, indicator_for, vector_key_for,
)
from metatv.gui import icons

NOW = datetime(2026, 9, 5, 19, 0, 0)


def _row(channel_id="c1", state="recording", starts_at=None, ends_at=None):
    starts_at = starts_at or NOW
    ends_at = ends_at or (NOW + timedelta(hours=1))
    return RecordingProgress(
        recording_id="r1", channel_id=channel_id, channel_name="BBC One",
        programme_title="The Match", state=state, starts_at=starts_at,
        ends_at=ends_at, recorded_bytes=0, dest_path="", error=None,
        waiting_for_slot=False,
    )


# ── no match ──────────────────────────────────────────────────────────────

def test_no_channel_id_never_matches():
    state, tooltip = indicator_for(
        None, NOW, NOW + timedelta(hours=1), [_row()], NOW)
    assert state is None
    assert tooltip == RECORD_TOOLTIP


def test_no_window_never_matches():
    state, tooltip = indicator_for("c1", None, None, [_row()], NOW)
    assert state is None
    assert tooltip == RECORD_TOOLTIP


def test_different_channel_does_not_match():
    row = _row(channel_id="other")
    state, _ = indicator_for(
        "c1", NOW, NOW + timedelta(hours=1), [row], NOW)
    assert state is None


def test_a_terminal_state_does_not_match():
    """completed/failed/cancelled rows are history, not a claim on this row."""
    row = _row(state="completed")
    state, _ = indicator_for(
        "c1", NOW, NOW + timedelta(hours=1), [row], NOW)
    assert state is None


# ── recording vs scheduled ────────────────────────────────────────────────

def test_recording_state_wins_the_glyph_and_names_its_end():
    row = _row(state="recording", starts_at=NOW, ends_at=NOW + timedelta(hours=2))
    state, tooltip = indicator_for(
        "c1", NOW, NOW + timedelta(hours=1), [row], NOW)
    assert state == "recording"
    assert "21:00" in tooltip  # NOW + 2h, HH:MM


def test_scheduled_state_names_its_start_and_end():
    row = _row(state="scheduled",
               starts_at=NOW + timedelta(hours=3),
               ends_at=NOW + timedelta(hours=4))
    state, tooltip = indicator_for(
        "c1", NOW + timedelta(hours=3), NOW + timedelta(hours=4), [row], NOW)
    assert state == "scheduled"
    assert "22:00" in tooltip and "23:00" in tooltip


def test_recording_outranks_a_simultaneous_scheduled_match():
    recording = _row(state="recording", starts_at=NOW, ends_at=NOW + timedelta(hours=1))
    scheduled = _row(state="scheduled", starts_at=NOW, ends_at=NOW + timedelta(hours=1))
    state, _ = indicator_for(
        "c1", NOW, NOW + timedelta(hours=1), [recording, scheduled], NOW)
    assert state == "recording"


# ── boundary: inclusive at start, exclusive at end ───────────────────────

def test_a_recording_ending_exactly_when_the_row_starts_does_not_match():
    row = _row(state="recording", starts_at=NOW - timedelta(hours=1), ends_at=NOW)
    state, _ = indicator_for(
        "c1", NOW, NOW + timedelta(hours=1), [row], NOW)
    assert state is None, "the recording's END is exclusive"


def test_a_recording_starting_exactly_when_the_row_ends_does_not_match():
    row = _row(state="recording", starts_at=NOW + timedelta(hours=1),
               ends_at=NOW + timedelta(hours=2))
    state, _ = indicator_for(
        "c1", NOW, NOW + timedelta(hours=1), [row], NOW)
    assert state is None, "the row's END is exclusive"


def test_a_recording_starting_exactly_when_the_row_starts_matches():
    row = _row(state="recording", starts_at=NOW, ends_at=NOW + timedelta(hours=1))
    state, _ = indicator_for(
        "c1", NOW, NOW + timedelta(hours=1), [row], NOW)
    assert state == "recording", "each interval's START is inclusive"


def test_a_recording_ending_exactly_when_the_row_ends_matches():
    row = _row(state="recording", starts_at=NOW - timedelta(minutes=30),
               ends_at=NOW + timedelta(hours=1))
    state, _ = indicator_for(
        "c1", NOW, NOW + timedelta(hours=1), [row], NOW)
    assert state == "recording"


# ── glyph/vector-key mapping (the icons.py chokepoint) ───────────────────

def test_glyph_for_every_state():
    assert glyph_for("recording") == icons.recording_active_icon
    assert glyph_for("scheduled") == icons.recording_scheduled_icon
    assert glyph_for(None) == icons.record_icon


def test_vector_key_for_every_state():
    assert vector_key_for("recording") == "recording_active"
    assert vector_key_for("scheduled") == "recording_scheduled"
    assert vector_key_for(None) == "record"
