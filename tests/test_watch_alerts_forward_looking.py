"""A watch-for rule alerts on what APPEARS, not on the whole existing catalogue.

Owner, 2026-09-09:

> I thought the watch alert matches are to be forward looking, refreshes, new
> episodes, new content, not a search result match of existing content. Because
> watch alert add [movie or series] seems to just act like a perpetual search
> result match now.

The app's own UI already promised this — ``WatchForDialog`` is headed "Watch for
new content" and its hint reads "You'll be alerted when matching content — or a
new episode of a monitored series — APPEARS on any of your sources" — and the
monitored-series half has always worked that way (``series_monitor.set_baseline``
runs the moment a series is monitored, so "new episodes" means new since then).
Keyword rules had no equivalent step, so a new rule fired on the entire
catalogue: the owner's "Evil Dead" rule matched 102 existing rows (~8 distinct
titles across languages and providers), each one a toast, a full config write
and a UI-thread refresh — measured at 26s of UI freeze across 9 stalls, worst
11,666ms.

Uses the REAL ``Config`` on a tmp_path file, never a stub that reimplements the
methods under test (CLAUDE.md).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from metatv.core.config import Config


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rule(text="Evil Dead", created=None) -> dict:
    return {
        "created": created or _now_iso(),
        "text": text,
        "match_type": "any",
        "alerted_ids": [],
        "viewed_ids": [],
    }


@pytest.fixture()
def cfg(tmp_path):
    return Config(config_dir=tmp_path)


# ---------------------------------------------------------------------------
# Baselining: existing content is the rule's starting point, not news
# ---------------------------------------------------------------------------

def test_baseline_records_existing_matches_as_already_seen(cfg):
    """Baselined ids are alerted (so they never re-fire) AND viewed (so no badge)."""
    rule = _rule()
    cfg.add_vod_watch_alert(rule)
    rid = rule["created"]

    n = cfg.baseline_vod_alert_matches(rid, ["ch1", "ch2", "ch3"])

    assert n == 3
    stored = cfg.get_vod_watch_alerts()[0]
    assert set(stored["alerted_ids"]) == {"ch1", "ch2", "ch3"}, \
        "baselined ids must be in alerted_ids or the rule will alert on them later"
    assert set(stored["viewed_ids"]) == {"ch1", "ch2", "ch3"}, \
        "baselined ids must be viewed or the rule badges the whole back catalogue"
    assert cfg.get_unviewed_vod_match_count() == 0, \
        "a freshly-created rule must report nothing new"


def test_baseline_survives_a_reload_from_disk(cfg, tmp_path):
    """The baseline is persisted, not just held in memory.

    Reads the written YAML back directly: ``Config(config_dir=...)`` constructs
    defaults, it does not load — ``Config.load()`` is the loader and it resolves
    its own path from home, which the autouse isolation fixture has already
    redirected elsewhere.
    """
    import yaml

    rule = _rule()
    cfg.add_vod_watch_alert(rule)
    cfg.baseline_vod_alert_matches(rule["created"], ["ch1", "ch2"])

    written = yaml.safe_load((tmp_path / "config.yaml").read_text())
    stored = written["vod_watch_alerts"][0]
    assert set(stored["alerted_ids"]) == {"ch1", "ch2"}
    assert set(stored["viewed_ids"]) == {"ch1", "ch2"}


def test_content_appearing_after_the_baseline_still_alerts(cfg):
    """The point of the whole thing: NEW content is still news."""
    rule = _rule()
    cfg.add_vod_watch_alert(rule)
    rid = rule["created"]
    cfg.baseline_vod_alert_matches(rid, ["old1", "old2"])
    assert cfg.get_unviewed_vod_match_count() == 0

    # A later scan finds a title that was not there when the rule was written.
    cfg.record_vod_alert_match(rid, "brand_new")

    assert cfg.get_unviewed_vod_match_count() == 1
    assert cfg.is_vod_match_unviewed("brand_new") is True
    assert cfg.is_vod_match_unviewed("old1") is False


def test_baseline_is_idempotent_and_never_duplicates(cfg):
    """Re-baselining the same ids must not grow the lists."""
    rule = _rule()
    cfg.add_vod_watch_alert(rule)
    rid = rule["created"]
    cfg.baseline_vod_alert_matches(rid, ["ch1", "ch2"])
    cfg.baseline_vod_alert_matches(rid, ["ch1", "ch2", "ch3"])

    stored = cfg.get_vod_watch_alerts()[0]
    assert sorted(stored["alerted_ids"]) == ["ch1", "ch2", "ch3"]
    assert sorted(stored["viewed_ids"]) == ["ch1", "ch2", "ch3"]


def test_baseline_writes_the_config_once(cfg, monkeypatch):
    """One save for the whole set, not one per match.

    The per-match record-and-save loop cost 102 full config writes for a single
    rule on the owner's library.
    """
    saves = []
    monkeypatch.setattr(type(cfg), "save", lambda self: saves.append(1))

    rule = _rule()
    cfg.vod_watch_alerts = [rule]
    cfg.baseline_vod_alert_matches(rule["created"], [f"ch{i}" for i in range(102)])

    assert len(saves) == 1, f"expected one save for 102 ids, got {len(saves)}"


def test_baseline_with_no_matches_does_not_write(cfg, monkeypatch):
    """A rule matching nothing yet is not a reason to touch the config file."""
    saves = []
    monkeypatch.setattr(type(cfg), "save", lambda self: saves.append(1))

    rule = _rule()
    cfg.vod_watch_alerts = [rule]
    assert cfg.baseline_vod_alert_matches(rule["created"], []) == 0
    assert saves == []


# ---------------------------------------------------------------------------
# Removing a rule takes its matches with it
# ---------------------------------------------------------------------------

def test_removing_a_rule_removes_its_matches_from_every_count(cfg):
    """The storage half of the owner's report.

    The ROUTING half — that every surface showing those matches is told to
    re-read — is enforced by tests/test_alert_mutations_use_composite_refresh.py.
    """
    rule = _rule()
    cfg.add_vod_watch_alert(rule)
    rid = rule["created"]
    cfg.record_vod_alert_match(rid, "ch1")
    cfg.record_vod_alert_match(rid, "ch2")
    assert cfg.get_unviewed_vod_match_count() == 2

    cfg.remove_vod_watch_alert(rid)

    assert cfg.get_vod_watch_alerts() == []
    assert cfg.get_unviewed_vod_match_count() == 0
    assert cfg.get_unviewed_vod_match_ids() == set() or \
        list(cfg.get_unviewed_vod_match_ids()) == []
    assert cfg.is_vod_match_unviewed("ch1") is False
