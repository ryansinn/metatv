"""Watch Alerts stays current against the clock.

The bug these cover: the list was a snapshot of whenever it last loaded.
``alerts.py`` computed every relative time from ``now`` at populate time and
the section owned no periodic timer, so a finished programme stayed listed and
a row reading "in 13m" was already playing.

Two mechanisms, and they are tested separately because they answer different
questions: the tick keeps the TEXT true, the boundary timer keeps MEMBERSHIP
true.
"""

from datetime import datetime, timedelta

import pytest

from metatv.core.config import Config
from metatv.gui.relative_time import humanize_remaining, humanize_until
from metatv.gui.sidebar.alerts import WatchAlertsSection
from metatv.gui.sidebar.alerts_rows import _AlertRow


NOW = datetime(2026, 8, 26, 12, 0, 0)


# ── the formatters ──────────────────────────────────────────────────────
def test_remaining_counts_down_and_bottoms_out_at_ending():
    assert humanize_remaining(NOW + timedelta(minutes=13), NOW) == "13m left"
    assert humanize_remaining(NOW + timedelta(seconds=20), NOW) == "ending"
    # Already finished: never a negative count.
    assert humanize_remaining(NOW - timedelta(minutes=5), NOW) == "ending"
    assert humanize_remaining(None, NOW) == ""


def test_until_switches_from_countdown_to_a_clock_time():
    assert humanize_until(NOW + timedelta(minutes=13), NOW) == "in 13m"
    # Past the hour a countdown stops being readable, so the ladder switches —
    # but only when the caller supplied the localisation helpers.
    later = NOW + timedelta(hours=3)
    assert humanize_until(later, NOW) == "in 180m"
    assert humanize_until(
        later, NOW, to_local=lambda d: d, is_local_today=lambda d: True
    ) == "3:00 PM"
    assert humanize_until(
        later, NOW, to_local=lambda d: d, is_local_today=lambda d: False
    ).endswith("3:00 PM")


# ── the tick keeps the TEXT true ────────────────────────────────────────
def test_a_row_recomputes_its_own_time_without_a_requery(qapp, tmp_path):
    """The exact reported symptom: a row saying "in 13m" that is already on.

    Built at ``NOW`` and then ticked 13 minutes later, the row must say so
    itself — no reload, no query, from the timestamp it kept.
    """
    cfg = Config(config_dir=tmp_path)
    row = _AlertRow(
        "ORF 2 WIEN",
        humanize_until(NOW + timedelta(minutes=13), NOW),
        cfg,
        when=NOW + timedelta(minutes=13),
        live=False,
    )
    assert row.time_lbl.text() == "in 13m"

    row.refresh_time(NOW + timedelta(minutes=13))
    assert row.time_lbl.text() == "in 0m", "the row never re-read its own clock"


def test_a_live_row_counts_down_as_the_programme_runs(qapp, tmp_path):
    cfg = Config(config_dir=tmp_path)
    stop = NOW + timedelta(minutes=30)
    row = _AlertRow("ORF 2 WIEN", humanize_remaining(stop, NOW), cfg,
                    when=stop, live=True)
    assert row.time_lbl.text() == "30m left"
    row.refresh_time(NOW + timedelta(minutes=27))
    assert row.time_lbl.text() == "3m left"
    row.refresh_time(stop)
    assert row.time_lbl.text() == "ending"


def test_a_row_with_no_timestamp_is_left_alone(qapp, tmp_path):
    """Not every row's text is time-derived; those must not be rewritten."""
    row = _AlertRow("ORF 2 WIEN", "retrying", Config(config_dir=tmp_path))
    row.refresh_time(NOW + timedelta(days=1))
    assert row.time_lbl.text() == "retrying"


# ── the section owns the tick ───────────────────────────────────────────
def test_the_section_runs_a_repaint_tick(qapp, tmp_path):
    sec = WatchAlertsSection(Config(config_dir=tmp_path), db=None)
    clock = sec.__dict__.get("_clock")
    assert clock is not None, "the section owns no repaint tick"
    assert clock.isActive()
    assert clock.interval() == sec.TICK_MS


