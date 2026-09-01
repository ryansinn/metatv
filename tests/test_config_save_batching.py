"""A watchlist pass must write the config once, not once per series.

``Config.save()`` copies the file to ``.bak``, runs a full Pydantic
``model_dump()`` and re-serialises everything. The owner's config is 4,854
lines / 132 KB — three quarters of it dev-QA results, derived filter caches and
an ever-growing collapsed-shelf list — so one save is not cheap.

Two loops paid that cost per iteration, and BOTH run on the main thread:

* ``SeriesMonitorManager._on_new_episodes`` is a queued-signal slot fired once
  per checked series. It is not a loop, so time-based debouncing cannot
  coalesce it — the signals arrive seconds apart across a pass. The buffer
  flushes on the pass boundary the class already has instead.
* ``MainWindow._apply`` (the ``_run_query`` callback backfilling
  region/language) saved once per row.

The owner's log recorded 29 UI-thread stalls in one session, worst 10,261 ms,
interleaved with ~10 ``Saved config`` lines in 40 seconds.

Each test here fails on the pre-fix tree, where every buffered write was an
immediate ``Config.save()``.
"""

from __future__ import annotations

import pathlib
import pytest


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _config_with_series(tmp_path: pathlib.Path, n: int):
    from metatv.core.config import Config
    cfg = Config(config_dir=tmp_path)
    cfg.monitored_series = [{
        "series_channel_id": f"ch{i}", "source_id": "s", "provider_id": "p",
        "title": f"Series {i}", "baselines": {}, "unseen_new": 0,
        "last_checked": None,
    } for i in range(n)]
    return cfg


def _count_saves(monkeypatch):
    """Patch Config.save to count calls, returning the (mutable) counter list."""
    from metatv.core.config import Config
    calls: list[int] = []
    real = Config.save

    def counting(self):
        calls.append(1)
        return real(self)

    monkeypatch.setattr(Config, "save", counting)
    return calls


class TestBatchedConfigWrite:

    def test_many_updates_cost_exactly_one_save(self, tmp_path, monkeypatch):
        cfg = _config_with_series(tmp_path, 11)
        saves = _count_saves(monkeypatch)

        cfg.update_monitored_series_many({
            f"ch{i}": {"baselines": {"p|s": i}, "last_checked": "t"}
            for i in range(11)
        })

        assert len(saves) == 1, (
            f"11 series cost {len(saves)} config saves; the whole point is one")
        assert cfg.monitored_series[5]["baselines"] == {"p|s": 5}
        assert cfg.monitored_series[5]["last_checked"] == "t"

    def test_it_merges_fields_rather_than_replacing_the_entry(self, tmp_path):
        cfg = _config_with_series(tmp_path, 2)
        cfg.update_monitored_series_many({"ch0": {"unseen_new": 3}})
        entry = cfg.monitored_series[0]
        assert entry["unseen_new"] == 3
        assert entry["title"] == "Series 0", "untouched fields must survive"
        assert entry["source_id"] == "s"

    def test_an_empty_or_unmatched_update_does_not_save(self, tmp_path, monkeypatch):
        """A no-op must not pay 132 KB."""
        cfg = _config_with_series(tmp_path, 2)
        saves = _count_saves(monkeypatch)
        cfg.update_monitored_series_many({})
        cfg.update_monitored_series_many({"nonexistent": {"unseen_new": 1}})
        assert len(saves) == 0, "a no-op update still rewrote the config"


