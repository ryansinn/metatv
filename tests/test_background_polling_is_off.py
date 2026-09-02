"""Speculative background work against the source is OFF unless asked for.

Owner, after a day of diagnosing it: *"everything they solve was already solved
with a single click refresh (or the automated schedule for source refresh, which
arguably is WAY more efficient)"* — and, measured against their own log:

    one full source refresh    1 request     ~34 s      the entire catalog
    one series-monitor pass    234 requests  3.9-39 min all "unchanged"

234 because a pass asks per SERIES PER MIRROR and their 11 watched shows expand
to 234 mirror entries. That is **7x to 69x** the provider connection-time of the
refresh that answers the same question, on sources reporting
``max_connections=1``.

Three defaults, pinned here so none of them drifts back on:

* the series monitor (this file),
* the eager genre backfill (501,030 movies at 500 a launch — ~1,002 launches),
* the signal check (already off in #651, asserted here so all three live
  together and a future change has one place to fail).
"""

from __future__ import annotations

from metatv.core.config import Config


def test_series_polling_is_off_by_default():
    assert Config().series_monitor_interval_minutes == 0, (
        "series polling is back on by default — a pass is 234 provider requests "
        "where a full source refresh is 1")


def test_the_eager_genre_backfill_is_off_by_default():
    assert Config().tmdb_enrichment_session_cap == 0, (
        "the genre drain is back on by default — 501,030 movies at 500 a launch. "
        "The lazy on-open path already covers anything the user actually views")


def test_the_signal_check_is_off_by_default():
    assert Config().signal_check_enabled is False


def test_the_interval_governs_the_startup_pass_not_just_the_timer():
    """The defect the owner actually hit.

    ``start_scheduler`` always honoured the interval; the STARTUP pass did not,
    so setting Never left a full pass running on every launch. The source
    comment even said so and the behaviour stayed — which is why this reads the
    code rather than trusting the comment.

    Reads the FILE rather than a named method, and matches the scheduling call
    rather than the identifier. Two earlier drafts failed on exactly that
    coupling: one matched the mention in a docstring, the next used
    ``inspect.getsource`` on the method whose docstring it was — not the one
    containing the call. Both were caught by running them.
    """
    from pathlib import Path as _P

    import metatv.gui.main_window as mw

    lines = _P(mw.__file__).read_text(encoding="utf-8").splitlines()
    idx = [i for i, l in enumerate(lines)
           if "self.series_monitor.check_all" in l and "singleShot" in "".join(
               lines[max(0, i - 2):i + 1])]
    assert idx, ("no scheduled series_monitor.check_all found — the startup "
                 "pass moved and this guard needs re-pointing")

    for i in idx:
        window = "\n".join(lines[max(0, i - 8):i])
        assert "series_monitor_interval_minutes" in window, (
            "a series-monitor startup pass is scheduled without consulting the "
            "interval — setting it to Never will silently still poll on every "
            f"launch (line {i + 1})")


def test_start_scheduler_still_honours_zero():
    """Non-degeneracy: the recurring half must still be gated too."""
    import inspect

    from metatv.core.series_monitor import SeriesMonitorManager

    src = inspect.getsource(SeriesMonitorManager.start_scheduler)
    assert "minutes <= 0" in src, "the recurring recheck lost its off switch"
