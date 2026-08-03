"""Regression tests for the #259 series-monitor baseline-accounting bug.

Root cause (owner-reported against a real config.yaml): a flaky provider
fetch that returned no usable ``episodes`` payload (``{}``, missing key, or
a malformed value) was silently recorded as a baseline of 0. The next
successful check then computed ``delta = full_count - 0`` and reported the
ENTIRE catalogue as "new" — repeatedly, since ``unseen_new`` only ever
accumulates and clears on explicit user action. Two real examples from the
owner's config:

    EN - Rick And Morty (2013): unseen_new=320, baselines={91, 41} -> real total 132
    4K-SC - Fallout (2024) (US): unseen_new=256, baselines={15, 8}  -> real total 23
    (256 == 8 * 32 -- the 8-episode provider was counted as new 32 times)

Covers:
- SeriesMonitorManager._worker_check_entries never lowers a stored baseline,
  and skips the baseline write entirely (rather than recording 0) when a
  fetch returns no usable episodes payload. Across a
  full -> empty -> full -> empty -> full check sequence, the baseline never
  decreases and unseen_new never grows. THIS TEST MUST FAIL on the pre-fix
  tree (see PR body for the captured failure).
- Config.get_monitored_series() one-time migration RESETS (not clamps) an
  already-inflated unseen_new to 0 -- a count proven corrupt by exceeding
  its summed baselines carries no recoverable signal, so 0 is the honest
  value. A healthy entry is left completely untouched (same object, no
  rewrite); running the migration twice changes nothing further; no other
  field (favorites/ratings/history/watch progress, or the presence of
  other monitored-series entries) is touched.
- The DIFFERENT, ongoing guard in SeriesMonitorManager._on_new_episodes
  still CLAMPS a fresh write to the summed baselines (never zeroes it) --
  that value isn't proven corrupt, just implausible, so it's conservatively
  capped rather than discarded. This distinction (reset-on-migration vs.
  clamp-on-fresh-write) must not regress either direction.

Uses a real, file-backed Database (NOT :memory: -- project rule for
DB-session work: each connection on :memory: gets a separate empty DB,
which breaks pooled sessions) and a real Config on tmp_path (not a stub),
so the migrate-on-read chokepoint (Config.get_monitored_series) is actually
exercised end-to-end.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# qapp fixture (headless Qt) -- SeriesMonitorManager is a QObject and its
# private signals need a QCoreApplication instance to marshal through.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------------------
# DB helpers (mirrors tests/test_series_monitor.py's file-backed pattern)
# ---------------------------------------------------------------------------

def _make_file_backed_db(tmp_path: Path):
    """Create a file-backed Database with tables (NOT :memory:)."""
    from metatv.core.database import Database
    db_path = tmp_path / "test.db"
    db = Database(f"sqlite:///{db_path}")
    db.create_tables()
    return db


def _make_provider_db(session, provider_id: str = "p1", name: str = "Test Provider"):
    """Insert a minimal ProviderDB row."""
    from metatv.core.database import ProviderDB
    provider = ProviderDB(
        id=provider_id,
        name=name,
        type="xtream",
        url="http://test.example.com",  # NOT NULL in the schema
        urls='[{"url": "http://test.example.com", "primary": true}]',
        username="user",
        password="pass",
        is_active=True,
    )
    session.add(provider)
    session.flush()
    return provider


# ===========================================================================
# Part 1: baseline never decreases, unseen_new never grows from a flaky fetch
# ===========================================================================

class TestBaselineNeverLowersUnseenNeverInflates:
    """Drives SeriesMonitorManager through repeated full/empty/full checks --
    the exact real-world pattern from the bug report (one always-stable
    provider co-existing with a flaky one that intermittently returns an
    empty payload). Must FAIL on the pre-fix tree.
    """

    def test_full_empty_full_cycle_never_inflates(self, tmp_path, qapp):
        from PyQt6.QtCore import QCoreApplication
        from metatv.core.config import Config
        from metatv.core.series_monitor import SeriesMonitorManager

        db = _make_file_backed_db(tmp_path)
        cfg = Config(config_dir=tmp_path / "cfg")
        cfg.monitored_series = [{
            "series_channel_id": "ch1",
            "source_id": "s1",
            "provider_id": "p1",
            "title": "EN - Rick And Morty (2013)",
            "baselines": {},
            "unseen_new": 0,
            "last_checked": None,
        }]

        with db.session_scope() as session:
            _make_provider_db(session, "p1", name="ProSat (Ottcst)")

        FULL = {"episodes": {"1": [{"info": {}} for _ in range(8)]}}  # 8 episodes
        EMPTY_VARIANTS = [{}, {"episodes": {}}, {"episodes": None}, {"nope": True}]

        manager = SeriesMonitorManager(db, cfg, notifications=None)

        def _check(payload):
            with patch("metatv.providers.factory.get_provider") as mock_get_provider, \
                 patch("metatv.core.series_monitor.asyncio.run") as mock_run:
                mock_get_provider.return_value = MagicMock()
                mock_run.return_value = payload
                manager._worker_check_entries(cfg.get_monitored_for_provider("p1"))
                if QCoreApplication.instance():
                    QCoreApplication.processEvents()

        # Check 1: establishes the baseline (prev is None) -- no notify yet.
        _check(FULL)
        entry = cfg.get_monitored_series()[0]
        assert entry["baselines"]["p1"] == 8
        assert entry["unseen_new"] == 0

        max_baseline_seen = 8

        # Repeat the flaky-provider pattern several times: an empty/malformed
        # response, then a full response again. Neither the baseline nor
        # unseen_new may ever regress/inflate across this sequence.
        for i, empty_payload in enumerate(EMPTY_VARIANTS + EMPTY_VARIANTS[:1]):
            _check(empty_payload)
            entry = cfg.get_monitored_series()[0]
            assert entry["baselines"]["p1"] >= max_baseline_seen, (
                f"baseline decreased on empty-payload check #{i} "
                f"({empty_payload!r}): baselines={entry['baselines']}"
            )
            max_baseline_seen = max(max_baseline_seen, entry["baselines"]["p1"])
            assert entry["unseen_new"] == 0, (
                f"unseen_new grew from an empty-payload response on check #{i} "
                f"({empty_payload!r}): unseen_new={entry['unseen_new']}"
            )

            _check(FULL)
            entry = cfg.get_monitored_series()[0]
            assert entry["baselines"]["p1"] == 8, (
                f"baseline drifted away from the real count after cycle #{i}: "
                f"baselines={entry['baselines']}"
            )
            assert entry["unseen_new"] == 0, (
                f"unseen_new grew across a full/empty/full cycle (#{i}) -- this "
                f"is the exact #259 regression (256 == 8 * 32 in the owner's "
                f"real config): unseen_new={entry['unseen_new']}"
            )

        manager.shutdown()

    def test_empty_payload_on_first_check_never_establishes_a_zero_baseline(
        self, tmp_path, qapp
    ):
        """A flaky FIRST check (before any baseline exists) must not establish
        baseline=0 either -- it must skip establishing a baseline at all, so a
        later successful check establishes the real count instead of treating
        the whole catalog as new."""
        from PyQt6.QtCore import QCoreApplication
        from metatv.core.config import Config
        from metatv.core.series_monitor import SeriesMonitorManager

        db = _make_file_backed_db(tmp_path)
        cfg = Config(config_dir=tmp_path / "cfg")
        cfg.monitored_series = [{
            "series_channel_id": "ch1",
            "source_id": "s1",
            "provider_id": "p1",
            "title": "4K-SC - Fallout (2024) (US)",
            "baselines": {},
            "unseen_new": 0,
            "last_checked": None,
        }]

        with db.session_scope() as session:
            _make_provider_db(session, "p1", name="ProSat (Ottcst)")

        manager = SeriesMonitorManager(db, cfg, notifications=None)

        with patch("metatv.providers.factory.get_provider") as mock_get_provider, \
             patch("metatv.core.series_monitor.asyncio.run") as mock_run:
            mock_get_provider.return_value = MagicMock()

            # First check: flaky empty response.
            mock_run.return_value = {}
            manager._worker_check_entries(cfg.get_monitored_for_provider("p1"))
            if QCoreApplication.instance():
                QCoreApplication.processEvents()

            entry = cfg.get_monitored_series()[0]
            assert "p1" not in entry.get("baselines", {}), (
                "an empty/malformed payload must never establish a baseline "
                f"(even a zero one): baselines={entry.get('baselines')}"
            )
            assert entry["unseen_new"] == 0

            # Second check: the provider recovers with the real count (23).
            mock_run.return_value = {"episodes": {"1": [{}] * 23}}
            manager._worker_check_entries(cfg.get_monitored_for_provider("p1"))
            if QCoreApplication.instance():
                QCoreApplication.processEvents()

        entry = cfg.get_monitored_series()[0]
        assert entry["baselines"]["p1"] == 23
        assert entry["unseen_new"] == 0, (
            "establishing a first-ever baseline must never fire an alert for "
            f"the whole back-catalog: unseen_new={entry['unseen_new']}"
        )

        manager.shutdown()


# ===========================================================================
# Part 2: one-time migration RESETS (zeroes) already-inflated unseen_new
# ===========================================================================

class TestUnseenNewZeroOutMigration:
    """Config.get_monitored_series() resets any unseen_new left inflated by
    the #259 bug to 0 -- NOT clamped to the summed baselines -- on first
    read, idempotent, and touching nothing else on the entry or the list.

    A count proven corrupt (unseen_new > summed baselines) carries no
    recoverable signal: there is no way to tell which, if any, of the
    recorded episodes were genuine, and the owner's own report is that NONE
    of the excess was real. 0 is the honest value here, not a guess."""

    def test_absurd_unseen_new_is_reset_to_zero_for_owner_reported_values(
        self, tmp_path
    ):
        """Exact real-config repro: both examples from the bug report reset
        to 0, not to their summed baselines (132 / 23)."""
        from metatv.core.config import Config

        cfg = Config(config_dir=tmp_path / "cfg")
        cfg.monitored_series = [
            {
                "series_channel_id": "rick_and_morty",
                "source_id": "s1",
                "provider_id": "providerA",
                "title": "EN - Rick And Morty (2013)",
                "baselines": {"providerA": 91, "providerB": 41},
                "unseen_new": 320,
                "growth_providers": ["ProSat (Ottcst)"],
                "last_checked": "2026-08-01T00:00:00+00:00",
            },
            {
                "series_channel_id": "fallout",
                "source_id": "s2",
                "provider_id": "providerA",
                "title": "4K-SC - Fallout (2024) (US)",
                "baselines": {"providerA": 15, "providerB": 8},
                "unseen_new": 256,
                "growth_providers": ["ProSat (Ottcst)"],
                "last_checked": "2026-08-01T00:00:00+00:00",
            },
        ]

        result = cfg.get_monitored_series()

        rick = next(e for e in result if e["series_channel_id"] == "rick_and_morty")
        fallout = next(e for e in result if e["series_channel_id"] == "fallout")
        assert rick["unseen_new"] == 0, \
            f"a proven-corrupt count must be RESET to 0, not clamped to the " \
            f"summed baseline (132); got {rick['unseen_new']}"
        assert fallout["unseen_new"] == 0, \
            f"a proven-corrupt count must be RESET to 0, not clamped to the " \
            f"summed baseline (23); got {fallout['unseen_new']}"

        # Written back to the raw stored field, not just the returned copy.
        stored_rick = next(
            e for e in cfg.monitored_series
            if e["series_channel_id"] == "rick_and_morty"
        )
        assert stored_rick["unseen_new"] == 0

    def test_healthy_entry_is_left_untouched_same_object(self, tmp_path):
        """An entry at or below its summed baseline must not be rewritten at
        all -- same object, no needless copy."""
        from metatv.core.config import Config

        cfg = Config(config_dir=tmp_path / "cfg")
        healthy_entry = {
            "series_channel_id": "ch1",
            "source_id": "s1",
            "provider_id": "p1",
            "title": "Healthy Show",
            "baselines": {"p1": 10},
            "unseen_new": 3,
            "growth_providers": ["Test Provider"],
            "last_checked": "2026-08-01T00:00:00+00:00",
        }
        cfg.monitored_series = [healthy_entry]

        result = cfg.get_monitored_series()
        entry = result[0]
        assert entry["unseen_new"] == 3, \
            "a sane unseen_new (at/below the summed baselines) must not be touched"
        assert entry["baselines"] == {"p1": 10}
        assert entry["growth_providers"] == ["Test Provider"]
        assert entry is healthy_entry, \
            "a healthy entry must be returned as the SAME object, not rewritten"

    def test_migration_never_touches_other_fields_or_drops_entries(self, tmp_path):
        """Only unseen_new may change -- everything else on the entry, and every
        other entry in the list, must survive byte-for-byte. Per project rule:
        user data (favorites/ratings/history/watch progress) is sacrosanct, and
        monitored-series entries must never be deleted by this migration."""
        from metatv.core.config import Config

        cfg = Config(config_dir=tmp_path / "cfg")
        cfg.monitored_series = [
            {
                "series_channel_id": "inflated",
                "source_id": "s1",
                "provider_id": "p1",
                "title": "Inflated Show",
                "baselines": {"p1": 12},
                "unseen_new": 999,
                "growth_providers": ["Flaky Provider"],
                "last_checked": "2026-08-01T00:00:00+00:00",
                "custom_marker": "must-survive",
            },
            {
                "series_channel_id": "untouched",
                "source_id": "s2",
                "provider_id": "p2",
                "title": "Untouched Show",
                "baselines": {"p2": 4},
                "unseen_new": 1,
                "growth_providers": [],
                "last_checked": None,
            },
        ]

        result = cfg.get_monitored_series()

        assert len(result) == 2, "no monitored-series entry may be dropped"
        inflated = next(e for e in result if e["series_channel_id"] == "inflated")
        untouched = next(e for e in result if e["series_channel_id"] == "untouched")

        assert inflated["unseen_new"] == 0, "reset to 0, not clamped to 12"
        # Everything else on the corrected entry is preserved verbatim.
        assert inflated["baselines"] == {"p1": 12}
        assert inflated["title"] == "Inflated Show"
        assert inflated["growth_providers"] == ["Flaky Provider"]
        assert inflated["last_checked"] == "2026-08-01T00:00:00+00:00"
        assert inflated["custom_marker"] == "must-survive"

        # The untouched entry (already sane) is byte-for-byte identical.
        assert untouched == {
            "series_channel_id": "untouched",
            "source_id": "s2",
            "provider_id": "p2",
            "title": "Untouched Show",
            "baselines": {"p2": 4},
            "unseen_new": 1,
            "growth_providers": [],
            "last_checked": None,
        }

    def test_running_migration_twice_changes_nothing_further(self, tmp_path):
        from metatv.core.config import Config

        cfg = Config(config_dir=tmp_path / "cfg")
        cfg.monitored_series = [{
            "series_channel_id": "ch1",
            "source_id": "s1",
            "provider_id": "p1",
            "title": "Show",
            "baselines": {"p1": 91, "p2": 41},
            "unseen_new": 320,
            "growth_providers": [],
            "last_checked": None,
        }]

        first = cfg.get_monitored_series()
        assert first[0]["unseen_new"] == 0

        second = cfg.get_monitored_series()
        assert second[0]["unseen_new"] == 0, "second read must not re-touch it"
        assert second == first, "a second migration pass must be a pure no-op"

    def test_pure_function_idempotent_same_object_on_second_call(self):
        """zero_out_inflated_unseen_new itself: calling it again on its own
        output returns the exact same object (no needless copy once sane)."""
        from metatv.core.series_monitor import zero_out_inflated_unseen_new

        entry = {
            "series_channel_id": "ch1",
            "baselines": {"providerA": 91, "providerB": 41},
            "unseen_new": 320,
        }
        once = zero_out_inflated_unseen_new(entry)
        assert once is not entry
        assert once["unseen_new"] == 0

        twice = zero_out_inflated_unseen_new(once)
        assert twice is once, \
            "a second reset pass on an already-sane entry must be a no-op " \
            "(same object), not a fresh copy"

    def test_pure_function_leaves_entry_without_baselines_untouched(self):
        """No baseline data to validate against -- can't confidently prove
        corruption, so the entry (and any absurd unseen_new it carries) is
        left alone rather than guessed at."""
        from metatv.core.series_monitor import zero_out_inflated_unseen_new

        entry = {"series_channel_id": "ch1", "baselines": {}, "unseen_new": 999}
        result = zero_out_inflated_unseen_new(entry)
        assert result is entry
        assert result["unseen_new"] == 999


# ===========================================================================
# Part 3: the ONGOING guard (fresh writes) still CLAMPS -- must not regress
# into also zeroing. This is the sharp distinction the coordinator called
# out: one-time repair on PROVEN-corrupt data resets to 0; the ongoing
# belt-and-braces guard on a fresh, merely-implausible write clamps to the
# summed baselines instead.
# ===========================================================================

class TestOngoingGuardStillClampsNotZeroes:
    """clamp_unseen_new_to_baseline_total (the pure function) and
    SeriesMonitorManager._on_new_episodes (the call site) must clamp an
    implausible fresh write to the summed baselines -- never reset it to 0.
    """

    def test_pure_function_clamps_to_sum_not_zero(self):
        from metatv.core.series_monitor import clamp_unseen_new_to_baseline_total

        entry = {
            "series_channel_id": "ch1",
            "baselines": {"providerA": 91, "providerB": 41},
            "unseen_new": 320,
        }
        result = clamp_unseen_new_to_baseline_total(entry)
        assert result is not entry
        assert result["unseen_new"] == 132, \
            f"the ongoing guard must clamp to the summed baseline (132), " \
            f"not zero it: got {result['unseen_new']}"

    def test_pure_function_idempotent_same_object_on_second_call(self):
        from metatv.core.series_monitor import clamp_unseen_new_to_baseline_total

        entry = {"series_channel_id": "ch1", "baselines": {"p1": 23}, "unseen_new": 256}
        once = clamp_unseen_new_to_baseline_total(entry)
        assert once["unseen_new"] == 23
        twice = clamp_unseen_new_to_baseline_total(once)
        assert twice is once

    def test_on_new_episodes_ongoing_guard_clamps_not_zeroes(self, qapp):
        """Exercises the real call site inside _on_new_episodes. Uses a bare
        config stub (not the real Config) so Config.get_monitored_series'
        migrate-on-read RESET step never runs first and masks what
        _on_new_episodes' OWN clamp step does -- this isolates the ongoing
        guard's behavior specifically."""
        from metatv.core.series_monitor import SeriesMonitorManager

        class _MinimalConfigStub:
            """No migrate-on-read step -- deliberately bypasses Config's own
            zero_out_inflated_unseen_new so this test isolates
            _on_new_episodes' clamp_unseen_new_to_baseline_total call."""

            def __init__(self, entries):
                self.monitored_series = list(entries)

            def get_monitored_series(self):
                return list(self.monitored_series)

            def update_monitored_series(self, series_channel_id, **fields):
                updated = []
                for e in self.monitored_series:
                    if e.get("series_channel_id") == series_channel_id:
                        merged = dict(e)
                        merged.update(fields)
                        updated.append(merged)
                    else:
                        updated.append(e)
                self.monitored_series = updated

        cfg = _MinimalConfigStub([{
            "series_channel_id": "ch1",
            "source_id": "s1",
            "provider_id": "p1",
            "title": "Show",
            "baselines": {"p1": 10},
            "unseen_new": 500,  # already implausible going in
            "growth_providers": [],
            "last_checked": None,
        }])

        manager = SeriesMonitorManager(MagicMock(), cfg, notifications=None)
        manager._on_new_episodes(
            "ch1", 2, "Show",
            {"baselines": {"p1": 12}, "grown_provider_names": ["Provider"]},
        )

        entry = cfg.get_monitored_series()[0]
        assert entry["unseen_new"] == 12, (
            "the ONGOING guard must CLAMP to the summed baseline (12), "
            f"never zero it: got {entry['unseen_new']}"
        )
        manager.shutdown()
