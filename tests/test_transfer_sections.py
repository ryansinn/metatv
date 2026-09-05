"""The Downloads and Recordings sidebar sections render what the engines report.

*Catch, Keep, Record* (2026-08-30) shipped its engines in #612 with **no
surface at all** — the worklog recorded "the engines shipped; the surfaces were
never built". These are slice 4's sections.

The spec is explicit about what these are NOT:

    Center panel: a scope on the channel list, not a second browse surface...
    The sidebar section stays, because it answers a different question: the
    scope is "what do I have", the section is "what is happening right now".

So every assertion here is about *right now* — state and progress — and the
tests assert the **rendered row**, not the DTO they were handed.

Two rules from the design carry real weight and are pinned:

* **A state is a word, never a colour.** "Paused" and "Failed" have to be
  tellable apart by someone who cannot distinguish the two fills.
* **Unknown size draws no bar**, rather than a bar at zero — an empty bar
  reads as broken, not as unknown. Same for a recording that has not started.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from metatv.core.download_manager import DownloadProgress
from metatv.core.recording_manager import RecordingProgress
from metatv.gui.progress_paint import ProgressBar

NOW = datetime(2026, 9, 1, 20, 0, 0)


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def config(tmp_path):
    from metatv.core.config import Config
    return Config(config_dir=tmp_path / "config")


def _downloads(config):
    from metatv.gui.sidebar.downloads import DownloadsSection
    return DownloadsSection(config, db=None)


def _recordings(config):
    from metatv.gui.sidebar.recordings import RecordingsSection
    return RecordingsSection(config, db=None)


def _dl(**kw) -> DownloadProgress:
    base = {"id": "d1", "channel_id": "c1", "channel_name": "Ghostbusters",
            "provider_id": "p1", "state": "running",
            "downloaded_bytes": 500_000_000, "total_bytes": 1_200_000_000,
            "dest_path": "/lib/gb.mkv", "error": None,
            "paused_by_playback": False}
    base.update(kw)
    return DownloadProgress(**base)


def _rec(**kw) -> RecordingProgress:
    base = {"recording_id": "r1", "channel_id": "c9", "channel_name": "BBC One",
            "programme_title": "The Match", "state": "recording",
            "starts_at": NOW - timedelta(minutes=30),
            "ends_at": NOW + timedelta(minutes=30),
            "recorded_bytes": 42_000_000,
            "dest_path": "/lib/Recordings/match.ts", "error": None,
            "waiting_for_slot": False}
    base.update(kw)
    return RecordingProgress(**base)


def _row_text(section, lst_name: str, i: int = 0) -> str:
    """Every string actually rendered into row *i*, joined.

    Buttons as well as labels: a chip is a flat ``QPushButton``, deliberately
    (``chip_widget`` — "As QLabels the year and language chips looked looser
    ... because a QLabel's border wraps the font's full line box"). Reading
    only labels would silently miss every state word on the row, which is the
    thing these tests exist to check.
    """
    from PyQt6.QtWidgets import QLabel, QPushButton
    lst = getattr(section, lst_name)
    widget = lst.itemWidget(lst.item(i))
    parts = [w.text() for w in widget.findChildren((QLabel, QPushButton)) if w.text()]
    return " | ".join(parts)


def _row_bar(section, lst_name: str, i: int = 0):
    lst = getattr(section, lst_name)
    widget = lst.itemWidget(lst.item(i))
    bars = widget.findChildren(ProgressBar)
    return bars[0] if bars else None


# ── Downloads ──────────────────────────────────────────────────────────────


def test_a_running_download_shows_its_title_state_and_bar(qapp, config):
    s = _downloads(config)
    s.refresh_progress([_dl()])
    # Row 0 is now the "In progress" heading (active rows render under one) —
    # row 1 is the download itself.
    text = _row_text(s, "downloads_list", i=1)
    assert "Ghostbusters" in text
    assert "Downloading" in text, f"no state word rendered: {text!r}"
    assert _row_bar(s, "downloads_list", i=1) is not None, "a known size must draw a bar"


def test_a_download_paused_by_playback_says_which_kind_of_paused(qapp, config):
    """The spec asks for exactly this distinction.

    *"a download pauses itself when you start watching and resumes when you
    stop, and the row says which of those it is doing."* On a one-connection
    account that is the scheduler working, not a fault — and a row reading
    plain "Paused" makes it look like something stopped.
    """
    s = _downloads(config)
    s.refresh_progress([_dl(state="paused", paused_by_playback=True)])
    text = _row_text(s, "downloads_list", i=1)
    assert "playing" in text.lower(), (
        f"a self-pause is indistinguishable from a user pause: {text!r}")

    s.refresh_progress([_dl(state="paused", paused_by_playback=False)])
    user_text = _row_text(s, "downloads_list", i=1)
    assert "Paused" in user_text and "playing" not in user_text.lower(), (
        f"a user pause claims playback caused it: {user_text!r}")


def test_an_unknown_size_draws_no_bar_rather_than_an_empty_one(qapp, config):
    """None, not 0.0 — DownloadProgress.fraction makes that distinction on purpose."""
    s = _downloads(config)
    s.refresh_progress([_dl(total_bytes=None)])
    assert _row_bar(s, "downloads_list", i=1) is None, (
        "drew a bar at zero for a download whose size the server never gave — "
        "that reads as stalled, not as unknown")
    assert "Downloading" in _row_text(s, "downloads_list", i=1)


def test_every_download_state_renders_a_distinct_word(qapp, config):
    """Colour alone must never be the difference between these."""
    from metatv.gui.sidebar.downloads import download_state_word

    words = {download_state_word(st) for st in
             ("queued", "running", "paused", "completed", "failed")}
    assert len(words) == 5, f"two states share a word: {sorted(words)}"
    assert all(w and not w.islower() for w in words)


def test_an_empty_download_list_is_empty_not_a_stale_row(qapp, config):
    s = _downloads(config)
    s.refresh_progress([_dl()])
    s.refresh_progress([])
    assert s.downloads_list.count() == 0


# ── Downloads: queue-with-reasons, speed/ETA, history + playback (DL-4) ─────


def test_active_rows_render_under_an_in_progress_heading_first(qapp, config):
    """Active work always leads; a history heading (if any) always follows it."""
    from metatv.gui.sidebar.base import GroupHeading
    from metatv.gui.sidebar.transfer_rows import ROLE_ITEM_ID

    s = _downloads(config)
    s.refresh_progress([_dl(id="d1"), _dl(id="d2", channel_name="Alien")])

    lst = s.downloads_list
    heading = lst.itemWidget(lst.item(0))
    assert isinstance(heading, GroupHeading)
    assert heading.label.text() == "In progress"
    assert heading.count_label.text().strip() == "2"
    assert lst.item(1).data(ROLE_ITEM_ID) == "d1", "the rows follow their heading"
    assert lst.item(2).data(ROLE_ITEM_ID) == "d2"


def test_a_running_rows_meta_carries_size_rate_and_eta(qapp, config):
    """The mock's own line: "... of ... · ... MB/s · ~... min left"."""
    s = _downloads(config)
    s.refresh_progress([_dl(
        downloaded_bytes=4_100_000_000, total_bytes=6_600_000_000,
        bytes_per_second=11_200_000, eta_seconds=180,
    )])
    text = _row_text(s, "downloads_list", i=1)
    assert "4.1 GB" in text and "6.6 GB" in text, f"no size in {text!r}"
    assert "MB/s" in text, f"no rate in {text!r}"
    assert "min left" in text, f"no ETA in {text!r}"


def test_a_queued_rows_meta_is_the_connection_reason(qapp, config):
    """Not "Queued" alone — the row explains WHY, the way the mock shows."""
    s = _downloads(config)
    reason = "Queued — this source allows 1 connection and it is in use."
    s.refresh_progress([_dl(state="queued", downloaded_bytes=0, reason=reason)])
    text = _row_text(s, "downloads_list", i=1)
    assert reason in text, f"the connection reason never reached the row: {text!r}"


def test_a_completed_row_sits_under_a_today_heading(qapp, config, tmp_path):
    """A finished download joins HISTORY's own Today/Yesterday/… segments."""
    from metatv.core.epg_utils import from_local_naive

    dest = tmp_path / "gb.mkv"
    dest.write_bytes(b"already finished")
    pinned_now = datetime(2026, 9, 5, 20, 0, 0)
    finished_local = pinned_now - timedelta(hours=3)   # same day, outside "hour"

    s = _downloads(config)
    s.refresh_progress(
        [_dl(state="completed", dest_path=str(dest),
             updated_at=from_local_naive(finished_local))],
        now=pinned_now,
    )

    lst = s.downloads_list
    heading = lst.itemWidget(lst.item(0))
    assert heading.label.text() == "Today"
    text = _row_text(s, "downloads_list", i=1)
    assert "Ghostbusters" in text
    assert "file removed" not in text.lower()


def test_a_completed_row_whose_file_is_gone_reads_file_removed(qapp, config):
    """DL-2: the ledger says 'completed', the DISK is what actually decides."""
    s = _downloads(config)
    s.refresh_progress([_dl(
        state="completed", dest_path="/no/such/file/anywhere.mkv",
        updated_at=datetime.utcnow(),
    )])
    text = _row_text(s, "downloads_list", i=1)
    assert "file removed" in text.lower(), f"a deleted file must say so: {text!r}"


def test_pause_all_toggles_the_config_flag_and_relabels_itself(qapp, config):
    """The ⋯ menu's Pause/Resume all — a config flip, nothing more to wire."""
    s = _downloads(config)
    assert config.downloads_paused is False
    labels = [a.label for a in s.overflow_actions()]
    assert any("Pause all downloads" in label for label in labels)

    s._toggle_downloads_paused()

    assert config.downloads_paused is True
    labels = [a.label for a in s.overflow_actions()]
    assert any("Resume all downloads" in label for label in labels)


# ── Recordings ─────────────────────────────────────────────────────────────


def test_a_running_recording_measures_the_clock_not_bytes(qapp, config):
    """A live stream has no total size; the only honest bar is the window."""
    s = _recordings(config)
    s.refresh_progress([_rec()], now=NOW)
    bar = _row_bar(s, "recordings_list")
    assert bar is not None
    # 30 of 60 minutes elapsed.
    assert abs(bar._pct - 50.0) < 1.0, f"bar reads {bar._pct}, expected ~50"
    assert "The Match" in _row_text(s, "recordings_list")


def test_the_clock_is_taken_not_reached_for(qapp, config):
    """Same moment in, same bar out — a test can pin one and so can a repaint.

    A helper that reaches for the real clock underneath a supplied one has
    been found three times in this codebase in a single day, once silently
    deleting 29.75 days instead of 30.
    """
    s = _recordings(config)
    s.refresh_progress([_rec()], now=NOW - timedelta(minutes=15))
    early = _row_bar(s, "recordings_list")._pct
    s.refresh_progress([_rec()], now=NOW + timedelta(minutes=15))
    late = _row_bar(s, "recordings_list")._pct
    assert early < late, "the injected clock did not move the bar"
    assert abs(early - 25.0) < 1.0 and abs(late - 75.0) < 1.0


def test_a_scheduled_recording_draws_no_bar(qapp, config):
    """Nothing has happened yet — a bar at zero would say it had stalled."""
    s = _recordings(config)
    s.refresh_progress([_rec(state="scheduled", recorded_bytes=0)], now=NOW)
    assert _row_bar(s, "recordings_list") is None
    assert "Scheduled" in _row_text(s, "recordings_list")


def test_waiting_for_the_source_is_its_own_word(qapp, config):
    """The one state where the user can still act, so it must not read as normal."""
    s = _recordings(config)
    s.refresh_progress([_rec(state="scheduled", waiting_for_slot=True)], now=NOW)
    text = _row_text(s, "recordings_list")
    assert "Waiting" in text, (
        f"a recording blocked on the connection looks merely scheduled: {text!r}")


def test_every_recording_state_renders_a_distinct_word(qapp, config):
    from metatv.gui.sidebar.recordings import recording_state_word

    words = {recording_state_word(st) for st in
             ("scheduled", "recording", "completed", "failed", "cancelled")}
    assert len(words) == 5, f"two states share a word: {sorted(words)}"


# ── the shared row ─────────────────────────────────────────────────────────


def test_both_sections_use_the_one_row_builder(qapp, config):
    """Not two row grammars for one idea — the failure this codebase repeats."""
    import inspect

    from metatv.gui.sidebar import downloads, recordings

    for mod in (downloads, recordings):
        src = inspect.getsource(mod)
        assert "add_transfer_row" in src, (
            f"{mod.__name__} builds its own row instead of the shared one")
        assert "build_chip_row" not in src, (
            f"{mod.__name__} reaches past add_transfer_row to the chip builder, "
            "which is how the two sections drift apart")


def test_human_bytes_uses_the_units_a_file_manager_shows():
    from metatv.gui.sidebar.transfer_rows import human_bytes

    assert human_bytes(None) == ""
    assert human_bytes(0) == "0 B"
    assert human_bytes(1_200_000_000) == "1.2 GB"
