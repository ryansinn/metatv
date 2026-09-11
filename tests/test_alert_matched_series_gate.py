"""ALERT-2: a monitored series' "+N eps" counts only LIVE sources, and its
row opens on one — never a disabled/expired source's copy.

Owner report (2026-09-11): Watch Queue -> Alerts Matched showed "President
Curtis +17 eps"; the entry's PRIMARY channel was on "TREX Shared", which had
since expired, and the +17 was counted while it was live. Clicking the row
opened TREX Shared's (dead) copy. The same series was ALSO carried by ProSat
(active), which grew 6->7 tonight — a legitimate +1, not +17 on a dead source.

Covers:
- ``series_monitor_visibility.visible_unseen`` — the one predicate: gated
  count + open-target selection (primary-if-live, else the largest live
  mirror), including the back-compat rule for an entry with no
  ``unseen_by_mirror`` breakdown at all.
- ``SeriesMonitorManager._on_new_episodes`` — per-mirror deltas merge onto a
  running ``unseen_by_mirror`` alongside the existing summed ``unseen_new``;
  mark-seen (``Config.clear_unseen``, via the fake config's mirrored version)
  clears both.
- ``WatchQueueSection._load_rows`` (real DB) — a series primary-hidden entry
  is gated to its live mirror's share and resolves ``_open_channel_id`` to
  that mirror's REAL ``ChannelDB.id``; with every mirror hidden, the row (and
  entry) drops out entirely.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tests.test_series_monitor import _FakeConfig, _make_file_backed_db


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ===========================================================================
# Part 1: visible_unseen — pure gating predicate
# ===========================================================================

def _entry(provider_id="p1", source_id="s1", unseen_new=0, unseen_by_mirror=None,
           has_mirror_field=True) -> dict:
    entry = {
        "series_channel_id": "cid1",
        "provider_id": provider_id,
        "source_id": source_id,
        "unseen_new": unseen_new,
    }
    if has_mirror_field:
        entry["unseen_by_mirror"] = unseen_by_mirror or {}
    return entry


class TestVisibleUnseen:

    def test_primary_live_mirror_hidden_counts_and_opens_only_primary(self):
        from metatv.core.series_monitor import mirror_key
        from metatv.core.series_monitor_visibility import visible_unseen

        primary = mirror_key("p1", "s1")
        mirror = mirror_key("p2", "s2")
        entry = _entry(unseen_by_mirror={primary: 5, mirror: 3})

        count, open_key = visible_unseen(entry, {"p2"})

        assert count == 5, "hidden mirror's share must not be counted"
        assert open_key == primary

    def test_primary_hidden_mirror_live_counts_and_opens_only_mirror(self):
        from metatv.core.series_monitor import mirror_key
        from metatv.core.series_monitor_visibility import visible_unseen

        primary = mirror_key("p1", "s1")
        mirror = mirror_key("p2", "s2")
        entry = _entry(unseen_by_mirror={primary: 5, mirror: 3})

        count, open_key = visible_unseen(entry, {"p1"})

        assert count == 3, "hidden primary's share must not be counted"
        assert open_key == mirror, "must redirect to the live mirror, never the dead primary"

    def test_every_mirror_hidden_drops_out_entirely(self):
        from metatv.core.series_monitor import mirror_key
        from metatv.core.series_monitor_visibility import visible_unseen

        entry = _entry(unseen_by_mirror={
            mirror_key("p1", "s1"): 5, mirror_key("p2", "s2"): 3,
        })

        assert visible_unseen(entry, {"p1", "p2"}) == (0, None)

    def test_legacy_entry_with_hidden_primary_is_fully_gated_out(self):
        """An entry written before unseen_by_mirror existed can only ever be
        attributed to its PRIMARY (the sole mirror ever checked) — if that
        primary is hidden, the whole (unattributable-elsewhere) count is gone."""
        from metatv.core.series_monitor_visibility import visible_unseen

        entry = _entry(unseen_new=17, has_mirror_field=False)

        assert visible_unseen(entry, {"p1"}) == (0, None)

    def test_legacy_entry_with_live_primary_keeps_the_whole_count(self):
        from metatv.core.series_monitor import mirror_key
        from metatv.core.series_monitor_visibility import visible_unseen

        entry = _entry(unseen_new=17, has_mirror_field=False)

        count, open_key = visible_unseen(entry, set())

        assert count == 17
        assert open_key == mirror_key("p1", "s1")


# ===========================================================================
# Part 2: SeriesMonitorManager — per-mirror accounting + mark-seen clearing
# ===========================================================================

class TestMonitorAccounting:

    def test_per_mirror_deltas_merge_and_mark_seen_clears_both(self, qapp, tmp_path):
        from metatv.core.series_monitor import SeriesMonitorManager, mirror_key

        db = _make_file_backed_db(tmp_path)
        cfg = _FakeConfig()
        cfg.add_monitored_series({
            "series_channel_id": "ch1",
            "source_id": "s1",
            "provider_id": "p1",
            "title": "President Curtis",
            "baselines": {},
            "unseen_new": 0,
            "unseen_by_mirror": {},
            "last_checked": None,
        })

        manager = SeriesMonitorManager(db, cfg, notifications=MagicMock())

        key_a = mirror_key("p1", "s1")   # TREX Shared
        key_b = mirror_key("p2", "s2")   # ProSat
        payload = {
            "baselines": {key_a: 17, key_b: 1},
            "grown_provider_names": ["TREX Shared", "ProSat"],
            "unseen_delta_by_mirror": {key_a: 3, key_b: 1},
        }
        manager._on_new_episodes("ch1", 4, "President Curtis", payload)

        entry = cfg.get_monitored_series()[0]
        assert entry["unseen_new"] == 4
        assert entry["unseen_by_mirror"] == {key_a: 3, key_b: 1}

        # A SECOND pass (only key_b grows again) accumulates onto the running
        # per-mirror map, same as unseen_new already did pre-ALERT-2.
        manager._on_new_episodes(
            "ch1", 1, "President Curtis",
            {"baselines": {key_a: 17, key_b: 2}, "grown_provider_names": ["ProSat"],
             "unseen_delta_by_mirror": {key_b: 1}},
        )
        entry = cfg.get_monitored_series()[0]
        assert entry["unseen_new"] == 5
        assert entry["unseen_by_mirror"] == {key_a: 3, key_b: 2}

        cfg.clear_unseen("ch1")
        entry = cfg.get_monitored_series()[0]
        assert entry["unseen_new"] == 0
        assert entry["unseen_by_mirror"] == {}

        manager.shutdown()


# ===========================================================================
# Part 3: WatchQueueSection._load_rows — real DB, real provider visibility
# ===========================================================================

def _make_provider(session, provider_id: str, name: str, *, is_active: bool):
    from metatv.core.database import ProviderDB
    p = ProviderDB(
        id=provider_id, name=name, type="xtream",
        url="http://test.example.com",
        urls='[{"url": "http://test.example.com", "primary": true}]',
        username="u", password="pw", is_active=is_active,
    )
    session.add(p)
    session.flush()
    return p


def _make_series_channel(session, channel_id: str, provider_id: str, source_id: str):
    from metatv.core.database import ChannelDB
    ch = ChannelDB(
        id=channel_id, source_id=source_id, provider_id=provider_id,
        name="President Curtis", media_type="series",
    )
    session.add(ch)
    session.flush()
    return ch


def _monitored_entry(key_a, key_b) -> dict:
    return {
        "series_channel_id": "ch-p1",
        "source_id": "s1",
        "provider_id": "P1",
        "title": "President Curtis",
        "display_title": "President Curtis",
        "baselines": {key_a: 17, key_b: 1},
        "unseen_new": 18,
        "unseen_by_mirror": {key_a: 17, key_b: 1},
        "growth_providers": ["ProSat"],
        "last_checked": None,
    }


class TestQueueSectionGate:

    def test_gated_row_counts_and_opens_the_live_mirror(self, qapp, db, tmp_path):
        from metatv.core.config import Config
        from metatv.core.series_monitor import mirror_key
        from metatv.gui.sidebar.queue import WatchQueueSection

        key_a, key_b = mirror_key("P1", "s1"), mirror_key("P2", "s2")
        with db.session_scope() as s:
            _make_provider(s, "P1", "TREX Shared", is_active=False)  # expired/disabled
            _make_provider(s, "P2", "ProSat", is_active=True)
            _make_series_channel(s, "ch-p1", "P1", "s1")
            ch2 = _make_series_channel(s, "ch-p2", "P2", "s2")
            ch2_id = ch2.id

        cfg = Config(config_dir=tmp_path / "cfg")
        cfg.add_monitored_series(_monitored_entry(key_a, key_b))

        sec = WatchQueueSection.__new__(WatchQueueSection)
        sec.db = db
        sec.config = cfg
        sec._load_rows()

        assert len(sec._alerts_matched_series) == 1, sec._alerts_matched_series
        entry = sec._alerts_matched_series[0]
        assert entry["unseen_new"] == 1, "only ProSat's (live) share counts, not TREX's 17"
        assert entry["_open_channel_id"] == ch2_id, "must open ProSat's real channel row"

        # End-to-end: the actual row built from this entry stores the SAME
        # (live) channel id as its click target, never series_channel_id.
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QListWidget
        sec._list = QListWidget()
        item = sec._add_matched_series_item(entry)
        payload = item.data(Qt.ItemDataRole.UserRole)
        assert payload["channel_id"] == ch2_id
        assert "+1 new ep" in item.toolTip(), item.toolTip()

    def test_every_mirror_hidden_drops_the_row_and_the_count(self, qapp, db, tmp_path):
        from metatv.core.config import Config
        from metatv.core.series_monitor import mirror_key
        from metatv.gui.sidebar.queue import WatchQueueSection

        key_a, key_b = mirror_key("P1", "s1"), mirror_key("P2", "s2")
        with db.session_scope() as s:
            _make_provider(s, "P1", "TREX Shared", is_active=False)
            _make_provider(s, "P2", "ProSat", is_active=False)
            _make_series_channel(s, "ch-p1", "P1", "s1")
            _make_series_channel(s, "ch-p2", "P2", "s2")

        cfg = Config(config_dir=tmp_path / "cfg")
        cfg.add_monitored_series(_monitored_entry(key_a, key_b))

        sec = WatchQueueSection.__new__(WatchQueueSection)
        sec.db = db
        sec.config = cfg
        sec._load_rows()

        assert sec._alerts_matched_series == []