class TestSeriesMonitorBuffersUntilThePassEnds:

    def _manager(self, cfg):
        from metatv.core.series_monitor import SeriesMonitorManager
        m = SeriesMonitorManager.__new__(SeriesMonitorManager)
        m.config = cfg
        m._pending_series_updates = {}
        m._pending_batches = 0
        return m

    def test_buffering_writes_nothing_until_the_pass_ends(
            self, tmp_path, monkeypatch, qapp):
        cfg = _config_with_series(tmp_path, 11)
        m = self._manager(cfg)
        saves = _count_saves(monkeypatch)

        for i in range(11):
            m._buffer_series_update(f"ch{i}", baselines={"p|s": i},
                                    last_checked="t")
        assert len(saves) == 0, (
            "buffering saved eagerly — this is the per-series write that froze "
            "the UI once per monitored series")

        m.flush_pending_series_updates()
        assert len(saves) == 1
        assert cfg.monitored_series[7]["baselines"] == {"p|s": 7}

    def test_repeated_buffering_of_one_series_merges(self, tmp_path, qapp):
        cfg = _config_with_series(tmp_path, 1)
        m = self._manager(cfg)
        m._buffer_series_update("ch0", baselines={"p|s": 1})
        m._buffer_series_update("ch0", unseen_new=4)
        assert m._pending_series_updates["ch0"] == {
            "baselines": {"p|s": 1}, "unseen_new": 4}

    def test_the_buffer_is_cleared_by_a_flush(self, tmp_path, monkeypatch, qapp):
        """A buffer that never clears would re-write stale values every pass."""
        cfg = _config_with_series(tmp_path, 2)
        m = self._manager(cfg)
        m._buffer_series_update("ch0", unseen_new=1)
        m.flush_pending_series_updates()
        assert m._pending_series_updates == {}

        saves = _count_saves(monkeypatch)
        m.flush_pending_series_updates()
        assert len(saves) == 0, "an empty flush must not save"

    def test_the_pass_boundary_flushes(self, tmp_path, monkeypatch, qapp):
        """``_on_check_batch_done`` is where the single write happens."""
        cfg = _config_with_series(tmp_path, 3)
        m = self._manager(cfg)
        m._pending_batches = 1
        for i in range(3):
            m._buffer_series_update(f"ch{i}", unseen_new=i + 1)

        saves = _count_saves(monkeypatch)
        # Bypass the pyqtSignal emit (needs a real QObject) but run the slot body.
        from metatv.core.series_monitor import SeriesMonitorManager
        monkeypatch.setattr(
            SeriesMonitorManager, "checking_finished",
            type("Sig", (), {"emit": lambda self: None})(), raising=False)
        SeriesMonitorManager._on_check_batch_done(m)

        assert len(saves) == 1, "the pass boundary did not flush the buffer"
        assert cfg.monitored_series[2]["unseen_new"] == 3

    def test_a_failing_save_does_not_wedge_the_buffer(self, tmp_path, monkeypatch, qapp):
        """A disk error must not make every later pass re-attempt stale writes."""
        from metatv.core.config import Config
        cfg = _config_with_series(tmp_path, 1)
        m = self._manager(cfg)
        m._buffer_series_update("ch0", unseen_new=9)
        monkeypatch.setattr(
            Config, "update_monitored_series_many",
            lambda self, u: (_ for _ in ()).throw(OSError("disk full")))
        m.flush_pending_series_updates()      # must not raise
        assert m._pending_series_updates == {}, "buffer retained after a failure"


class TestSeriesIntervalSetting:
    """The interval is reachable from Settings, and OK actually applies it.

    Before this there was no UI for ``series_monitor_interval_minutes`` at all —
    switching the watchlist poll off meant hand-editing config.yaml with the app
    closed, because the app rewrites that file on exit.

    "Saved without applying" is a failure this dialog has had before, so the
    host hook is asserted too: the value only takes effect when the timer is
    re-armed, and ``_restart_series_monitor_scheduler`` is what does it.
    """

    def _dialog(self, tmp_path, minutes: int):
        from metatv.core.config import Config
        from metatv.gui.settings_dialog import SettingsDialog
        cfg = Config(config_dir=tmp_path)
        cfg.series_monitor_interval_minutes = minutes
        return cfg, SettingsDialog(cfg, None)

    def test_the_dialog_shows_the_stored_interval(self, tmp_path, qapp):
        cfg, dlg = self._dialog(tmp_path, 60)
        assert dlg._series_interval_spin.value() == 60

    def test_ok_writes_the_new_interval(self, tmp_path, qapp):
        cfg, dlg = self._dialog(tmp_path, 60)
        dlg._series_interval_spin.setValue(180)
        dlg._save_values()
        assert cfg.series_monitor_interval_minutes == 180

    def test_zero_is_offered_as_never_and_persists(self, tmp_path, qapp):
        """0 disables the recurring poll — the whole point of exposing this."""
        cfg, dlg = self._dialog(tmp_path, 60)
        assert dlg._series_interval_spin.specialValueText() == "Never", (
            "0 must read as a choice, not as a bare zero")
        assert dlg._series_interval_spin.minimum() == 0
        dlg._series_interval_spin.setValue(0)
        dlg._save_values()
        assert cfg.series_monitor_interval_minutes == 0

    def test_the_host_re_arms_the_timer_on_apply(self, tmp_path, qapp):
        """A setting saved but never applied is a known failure mode here."""
        from unittest.mock import MagicMock
        from metatv.gui.main_window import MainWindow

        host = MainWindow.__new__(MainWindow)
        host.series_monitor = MagicMock()
        MainWindow._restart_series_monitor_scheduler(host)
        host.series_monitor.start_scheduler.assert_called_once()

    def test_the_hook_is_registered_so_it_cannot_be_forgotten(self):
        """The registry is what makes the wiring discoverable, not a grep."""
        from tests.conftest import _SETTINGS_APPLIED_HOOKS
        assert "_restart_series_monitor_scheduler" in _SETTINGS_APPLIED_HOOKS
