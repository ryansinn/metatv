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


# ---------------------------------------------------------------------------
# Turning a DEFAULT off does nothing to someone who already stored the old one
# ---------------------------------------------------------------------------

def _load_config_with(tmp_path, monkeypatch, stored: dict):
    """Load a Config from a real config.yaml containing *stored*.

    Goes through ``Config.load()`` and a patched HOME rather than
    ``Config(**stored)``: the constructor skips the YAML path entirely, and the
    whole defect here lives in what happens to a value that came OFF DISK.
    ``database_url`` is always present because ``load()`` treats a config
    without one as corrupt and silently builds a fresh default — which made the
    first version of this test pass for the wrong reason, with every case
    returning the defaults it was supposed to be overriding.
    """
    import pathlib

    import yaml

    from metatv.core.config import Config

    home = tmp_path / "home"
    (home / ".config" / "metatv").mkdir(parents=True, exist_ok=True)
    (home / ".config" / "metatv" / "config.yaml").write_text(
        yaml.safe_dump({"database_url": "sqlite:///x.db", **stored}))
    monkeypatch.setattr(pathlib.Path, "home", staticmethod(lambda: home))
    cfg, _ = Config.load()
    return cfg


def test_a_stored_old_default_is_turned_off_not_left_alone(tmp_path, monkeypatch):
    """The owner's actual config, and the reason this migration exists.

    Their ``config.yaml`` carries ``tmdb_enrichment_session_cap: 500``
    explicitly, because ``save()`` writes every field. An explicit stored value
    beats any default, so moving the default to 0 left the genre backfill
    running — they watched it log ``filled 40 of 40 movie(s)`` every ~6 s while
    reading a PR whose whole subject was turning it off.
    """
    cfg = _load_config_with(tmp_path, monkeypatch, {
        "tmdb_enrichment_session_cap": 500,
        "series_monitor_interval_minutes": 0,
    })
    assert cfg.tmdb_enrichment_session_cap == 0, (
        "a stored 500 survived — the new default never reaches an existing "
        "config, which is the entire defect this migration fixes")
    assert cfg.background_polling_off_version == 1


def test_a_deliberately_chosen_value_is_preserved(tmp_path, monkeypatch):
    """The conservative half. Only a value EQUAL to the old default is rewritten.

    500 and 1440 are provably "the old default, written down by save()".
    Anything else is a number a person typed, and this migration must not
    touch it — a migration that flattens real choices is worse than the bug.
    """
    cfg = _load_config_with(tmp_path, monkeypatch, {
        "tmdb_enrichment_session_cap": 250,
        "series_monitor_interval_minutes": 720,
    })
    assert cfg.tmdb_enrichment_session_cap == 250
    assert cfg.series_monitor_interval_minutes == 720


def test_turning_polling_back_on_survives_the_next_launch(tmp_path, monkeypatch):
    """Version-gated, so re-enabling sticks.

    Without the marker this would re-run every launch and silently undo the
    user's choice — the trap the metadata-providers migration's version field
    was added to avoid.
    """
    cfg = _load_config_with(tmp_path, monkeypatch, {
        "tmdb_enrichment_session_cap": 500,
        "series_monitor_interval_minutes": 1440,
        "background_polling_off_version": 1,
    })
    assert cfg.tmdb_enrichment_session_cap == 500
    assert cfg.series_monitor_interval_minutes == 1440