def test_the_tick_is_a_no_op_while_collapsed(qapp, tmp_path):
    """Repainting rows nobody can see is the one cost this cannot justify.

    Asserts the ROW is untouched, not merely that ``_tick`` returns: a version
    of this test that just called ``_tick()`` passed with the guard deleted,
    which is fake coverage for exactly the branch it names.
    """
    from PyQt6.QtWidgets import QTreeWidgetItem

    sec = WatchAlertsSection(Config(config_dir=tmp_path), db=None)
    stop = NOW + timedelta(minutes=30)
    row = _AlertRow("ORF 2 WIEN", humanize_remaining(stop, NOW),
                    sec.config, when=stop, live=True)
    item = QTreeWidgetItem()
    sec.alerts_tree.addTopLevelItem(item)
    sec.alerts_tree.setItemWidget(item, 0, row)
    assert row.time_lbl.text() == "30m left"

    sec.is_collapsed = True
    sec._tick()
    assert row.time_lbl.text() == "30m left", "a collapsed section repainted its rows"

    # ...and the same tick DOES work once expanded, so the assertion above is
    # measuring the guard rather than a tick that never worked at all.
    sec.is_collapsed = False
    sec._tick()
    assert row.time_lbl.text() != "30m left", "the tick does not reach the rows"


# ── the boundary timer keeps MEMBERSHIP true ────────────────────────────
def _group(stop_or_start):
    return {"k": {"live": [(0, "x", "ORF", "cid", stop_or_start)],
                  "upcoming": [], "title": "T"}}


def test_a_boundary_timer_is_aimed_at_the_next_change(qapp, tmp_path, monkeypatch):
    """Not a poll: one shot, at the instant the list actually changes."""
    # _schedule_boundary lives in the EPG group module since the split, so
    # that is where it reads _now_utc from — patching the section's own
    # module would set an attribute nothing consults.
    import metatv.gui.sidebar.alerts_epg as mod
    sec = WatchAlertsSection(Config(config_dir=tmp_path), db=None)
    monkeypatch.setattr(mod, "_now_utc", lambda: NOW)

    sec._schedule_boundary(_group(NOW + timedelta(minutes=5)), {})
    t = sec.__dict__.get("_boundary")
    assert t is not None, "no boundary timer was scheduled"
    assert t.isSingleShot(), "a repeating timer here would be a poll"
    # ~5 minutes out, plus the deliberate 1s cushion.
    assert 300_000 <= t.interval() <= 302_000


def test_boundaries_already_past_schedule_nothing(qapp, tmp_path, monkeypatch):
    # _schedule_boundary lives in the EPG group module since the split, so
    # that is where it reads _now_utc from — patching the section's own
    # module would set an attribute nothing consults.
    import metatv.gui.sidebar.alerts_epg as mod
    sec = WatchAlertsSection(Config(config_dir=tmp_path), db=None)
    monkeypatch.setattr(mod, "_now_utc", lambda: NOW)
    sec._schedule_boundary(_group(NOW - timedelta(minutes=5)), {})
    t = sec.__dict__.get("_boundary")
    assert t is None or not t.isActive()


def test_the_earliest_boundary_wins(qapp, tmp_path, monkeypatch):
    """Several rows, one timer — aimed at whichever changes first."""
    # _schedule_boundary lives in the EPG group module since the split, so
    # that is where it reads _now_utc from — patching the section's own
    # module would set an attribute nothing consults.
    import metatv.gui.sidebar.alerts_epg as mod
    sec = WatchAlertsSection(Config(config_dir=tmp_path), db=None)
    monkeypatch.setattr(mod, "_now_utc", lambda: NOW)
    groups = {"k": {"live": [(0, "x", "A", "1", NOW + timedelta(minutes=40)),
                             (0, "x", "B", "2", NOW + timedelta(minutes=7))],
                    "upcoming": [], "title": "T"}}
    sec._schedule_boundary(groups, {})
    assert 420_000 <= sec._boundary.interval() <= 422_000
