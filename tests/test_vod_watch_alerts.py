"""Behavioral tests for the VOD Watch-Alert feature.

Covers:
- Config helpers: add/remove/record_match/get_matches round-trip.
- VodWatchAlertManager._worker_check_rules: fires _notify_match for new matches,
  skips already-alerted ids, skips channels filtered by media_type gate.
- VodWatchAlertManager._on_new_match: persists the alert + shows a notification.
- _matches_rule logic: media-type gate (movie-rule ignores series), live channels
  always skip, "any" type matches both movie and series.
- WatchAlertsSection.refresh_vod_rules renders active rules correctly.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Minimal Qt fixture (headless)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------------------
# Helpers: minimal Config stub and DB factory
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_label_texts(row) -> list[str]:
    """Return the text of every QLabel in a _VodAlertRow (icon / name / count)."""
    from PyQt6.QtWidgets import QLabel
    return [w.text() for w in row.findChildren(QLabel)]


class _FakeConfig:
    """In-memory Config stub implementing the vod_watch_alerts helpers."""

    def __init__(self):
        self.vod_watch_alerts = []

    def save(self):
        pass  # no-op

    def get_vod_watch_alerts(self) -> list:
        return list(self.vod_watch_alerts)

    def add_vod_watch_alert(self, rule: dict) -> None:
        rule_id = rule.get("created", "")
        if rule_id and any(r.get("created") == rule_id for r in self.vod_watch_alerts):
            return
        self.vod_watch_alerts = list(self.vod_watch_alerts) + [rule]

    def remove_vod_watch_alert(self, rule_created: str) -> None:
        self.vod_watch_alerts = [
            r for r in self.vod_watch_alerts if r.get("created") != rule_created
        ]

    def record_vod_alert_match(self, rule_created: str, channel_id: str) -> None:
        updated = []
        for r in self.vod_watch_alerts:
            if r.get("created") == rule_created:
                merged = dict(r)
                ids = list(merged.get("alerted_ids") or [])
                if channel_id not in ids:
                    ids.append(channel_id)
                merged["alerted_ids"] = ids
                updated.append(merged)
            else:
                updated.append(r)
        self.vod_watch_alerts = updated

    def get_vod_alert_matches(self, rule_created: str) -> list:
        for r in self.vod_watch_alerts:
            if r.get("created") == rule_created:
                return list(r.get("alerted_ids") or [])
        return []

    # Stubs for get_hidden_provider_ids (needed by the manager's worker)
    # delegated via repos; not actually called on Config directly.


def _make_file_backed_db(tmp_path: Path):
    """File-backed Database (not :memory: — each connection would get an empty DB)."""
    from metatv.core.database import Database
    db_path = tmp_path / "test.db"
    db = Database(f"sqlite:///{db_path}")
    db.create_tables()
    return db


def _make_provider(session, provider_id: str = "p1"):
    from metatv.core.database import ProviderDB
    p = ProviderDB(
        id=provider_id,
        name="Test",
        type="xtream",
        url="http://test.example.com",
        urls='[{"url": "http://test.example.com", "primary": true}]',
        username="u",
        password="pw",
        is_active=True,
    )
    session.add(p)
    session.flush()
    return p


def _make_channel(session, channel_id: str = "ch1", name: str = "Dune (2021)",
                  detected_title: str | None = "Dune", media_type: str = "movie",
                  provider_id: str = "p1"):
    from metatv.core.database import ChannelDB
    ch = ChannelDB(
        id=channel_id,
        source_id=channel_id,
        provider_id=provider_id,
        name=name,
        detected_title=detected_title,
        media_type=media_type,
        is_hidden=False,
    )
    session.add(ch)
    session.flush()
    return ch


# ===========================================================================
# Part 1: Config helpers
# ===========================================================================

class TestConfigHelpers:

    def _rule(self, text: str = "Dune", match_type: str = "any") -> dict:
        return {
            "text": text,
            "match_type": match_type,
            "created": _now_iso(),
            "alerted_ids": [],
        }

    def test_add_and_get(self):
        cfg = _FakeConfig()
        rule = self._rule("Dune")
        cfg.add_vod_watch_alert(rule)
        rules = cfg.get_vod_watch_alerts()
        assert len(rules) == 1
        assert rules[0]["text"] == "Dune"

    def test_add_is_idempotent_by_created_key(self):
        cfg = _FakeConfig()
        rule = self._rule("Dune")
        cfg.add_vod_watch_alert(rule)
        cfg.add_vod_watch_alert(rule)  # same created timestamp → no-op
        assert len(cfg.get_vod_watch_alerts()) == 1

    def test_remove_deletes_rule(self):
        cfg = _FakeConfig()
        rule = self._rule("Dune")
        cfg.add_vod_watch_alert(rule)
        cfg.remove_vod_watch_alert(rule["created"])
        assert len(cfg.get_vod_watch_alerts()) == 0

    def test_remove_nonexistent_is_noop(self):
        cfg = _FakeConfig()
        cfg.add_vod_watch_alert(self._rule("Dune"))
        cfg.remove_vod_watch_alert("does_not_exist")
        assert len(cfg.get_vod_watch_alerts()) == 1

    def test_record_match_appends_channel_id(self):
        cfg = _FakeConfig()
        rule = self._rule("Dune")
        cfg.add_vod_watch_alert(rule)
        cfg.record_vod_alert_match(rule["created"], "ch1")
        assert "ch1" in cfg.get_vod_alert_matches(rule["created"])

    def test_record_match_is_deduped(self):
        cfg = _FakeConfig()
        rule = self._rule("Dune")
        cfg.add_vod_watch_alert(rule)
        cfg.record_vod_alert_match(rule["created"], "ch1")
        cfg.record_vod_alert_match(rule["created"], "ch1")  # second call — no-op
        assert cfg.get_vod_alert_matches(rule["created"]).count("ch1") == 1

    def test_record_multiple_matches(self):
        cfg = _FakeConfig()
        rule = self._rule("Star Wars")
        cfg.add_vod_watch_alert(rule)
        cfg.record_vod_alert_match(rule["created"], "ch1")
        cfg.record_vod_alert_match(rule["created"], "ch2")
        matches = cfg.get_vod_alert_matches(rule["created"])
        assert "ch1" in matches
        assert "ch2" in matches

    def test_get_returns_copy(self):
        cfg = _FakeConfig()
        cfg.add_vod_watch_alert(self._rule("Test"))
        lst = cfg.get_vod_watch_alerts()
        lst.clear()
        assert len(cfg.get_vod_watch_alerts()) == 1


# ===========================================================================
# Part 2: _matches_rule logic
# ===========================================================================

class TestMatchesRule:

    def _rule(self, text: str, match_type: str = "any") -> dict:
        return {"text": text, "match_type": match_type, "created": _now_iso(), "alerted_ids": []}

    def test_live_channels_always_skip(self):
        from metatv.core.vod_watch_alert_manager import _matches_rule
        rule = self._rule("CNN", "any")
        assert not _matches_rule("CNN News", "CNN News", "live", rule), \
            "live channels must never match any VOD rule"

    def test_movie_rule_matches_movie(self):
        from metatv.core.vod_watch_alert_manager import _matches_rule
        rule = self._rule("Dune", "movie")
        assert _matches_rule("EN - Dune (2021)", "Dune", "movie", rule)

    def test_movie_rule_ignores_series(self):
        from metatv.core.vod_watch_alert_manager import _matches_rule
        rule = self._rule("Dune", "movie")
        assert not _matches_rule("EN - Dune: Part One S01", "Dune", "series", rule), \
            "movie-typed rule must not match a series channel"

    def test_series_rule_matches_series(self):
        from metatv.core.vod_watch_alert_manager import _matches_rule
        rule = self._rule("Severance", "series")
        assert _matches_rule("EN - Severance S02", "Severance", "series", rule)

    def test_series_rule_ignores_movie(self):
        from metatv.core.vod_watch_alert_manager import _matches_rule
        rule = self._rule("Severance", "series")
        assert not _matches_rule("EN - Severance (2022)", "Severance", "movie", rule), \
            "series-typed rule must not match a movie channel"

    def test_any_matches_movie(self):
        from metatv.core.vod_watch_alert_manager import _matches_rule
        rule = self._rule("Inception", "any")
        assert _matches_rule("Inception (2010)", "Inception", "movie", rule)

    def test_any_matches_series(self):
        from metatv.core.vod_watch_alert_manager import _matches_rule
        rule = self._rule("Inception", "any")
        assert _matches_rule("Inception S01", "Inception", "series", rule)

    def test_case_insensitive_match(self):
        from metatv.core.vod_watch_alert_manager import _matches_rule
        rule = self._rule("DUNE", "any")
        assert _matches_rule("EN - Dune (2021)", "dune", "movie", rule)

    def test_no_match_for_unrelated_title(self):
        from metatv.core.vod_watch_alert_manager import _matches_rule
        rule = self._rule("Dune", "any")
        assert not _matches_rule("Blade Runner 2049", "Blade Runner 2049", "movie", rule)

    def test_falls_back_to_full_name_when_detected_title_is_none(self):
        from metatv.core.vod_watch_alert_manager import _matches_rule
        rule = self._rule("Dune", "any")
        # detected_title is None — matcher should use channel_name
        assert _matches_rule("EN - Dune (2021)", None, "movie", rule)

    def test_empty_keyword_never_matches(self):
        from metatv.core.vod_watch_alert_manager import _matches_rule
        rule = {"text": "", "match_type": "any", "created": _now_iso(), "alerted_ids": []}
        assert not _matches_rule("Dune (2021)", "Dune", "movie", rule)


# ===========================================================================
# Part 3: VodWatchAlertManager worker + main-thread slot
# ===========================================================================

class TestVodWatchAlertManagerWorker:

    def test_worker_emits_notify_for_new_match(self, tmp_path):
        """Worker emits _notify_match when a channel matches and is not yet alerted."""
        from PyQt6.QtCore import QCoreApplication
        from metatv.core.vod_watch_alert_manager import VodWatchAlertManager

        db = _make_file_backed_db(tmp_path)
        cfg = _FakeConfig()
        rule = {
            "text": "Dune",
            "match_type": "movie",
            "created": _now_iso(),
            "alerted_ids": [],
        }
        cfg.add_vod_watch_alert(rule)

        with db.session_scope() as session:
            _make_provider(session, "p1")
            _make_channel(session, "ch1", "EN - Dune (2021)", "Dune", "movie", "p1")

        fired: list[tuple] = []
        manager = VodWatchAlertManager(db, cfg, notifications=None)
        manager._notify_match.connect(
            lambda rc, cid, cname, rt: fired.append((rc, cid, cname, rt))
        )

        manager._worker_check_rules(cfg.get_vod_watch_alerts())
        if QCoreApplication.instance():
            QCoreApplication.instance().processEvents()

        assert len(fired) == 1
        _rc, cid, cname, rt = fired[0]
        assert cid == "ch1"
        assert "Dune" in cname
        assert rt == "Dune"

        manager.shutdown()

    def test_worker_skips_already_alerted_channel(self, tmp_path):
        """Worker does NOT emit _notify_match for a channel already in alerted_ids."""
        from PyQt6.QtCore import QCoreApplication
        from metatv.core.vod_watch_alert_manager import VodWatchAlertManager

        db = _make_file_backed_db(tmp_path)
        cfg = _FakeConfig()
        rule = {
            "text": "Dune",
            "match_type": "any",
            "created": _now_iso(),
            "alerted_ids": ["ch1"],  # already alerted
        }
        cfg.add_vod_watch_alert(rule)

        with db.session_scope() as session:
            _make_provider(session, "p1")
            _make_channel(session, "ch1", "EN - Dune (2021)", "Dune", "movie", "p1")

        fired: list = []
        manager = VodWatchAlertManager(db, cfg, notifications=None)
        manager._notify_match.connect(lambda *a: fired.append(a))

        manager._worker_check_rules(cfg.get_vod_watch_alerts())
        if QCoreApplication.instance():
            QCoreApplication.instance().processEvents()

        assert len(fired) == 0, \
            "Already-alerted channel must NOT produce a second notification"

        manager.shutdown()

    def test_worker_skips_live_channels(self, tmp_path):
        """Worker does not match live channels regardless of keyword match."""
        from PyQt6.QtCore import QCoreApplication
        from metatv.core.vod_watch_alert_manager import VodWatchAlertManager

        db = _make_file_backed_db(tmp_path)
        cfg = _FakeConfig()
        rule = {
            "text": "CNN",
            "match_type": "any",
            "created": _now_iso(),
            "alerted_ids": [],
        }
        cfg.add_vod_watch_alert(rule)

        with db.session_scope() as session:
            _make_provider(session, "p1")
            # The DB query filters on media_type IN ('movie', 'series'), so live
            # channels are excluded at the SQL level — make a live channel.
            _make_channel(session, "ch1", "CNN News", "CNN News", "live", "p1")

        fired: list = []
        manager = VodWatchAlertManager(db, cfg, notifications=None)
        manager._notify_match.connect(lambda *a: fired.append(a))

        manager._worker_check_rules(cfg.get_vod_watch_alerts())
        if QCoreApplication.instance():
            QCoreApplication.instance().processEvents()

        assert len(fired) == 0, "Live channels must never be matched by VOD rules"

        manager.shutdown()

    def test_worker_movie_rule_ignores_series_channel(self, tmp_path):
        """A movie-typed rule must not produce an alert for a series channel."""
        from PyQt6.QtCore import QCoreApplication
        from metatv.core.vod_watch_alert_manager import VodWatchAlertManager

        db = _make_file_backed_db(tmp_path)
        cfg = _FakeConfig()
        rule = {
            "text": "Dune",
            "match_type": "movie",  # movie only
            "created": _now_iso(),
            "alerted_ids": [],
        }
        cfg.add_vod_watch_alert(rule)

        with db.session_scope() as session:
            _make_provider(session, "p1")
            _make_channel(session, "ch1", "Dune: The Series", "Dune", "series", "p1")

        fired: list = []
        manager = VodWatchAlertManager(db, cfg, notifications=None)
        manager._notify_match.connect(lambda *a: fired.append(a))

        manager._worker_check_rules(cfg.get_vod_watch_alerts())
        if QCoreApplication.instance():
            QCoreApplication.instance().processEvents()

        assert len(fired) == 0, "movie-typed rule must ignore series channels"

        manager.shutdown()

    def test_on_new_match_persists_and_notifies(self, qapp, tmp_path):
        """_on_new_match records the match in config and calls NotificationManager."""
        from metatv.core.vod_watch_alert_manager import VodWatchAlertManager

        db = _make_file_backed_db(tmp_path)
        cfg = _FakeConfig()
        rule_created = _now_iso()
        cfg.add_vod_watch_alert({
            "text": "Dune",
            "match_type": "any",
            "created": rule_created,
            "alerted_ids": [],
        })

        notif_mock = MagicMock()
        found_signal_args: list = []

        manager = VodWatchAlertManager(db, cfg, notifications=notif_mock)
        manager.new_matches_found.connect(lambda: found_signal_args.append(True))

        # Drive the main-thread slot directly
        manager._on_new_match(rule_created, "ch1", "Dune (2021)", "Dune")

        # Channel id must be recorded in config
        assert "ch1" in cfg.get_vod_alert_matches(rule_created), \
            "Alerted channel_id must be persisted in config"

        # Notification must have been shown
        assert notif_mock.show.called, "NotificationManager.show() must be called"
        call_str = str(notif_mock.show.call_args)
        assert "Dune" in call_str

        # Public signal must have been emitted
        assert found_signal_args, "new_matches_found must emit after a new match"

        manager.shutdown()

    def test_on_new_match_no_duplicate_config_write(self, qapp, tmp_path):
        """Calling _on_new_match twice for the same channel_id only records it once."""
        from metatv.core.vod_watch_alert_manager import VodWatchAlertManager

        db = _make_file_backed_db(tmp_path)
        cfg = _FakeConfig()
        rule_created = _now_iso()
        cfg.add_vod_watch_alert({
            "text": "Dune",
            "match_type": "any",
            "created": rule_created,
            "alerted_ids": [],
        })

        manager = VodWatchAlertManager(db, cfg, notifications=MagicMock())
        manager._on_new_match(rule_created, "ch1", "Dune (2021)", "Dune")
        manager._on_new_match(rule_created, "ch1", "Dune (2021)", "Dune")  # dup

        matches = cfg.get_vod_alert_matches(rule_created)
        assert matches.count("ch1") == 1, "Same channel must appear only once in alerted_ids"

        manager.shutdown()


# ===========================================================================
# Part 3.5: Repository strict id-set filter (alert "show matches")
# ===========================================================================

class TestChannelIdFilter:
    """get_all(channel_ids=...) constrains the visible set to a stored id-set."""

    def test_returns_only_requested_ids(self, tmp_path):
        from metatv.core.repositories import RepositoryFactory
        db = _make_file_backed_db(tmp_path)
        with db.session_scope() as s:
            _make_provider(s)
            for cid, nm in [("c1", "Dune"), ("c2", "Arrival"), ("c3", "Odyssey")]:
                _make_channel(s, channel_id=cid, name=nm, detected_title=nm)
        with db.session_scope(commit=False) as s:
            repo = RepositoryFactory(s).channels
            got = repo.get_all(channel_ids={"c1", "c3"})
            assert sorted(c.id for c in got) == ["c1", "c3"]
            # No filter → all rows; empty set → nothing (never "all").
            assert len(repo.get_all()) == 3
            assert repo.get_all(channel_ids=set()) == []


def _seed_alert_channels(db):
    """pA (active): c1 movie, c3 series; pB (disabled): c2 movie."""
    from metatv.core.database import ProviderDB, ChannelDB
    with db.session_scope() as s:
        s.add(ProviderDB(id="pA", name="Active", type="xtream", url="http://a",
                         urls='[{"url":"http://a","primary":true}]',
                         username="u", password="p", is_active=True))
        s.add(ProviderDB(id="pB", name="Disabled", type="xtream", url="http://b",
                         urls='[{"url":"http://b","primary":true}]',
                         username="u", password="p", is_active=False))
        s.add(ChannelDB(id="c1", provider_id="pA", source_id="c1",
                        name="Dune", media_type="movie", is_hidden=False))
        s.add(ChannelDB(id="c2", provider_id="pB", source_id="c2",
                        name="Dune (disabled source)", media_type="movie", is_hidden=False))
        s.add(ChannelDB(id="c3", provider_id="pA", source_id="c3",
                        name="Dune (series)", media_type="series", is_hidden=False))


class TestIdFilterRevealAll:
    """Gold-bar reveal relaxes SOFT filters only — never the disabled-source gate."""

    def test_reveal_keeps_provider_gate_but_relaxes_soft(self, qapp, tmp_path):
        from metatv.core.repositories import RepositoryFactory
        from metatv.gui.main_window import MainWindow

        db = _make_file_backed_db(tmp_path)
        _seed_alert_channels(db)
        # c2 lives on the DISABLED source; it must stay hidden in BOTH views.
        base = dict(provider_id=None, media_types=["movie"], force_adult_ids=None,
                    invert_prefix_filters=False, include_untagged=True, adult_mode="all",
                    source_categories=None, page_size=1000, hide_watched=False,
                    context_id_filter={"c1", "c2", "c3"})
        with db.session_scope(commit=False) as s:
            repos = RepositoryFactory(s)
            # Default: only c1 (c2 disabled-source, c3 media-type filtered).
            dtos, _dp = MainWindow._query_channels(repos, dict(base, id_filter_show_all=False))
            assert sorted(d.id for d in dtos) == ["c1"]

            # Reveal: soft filters relaxed → c3 comes back, but c2 (disabled source)
            # stays gone — provider-scoping is NEVER relaxed.
            adtos, _ap = MainWindow._query_channels(repos, dict(base, id_filter_show_all=True))
            revealed = sorted(d.id for d in adtos)
            assert "c2" not in revealed, "disabled-source match must NOT be revealed"
            assert revealed == ["c1", "c3"]

    def test_reveal_clears_bar_for_available_set(self, qapp, tmp_path):
        from metatv.core.repositories import RepositoryFactory
        from metatv.gui.main_window import MainWindow

        db = _make_file_backed_db(tmp_path)
        _seed_alert_channels(db)
        # In real use the caller feeds only the AVAILABLE subset ({c1, c3}) — c2 is
        # already gated out.  Default hides c3 (media-type); reveal shows both → bar clears.
        base = dict(provider_id=None, media_types=["movie"], force_adult_ids=None,
                    invert_prefix_filters=False, include_untagged=True, adult_mode="all",
                    source_categories=None, page_size=1000, hide_watched=False,
                    context_id_filter={"c1", "c3"})
        with db.session_scope(commit=False) as s:
            repos = RepositoryFactory(s)
            dtos, dp = MainWindow._query_channels(repos, dict(base, id_filter_show_all=False))
            assert sorted(d.id for d in dtos) == ["c1"]
            assert dp['total_channels'] == 2
            assert dp['filtered_out_count'] == 1, "c3 media-filtered → gold bar shows"

            adtos, ap = MainWindow._query_channels(repos, dict(base, id_filter_show_all=True))
            assert sorted(d.id for d in adtos) == ["c1", "c3"]
            assert ap['total_channels'] == 2
            assert ap['filtered_out_count'] == 0, "reveal shows the available set → bar clears"


class TestFilterAvailableIds:
    """ChannelRepository.filter_available_ids — the re-validation chokepoint."""

    def test_gates_out_disabled_source_and_hidden(self, tmp_path):
        from metatv.core.database import ChannelDB
        from metatv.core.repositories import RepositoryFactory

        db = _make_file_backed_db(tmp_path)
        _seed_alert_channels(db)
        with db.session_scope() as s:
            # A user-hidden channel on the ACTIVE source — also unavailable.
            s.add(ChannelDB(id="c4", provider_id="pA", source_id="c4",
                            name="Dune (hidden)", media_type="movie", is_hidden=True))
        with db.session_scope(commit=False) as s:
            repos = RepositoryFactory(s)
            excluded = set(repos.providers.get_hidden_provider_ids())
            assert "pB" in excluded  # disabled provider is a hidden provider
            avail = repos.channels.filter_available_ids({"c1", "c2", "c3", "c4"}, excluded)
            assert avail == {"c1", "c3"}, "c2 disabled-source, c4 user-hidden → both gated out"
            assert repos.channels.filter_available_ids(set(), excluded) == set()


class TestComputeAlertAvailability:
    """compute_alert_availability derives every count from the AVAILABLE subset only."""

    def test_counts_reflect_available_matches(self, tmp_path):
        from metatv.core.repositories import RepositoryFactory
        from metatv.core.vod_alert_availability import compute_alert_availability

        db = _make_file_backed_db(tmp_path)
        _seed_alert_channels(db)  # pA active: c1, c3 ; pB disabled: c2
        cfg = _FakeConfig()
        # r1: c1 (available) + c2 (disabled source), both unviewed.
        cfg.add_vod_watch_alert({"text": "Dune", "match_type": "movie", "created": "r1",
                                 "alerted_ids": ["c1", "c2"], "viewed_ids": []})
        # r2: only c2 (disabled) → 0 available, NOT firing.
        cfg.add_vod_watch_alert({"text": "Ghost", "match_type": "movie", "created": "r2",
                                 "alerted_ids": ["c2"], "viewed_ids": []})

        with db.session_scope(commit=False) as s:
            avail = compute_alert_availability(cfg, RepositoryFactory(s))

        assert avail.available_ids == frozenset({"c1"})
        assert avail.per_rule_total["r1"] == 1 and avail.per_rule_unviewed["r1"] == 1
        assert avail.per_rule_total["r2"] == 0 and avail.per_rule_unviewed["r2"] == 0
        assert avail.firing_rules == 1, "r2's only match is on a disabled source → not firing"
        assert avail.unviewed_total == 1

    def test_all_on_disabled_source_reports_zero(self, tmp_path):
        from metatv.core.repositories import RepositoryFactory
        from metatv.core.vod_alert_availability import compute_alert_availability

        db = _make_file_backed_db(tmp_path)
        _seed_alert_channels(db)
        cfg = _FakeConfig()
        cfg.add_vod_watch_alert({"text": "Ghost", "match_type": "movie", "created": "r1",
                                 "alerted_ids": ["c2"], "viewed_ids": []})  # c2 = disabled
        with db.session_scope(commit=False) as s:
            avail = compute_alert_availability(cfg, RepositoryFactory(s))
        assert avail.firing_rules == 0
        assert avail.unviewed_total == 0
        assert avail.per_rule_total["r1"] == 0


# ===========================================================================
# Part 4: WatchAlertsSection.refresh_vod_rules rendering
# ===========================================================================

class TestWatchAlertsSectionVodRules:
    """Test that refresh_vod_rules correctly renders active rules."""

    def _make_section(self, config, qapp):
        """Build a minimal WatchAlertsSection-like object with _vod_list only."""
        from PyQt6.QtWidgets import QListWidget

        # Use __new__ + manually patch what refresh_vod_rules needs.
        # We don't instantiate the full section (it needs a real DB) — we verify
        # only the main-thread render path (that's the half that regresses).
        from metatv.gui.sidebar.alerts import WatchAlertsSection

        section = WatchAlertsSection.__new__(WatchAlertsSection)
        section.config = config
        section._vod_collapsed = False
        section._vod_list = QListWidget()
        # Stub the show/hide helpers — they touch real Qt widgets but we just
        # need to validate list content.
        section._vod_hdr_container = MagicMock()
        section._update_vod_toggle_label = MagicMock()
        return section

    def test_no_rules_hides_sub_section(self, qapp):
        cfg = _FakeConfig()
        section = self._make_section(cfg, qapp)
        section.refresh_vod_rules()
        assert section._vod_list.count() == 0, "Empty rule list must leave vod_list empty"
        section._vod_hdr_container.hide.assert_called()

    def test_one_rule_renders_one_item(self, qapp):
        cfg = _FakeConfig()
        cfg.add_vod_watch_alert({
            "text": "Dune",
            "match_type": "movie",
            "created": _now_iso(),
            "alerted_ids": [],
        })
        section = self._make_section(cfg, qapp)
        section.refresh_vod_rules()
        assert section._vod_list.count() == 1, "One rule must render one list item"
        row = section._vod_list.itemWidget(section._vod_list.item(0))
        assert row is not None, "Rule must render as a custom _VodAlertRow widget"
        texts = _row_label_texts(row)
        assert any("Dune" in t for t in texts), f"Rule name must appear in row: {texts!r}"

    def test_match_count_shown_when_nonzero(self, qapp):
        cfg = _FakeConfig()
        created = _now_iso()
        cfg.add_vod_watch_alert({
            "text": "Star Wars",
            "match_type": "any",
            "created": created,
            "alerted_ids": ["ch1", "ch2", "ch3"],  # 3 matches
        })
        section = self._make_section(cfg, qapp)
        section.refresh_vod_rules()
        row = section._vod_list.itemWidget(section._vod_list.item(0))
        texts = _row_label_texts(row)
        assert any("3" in t for t in texts), f"Match count 3 must appear in row: {texts!r}"

    def test_multiple_rules_render_multiple_items(self, qapp):
        cfg = _FakeConfig()
        for title in ("Dune", "Severance", "Inception"):
            cfg.add_vod_watch_alert({
                "text": title,
                "match_type": "any",
                "created": _now_iso(),
                "alerted_ids": [],
            })
        section = self._make_section(cfg, qapp)
        section.refresh_vod_rules()
        assert section._vod_list.count() == 3, "Three rules must produce three rows"

    def test_item_stores_rule_created_in_user_role(self, qapp):
        """Each list item must store rule_created in UserRole so click handlers can look up the rule."""
        from PyQt6.QtCore import Qt
        cfg = _FakeConfig()
        created = _now_iso()
        cfg.add_vod_watch_alert({
            "text": "Dune",
            "match_type": "movie",
            "created": created,
            "alerted_ids": [],
        })
        section = self._make_section(cfg, qapp)
        section.refresh_vod_rules()
        item = section._vod_list.item(0)
        assert item is not None
        assert item.data(Qt.ItemDataRole.UserRole) == created, \
            "UserRole must hold rule_created so the click handler can resolve the rule"


# ===========================================================================
# Part 5: Interactive rule actions — click / context menu / dialog view button
# ===========================================================================

class TestVodRuleInteractiveActions:
    """Test click wiring, context menu, and dialog view-matches button."""

    def _make_section(self, config, qapp):
        """Build a WatchAlertsSection stub with _vod_list + real signals."""
        from PyQt6.QtWidgets import QListWidget
        from metatv.gui.sidebar.alerts import WatchAlertsSection

        section = WatchAlertsSection.__new__(WatchAlertsSection)
        section.config = config
        section._vod_collapsed = False
        section._vod_list = QListWidget()
        section._vod_hdr_container = MagicMock()
        section._update_vod_toggle_label = MagicMock()
        return section

    def test_single_click_emits_rule_created_for_stored_matches(self, qapp):
        """_on_vod_item_clicked emits the rule's created id via vodRuleShowMatchesRequested.

        The click now carries the rule id (not a keyword) so the host shows the
        rule's STORED matched ids.  Using __new__ means the Qt signal isn't
        constructed, so we replace .emit with a MagicMock to capture the argument.
        """
        cfg = _FakeConfig()
        created = _now_iso()
        cfg.add_vod_watch_alert({
            "text": "Severance",
            "match_type": "series",
            "created": created,
            "alerted_ids": [],
        })

        section = self._make_section(cfg, qapp)
        section.refresh_vod_rules()

        section.vodRuleShowMatchesRequested = MagicMock()

        item = section._vod_list.item(0)
        assert item is not None
        section._on_vod_item_clicked(item)

        section.vodRuleShowMatchesRequested.emit.assert_called_once_with(created)

    def test_single_click_any_type(self, qapp):
        """Left-click still routes by rule id for an any-typed rule."""
        cfg = _FakeConfig()
        created = _now_iso()
        cfg.add_vod_watch_alert({
            "text": "Dune",
            "match_type": "any",
            "created": created,
            "alerted_ids": [],
        })

        section = self._make_section(cfg, qapp)
        section.refresh_vod_rules()
        section.vodRuleShowMatchesRequested = MagicMock()

        section._on_vod_item_clicked(section._vod_list.item(0))

        section.vodRuleShowMatchesRequested.emit.assert_called_once_with(created)

    def test_remove_signal_carries_rule_created(self, qapp):
        """vodRuleRemoveRequested emitted via _rule_info_for_created lookup (tested indirectly).

        We verify that _rule_info_for_created returns the correct (text, match_type) for a
        known rule_created value — this is the lookup click handlers depend on.
        """
        cfg = _FakeConfig()
        created = _now_iso()
        cfg.add_vod_watch_alert({
            "text": "Inception",
            "match_type": "movie",
            "created": created,
            "alerted_ids": [],
        })

        section = self._make_section(cfg, qapp)
        text, match_type = section._rule_info_for_created(created)
        assert text == "Inception"
        assert match_type == "movie"

    def test_rule_info_for_unknown_created_returns_empty(self, qapp):
        """_rule_info_for_created returns ('', 'any') for an unrecognised rule_created."""
        cfg = _FakeConfig()
        section = self._make_section(cfg, qapp)
        text, match_type = section._rule_info_for_created("does-not-exist")
        assert text == ""
        assert match_type == "any"

    def test_manage_dialog_view_matches_emits_and_closes(self, qapp):
        """ManageVodAlertsDialog 'View' button emits view_matches_requested and accepts the dialog."""
        from metatv.gui.vod_watch_alert_dialog import ManageVodAlertsDialog

        cfg = _FakeConfig()
        created = _now_iso()
        cfg.add_vod_watch_alert({
            "text": "Blade Runner",
            "match_type": "movie",
            "created": created,
            "alerted_ids": [],
        })

        emitted: list[tuple[str, str]] = []
        dlg = ManageVodAlertsDialog(cfg)
        dlg.view_matches_requested.connect(lambda t, mt: emitted.append((t, mt)))

        # Simulate clicking "View" by calling _view_matches directly
        dlg._view_matches("Blade Runner", "movie")

        assert len(emitted) == 1
        assert emitted[0] == ("Blade Runner", "movie"), \
            "view_matches_requested must carry the rule text and match_type"

    def test_manage_dialog_remove_emits_changed(self, qapp):
        """ManageVodAlertsDialog _remove emits changed and removes the rule from config."""
        from metatv.gui.vod_watch_alert_dialog import ManageVodAlertsDialog

        cfg = _FakeConfig()
        created = _now_iso()
        cfg.add_vod_watch_alert({
            "text": "Arrival",
            "match_type": "movie",
            "created": created,
            "alerted_ids": [],
        })

        changed_calls: list = []
        dlg = ManageVodAlertsDialog(cfg)
        dlg.changed.connect(lambda: changed_calls.append(True))

        dlg._remove(created)

        assert changed_calls, "changed signal must fire after removal"
        assert len(cfg.get_vod_watch_alerts()) == 0, "Rule must be deleted from config"
