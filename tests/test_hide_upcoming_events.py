""""Hide live events that start more than [N] [unit] in the future" (owner, 2026-11-01).

(a) An empty event slot ("(Victory+ 002) |  (2098-12-31 08:00:01)") stores its
    sentinel start at ingestion; a named event on the sentinel does not.
(b) The rule hides a slot starting beyond the threshold and the empty slots,
    keeps one starting sooner. On by default with each source's refresh cycle
    (weekly → 7 days; a manual source → 24 hours).
(c) The dialog row saves the checkbox, the number and the unit, greys the
    number out for "source refresh cycle", and "Sync to source refresh" resets.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from metatv.core.config import Config
from metatv.core.database import ChannelDB
from metatv.core.epg_utils import now_utc
from metatv.core.event_datetime import placeholder_slot_start
from metatv.core.special_content import update_channel_special_content
from metatv.core.tag_exclusions import (
    excluded_channel_ids,
    excluded_tag_content_types,
    tag_content_type_exclusion_criterion,
)


# ── (a) Ingestion ─────────────────────────────────────────────────────────────


def test_empty_slot_stores_its_sentinel_start():
    assert placeholder_slot_start("(Victory+ 002) |  (2098-12-31 08:00:01)") == datetime(2098, 12, 31, 8, 0)
    ch = ChannelDB(id="x", source_id="x", provider_id="p", media_type="live",
                   name="(Apple) (MLS) 026 |  (2098-12-31 08:00:01)")
    update_channel_special_content(ch)
    assert ch.event_start_time == datetime(2098, 12, 31, 8, 0)


def test_named_event_on_the_sentinel_is_not_a_placeholder():
    assert placeholder_slot_start("(Victory+ 002) | Big Game (2098-12-31 08:00:01)") is None
    assert placeholder_slot_start("(Victory+ 002) |  (2026-12-31 08:00:01)") is None, "a real date is not a sentinel"


# ── (b) The rule ──────────────────────────────────────────────────────────────


@pytest.fixture
def slots(file_db):
    from metatv.core.database import ProviderDB

    now = now_utc()
    rows = {"soon": ("weekly", now + timedelta(hours=3)), "in3d": ("weekly", now + timedelta(days=3)),
            "in8d": ("weekly", now + timedelta(days=8)), "empty": ("weekly", datetime(2098, 12, 31, 8, 0)),
            "rack": ("weekly", None), "manual_2d": ("manual", now + timedelta(days=2)),
            "manual_3h": ("manual", now + timedelta(hours=3))}
    ids = {}
    with file_db.session_scope() as s:
        for pid in ("weekly", "manual"):
            s.add(ProviderDB(id=pid, name=pid, type="xtream", url=f"http://{pid}.example",
                             is_active=True, refresh_schedule=pid))
        for key, (pid, start) in rows.items():
            cid = str(uuid.uuid4())
            s.add(ChannelDB(id=cid, source_id=cid, provider_id=pid, name=key, media_type="live",
                            event_start_time=start))
            ids[key] = cid
    return ids, file_db


def _visible(db, slugs):
    with db.session_scope() as s:
        return {c for (c,) in s.query(ChannelDB.id).filter(
            tag_content_type_exclusion_criterion(slugs, ChannelDB.channel_key)).all()}


def test_on_by_default_with_each_sources_refresh_cycle(slots):
    ids, db = slots
    cfg = Config()
    assert cfg.hide_upcoming_events and cfg.upcoming_events_unit == "refresh"
    slugs = excluded_tag_content_types(cfg)
    visible = _visible(db, slugs)
    assert {ids["soon"], ids["in3d"], ids["rack"], ids["manual_3h"]} <= visible, \
        "within the weekly cycle / the 24h manual fallback, and undated channels, stay"
    assert ids["in8d"] not in visible, "past a weekly source's next refresh"
    assert ids["manual_2d"] not in visible, "a manual source falls back to 24 hours"
    assert ids["empty"] not in visible, "an empty slot is always beyond the cycle"
    with db.session_scope() as s:
        assert excluded_channel_ids(s, slugs) == {ids["in8d"], ids["manual_2d"], ids["empty"]}


def test_threshold_is_the_sources_next_scheduled_refresh(file_db):
    """Weekly source refreshed 5 days ago → next refresh in 2 days: a game in
    1 day stays, one in 3 days (after the refresh re-reads it) hides."""
    from metatv.core.database import ProviderDB
    from metatv.core.tag_exclusions import next_refresh_times

    now = now_utc()
    with file_db.session_scope() as s:
        s.add(ProviderDB(id="w", name="Weekly", type="xtream", url="http://w.example", is_active=True,
                         refresh_schedule="weekly", last_catalog_refresh_at=now - timedelta(days=5)))
        ids = {}
        for key, ahead in (("in1d", timedelta(days=1)), ("in3d", timedelta(days=3))):
            cid = str(uuid.uuid4())
            s.add(ChannelDB(id=cid, source_id=cid, provider_id="w", name=key, media_type="live",
                            event_start_time=now + ahead))
            ids[key] = cid
    visible = _visible(file_db, excluded_tag_content_types(Config()))
    assert ids["in1d"] in visible and ids["in3d"] not in visible
    with file_db.session_scope() as s:
        ((name, nxt),) = next_refresh_times(s, now)
    assert name == "Weekly" and abs((nxt - (now + timedelta(days=2))).total_seconds()) < 5


def test_a_fixed_threshold_overrides_the_cycle(slots):
    ids, db = slots
    visible = _visible(db, excluded_tag_content_types(
        Config(upcoming_events_amount=24, upcoming_events_unit="hours")))
    assert ids["in3d"] not in visible and ids["soon"] in visible


def test_unchecked_hides_nothing_upcoming(slots):
    ids, db = slots
    assert set(ids.values()) <= _visible(db, excluded_tag_content_types(Config(hide_upcoming_events=False)))


# ── (c) Dialog row ────────────────────────────────────────────────────────────


def test_toggle_row_saves_greys_out_and_syncs(qtbot):
    from metatv.gui.exclusion_sections import ExclusionToggles

    cfg = Config()
    w = ExclusionToggles(cfg)   # no database: no next-refresh text, nothing breaks
    qtbot.addWidget(w)
    w.show()
    assert w.next_refresh.text() == "" and not w.next_refresh.isVisible()
    assert w.upcoming.text() == "Hide live events that start"
    assert w.unit.currentText() == "after the next source refresh"
    assert not w.amount.isVisible() and not w.more_than.isVisible(), "the refresh needs no number"
    assert not w.sync_link.isVisible(), "nothing to sync back to yet"
    w.unit.setCurrentIndex(w.unit.findData("days"))
    w.amount.setValue(2)
    assert w.amount.isVisible() and w.more_than.isVisible() and w.in_future.isVisible()
    assert w.sync_link.isVisible()
    w.save(cfg)
    assert (cfg.upcoming_events_amount, cfg.upcoming_events_unit) == (2, "days")
    w.sync_link.linkActivated.emit("#")
    assert w.unit.currentData() == "refresh" and not w.sync_link.isVisible()
    assert not w.amount.isVisible()
    w.upcoming.setChecked(False)
    assert not w.unit.isEnabled()
    w.save(cfg)
    assert cfg.hide_upcoming_events is False and cfg.upcoming_events_unit == "refresh"


def test_row_shows_the_next_refresh_as_a_date_and_time(file_db, qtbot):
    from metatv.core.database import ProviderDB
    from metatv.gui.exclusion_sections import ExclusionToggles

    with file_db.session_scope() as s:
        s.add(ProviderDB(id="w", name="Weekly", type="xtream", url="http://w.example", is_active=True,
                         refresh_schedule="weekly", last_catalog_refresh_at=now_utc() - timedelta(days=5)))
    w = ExclusionToggles(Config(), file_db)
    qtbot.addWidget(w)
    w.show()
    assert w.next_refresh.text().startswith("(next refresh ") and w.next_refresh.isVisible()
    row = w.upcoming.geometry()
    assert w.next_refresh.geometry().left() > row.right(), "drawn on the same line, after the choice"
    w.unit.setCurrentIndex(w.unit.findData("hours"))
    assert not w.next_refresh.isVisible(), "a fixed amount has no refresh to name"
