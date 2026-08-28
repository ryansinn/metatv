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


# ── the clock tick must survive a tree the notice path cleared ──────────────
#
# Owner crash, 2026-08-28: SIGABRT out of the 30-second tick.
#
#   _tick -> _refresh_upcoming_tail -> _upcoming_heading -> itemWidget
#   RuntimeError: wrapped C/C++ object of type QTreeWidgetItem has been deleted
#
# QTreeWidget.clear() destroys the C++ items while the Python references we
# tracked stay alive and dangling, and touching one raises RuntimeError — NOT
# AttributeError — so the `is None` guard in _upcoming_heading walks straight
# past it. _populate_rows reset those references; the notice path (loading,
# error, nothing-airing) cleared WITHOUT rebuilding and left them.


def _section(tmp_path):
    return WatchAlertsSection(Config(config_dir=tmp_path), db=None)


def _upcoming_payload():
    """One upcoming-only programme — enough to build the heading + a row."""
    from metatv.gui.sidebar.alerts_epg import _Airing

    start = NOW + timedelta(minutes=5)
    return {
        "live_groups": {},
        "upcoming_only": {
            "k": {
                "title": "T",
                "airings": [_Airing(start.timestamp(), "12:05", "ORF",
                                    "cid", start, None, None, None)],
            }
        },
    }


def test_the_clock_tick_survives_a_notice_render(qapp, tmp_path):
    """The reported crash, end to end: populate, show a notice, then tick."""
    sec = _section(tmp_path)
    sec._populate_rows(_upcoming_payload())
    # A load failure (or "Nothing airing", or the loading row) clears the tree.
    sec.show_load_error(sec.alerts_tree, "boom")

    # 30 seconds later the clock fires. This raised RuntimeError and aborted.
    sec._tick()


def test_a_notice_render_drops_the_tracked_item_references(qapp, tmp_path):
    """The mechanism, asserted directly: nothing dangling survives the clear."""
    sec = _section(tmp_path)
    sec._populate_rows(_upcoming_payload())
    sec.show_loading(sec.alerts_tree)

    assert sec.__dict__.get("_upcoming_heading_item") is None, (
        "the heading item was destroyed by clear() but still referenced"
    )
    assert not sec.__dict__.get("_upcoming_items"), (
        "row items were destroyed by clear() but still referenced"
    )
    assert sec._upcoming_heading() is None, "reading it back must be safe"


def test_every_clear_goes_through_one_forget():
    """A future clear() cannot forget to invalidate what it destroys.

    The bug was a second clear site that did not repeat the reset. Derived, so
    a third one fails here rather than at a user's 30-second tick.
    """
    import ast
    import inspect
    from metatv.gui.sidebar import alerts_epg

    tree = ast.parse(inspect.getsource(alerts_epg))
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        clears = [
            n for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "clear"
        ]
        if not clears:
            continue
        calls = {
            n.func.attr for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        assert "_forget_tracked_items" in calls, (
            f"{fn.name}() clears a tree without dropping the item references "
            "it invalidates — call self._forget_tracked_items() first"
        )
