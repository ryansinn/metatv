"""Behavioral tests for the stream-diagnostics dialog (UI half).

The worker half (off-thread probe) is the boring try/except over the headless
engine — these pin the half that regresses: the main-thread render slot
(verdict headline text, buffering recommendation text, Apply enabled/disabled),
the Apply handler (config.buffer_profile + config.prebuffer_before_play written
+ save() called; config unchanged and save() NOT called when no profile change is
warranted), and the bottom-nav on_diagnose_clicked handler (targets the selected
channel; notifies + skips the lookup when nothing is selected).

Widgets are constructed via __new__ (no full QDialog __init__) and handed real
QLabels/QPushButtons through the module qapp fixture, so the slots run headless.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QLabel, QPushButton

from metatv.core import stream_diagnostics as _diag
from metatv.core.stream_diagnostics import DiagnosticResult


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


# --------------------------------------------------------------------------- #
# Shared helpers                                                               #
# --------------------------------------------------------------------------- #

def _bare_dialog(qapp):
    """Construct a dialog without running QDialog.__init__ and wire the widgets
    the render slot touches (real Qt widgets via the qapp fixture)."""
    from metatv.gui.diagnostics_dialog import StreamDiagnosticsDialog
    dlg = StreamDiagnosticsDialog.__new__(StreamDiagnosticsDialog)
    dlg._result = None
    dlg._run_button = QPushButton()
    dlg._headline = QLabel()
    dlg._summary = QLabel()
    dlg._metrics = QLabel()
    dlg._recommend = QLabel()
    dlg._saved = QLabel()
    dlg._apply_button = QPushButton()
    dlg._apply_button.setEnabled(False)
    return dlg


class _FakeConfig:
    def __init__(self, *, buffer_profile="modest", prebuffer_before_play=False,
                 mpv_args_override_all=False):
        self.buffer_profile = buffer_profile
        self.prebuffer_before_play = prebuffer_before_play
        self.mpv_args_override_all = mpv_args_override_all
        self.save_calls = 0

    def save(self):
        self.save_calls += 1


# --------------------------------------------------------------------------- #
# 1. The result-render slot — verdict headline + recommendation + Apply state  #
# --------------------------------------------------------------------------- #

def test_render_provider_limited_headline_and_apply_enabled(qapp):
    dlg = _bare_dialog(qapp)
    result = DiagnosticResult(
        reachable=True,
        verdict=_diag.PROVIDER_LIMITED,
        summary="Provider can't deliver this bitrate.",
        throughput_mbps=2.0,
        bitrate_mbps=6.0,
        baseline_mbps=50.0,
        headroom_ratio=0.33,
        recommended_args=("--cache=yes", "--demuxer-max-bytes=256MiB"),
    )
    dlg._on_result_ready(result)

    assert dlg._headline.text() == "Your provider is the bottleneck"
    assert dlg._summary.text() == "Provider can't deliver this bitrate."
    assert dlg._apply_button.isEnabled() is True
    assert dlg._run_button.isEnabled() is True
    # Metrics render the populated fields.
    assert "6.0 Mbps" in dlg._metrics.text()
    assert "50.0 Mbps" in dlg._metrics.text()
    # Recommendation text shows a profile label, not raw mpv flags.
    rec = dlg._recommend.text()
    assert "Large" in rec
    assert "pre-buffer" in rec
    assert "--cache=" not in rec


def test_render_jitter_shows_profile_no_prebuffer(qapp):
    dlg = _bare_dialog(qapp)
    result = DiagnosticResult(
        reachable=True,
        verdict=_diag.JITTER,
        summary="Barely keeping up.",
        recommended_args=("--cache=yes", "--demuxer-max-bytes=128MiB"),
    )
    dlg._on_result_ready(result)

    assert dlg._apply_button.isEnabled() is True
    rec = dlg._recommend.text()
    assert "Large" in rec
    assert "pre-buffer" not in rec


def test_render_healthy_shows_no_change_and_disables_apply(qapp):
    dlg = _bare_dialog(qapp)
    result = DiagnosticResult(
        reachable=True,
        verdict=_diag.HEALTHY,
        summary="Comfortable headroom.",
        recommended_args=("--cache=yes",),
    )
    dlg._on_result_ready(result)

    assert dlg._headline.text() == "Stream looks healthy"
    assert dlg._apply_button.isEnabled() is False
    assert "No buffering change recommended." in dlg._recommend.text()


def test_render_internet_limited_shows_no_change_and_disables_apply(qapp):
    dlg = _bare_dialog(qapp)
    result = DiagnosticResult(
        reachable=True,
        verdict=_diag.INTERNET_LIMITED,
        summary="Pipe too thin.",
        recommended_args=("--cache=yes",),
    )
    dlg._on_result_ready(result)

    assert dlg._apply_button.isEnabled() is False
    assert "No buffering change recommended." in dlg._recommend.text()


def test_render_unreachable_keeps_apply_disabled(qapp):
    dlg = _bare_dialog(qapp)
    result = DiagnosticResult(
        reachable=False,
        verdict=_diag.UNREACHABLE,
        summary="Could not reach the stream.",
        recommended_args=(),
    )
    dlg._on_result_ready(result)

    assert dlg._headline.text() == "Couldn't reach the stream"
    assert dlg._apply_button.isEnabled() is False


def test_render_none_result_shows_failure_and_disables_apply(qapp):
    dlg = _bare_dialog(qapp)
    dlg._apply_button.setEnabled(True)  # pretend a prior result enabled it
    dlg._on_result_ready(None)

    assert dlg._result is None
    assert dlg._apply_button.isEnabled() is False
    assert "failed" in dlg._summary.text().lower()


def test_render_metrics_show_dash_for_none_fields(qapp):
    dlg = _bare_dialog(qapp)
    result = DiagnosticResult(
        reachable=True,
        verdict=_diag.JITTER,
        summary="Barely keeping up.",
        recommended_args=("--cache=yes",),
    )
    dlg._on_result_ready(result)
    # None numeric fields render as the em-dash placeholder, not "None".
    assert "—" in dlg._metrics.text()
    assert "None" not in dlg._metrics.text()


# --------------------------------------------------------------------------- #
# 2. The Apply handler — writes structured config fields, calls save()         #
# --------------------------------------------------------------------------- #

def test_apply_provider_limited_sets_large_and_prebuffer(qapp):
    dlg = _bare_dialog(qapp)
    dlg._config = _FakeConfig()
    dlg._result = DiagnosticResult(
        reachable=True,
        verdict=_diag.PROVIDER_LIMITED,
        summary="x",
        recommended_args=("--cache=yes",),
    )

    dlg._on_apply()

    assert dlg._config.buffer_profile == "large"
    assert dlg._config.prebuffer_before_play is True
    assert dlg._config.save_calls == 1
    assert dlg._apply_button.isEnabled() is False
    saved = dlg._saved.text()
    assert "Large" in saved
    assert "pre-buffer on" in saved


def test_apply_jitter_sets_large_no_prebuffer(qapp):
    dlg = _bare_dialog(qapp)
    dlg._config = _FakeConfig()
    dlg._result = DiagnosticResult(
        reachable=True,
        verdict=_diag.JITTER,
        summary="x",
        recommended_args=("--cache=yes",),
    )

    dlg._on_apply()

    assert dlg._config.buffer_profile == "large"
    assert dlg._config.prebuffer_before_play is False
    assert dlg._config.save_calls == 1
    saved = dlg._saved.text()
    assert "Large" in saved
    assert "pre-buffer on" not in saved


def test_apply_healthy_noop(qapp):
    """HEALTHY verdict: Apply must not write config or call save."""
    dlg = _bare_dialog(qapp)
    dlg._config = _FakeConfig(buffer_profile="modest")
    dlg._result = DiagnosticResult(
        reachable=True,
        verdict=_diag.HEALTHY,
        summary="x",
        recommended_args=("--cache=yes",),
    )

    dlg._on_apply()

    assert dlg._config.buffer_profile == "modest"   # unchanged
    assert dlg._config.save_calls == 0


def test_apply_unreachable_noop(qapp):
    """UNREACHABLE verdict: Apply must not write config or call save."""
    dlg = _bare_dialog(qapp)
    dlg._config = _FakeConfig(buffer_profile="modest")
    dlg._result = DiagnosticResult(
        reachable=False,
        verdict=_diag.UNREACHABLE,
        summary="x",
        recommended_args=(),
    )

    dlg._on_apply()

    assert dlg._config.buffer_profile == "modest"   # unchanged
    assert dlg._config.save_calls == 0


def test_apply_override_all_appends_warning(qapp):
    """When mpv_args_override_all is True the saved message includes a note."""
    dlg = _bare_dialog(qapp)
    dlg._config = _FakeConfig(mpv_args_override_all=True)
    dlg._result = DiagnosticResult(
        reachable=True,
        verdict=_diag.JITTER,
        summary="x",
        recommended_args=("--cache=yes",),
    )

    dlg._on_apply()

    assert dlg._config.save_calls == 1
    assert "Override-all" in dlg._saved.text()


def test_apply_noop_without_result(qapp):
    """_on_apply with no result set must be a safe no-op."""
    dlg = _bare_dialog(qapp)
    dlg._config = _FakeConfig()
    dlg._result = None

    dlg._on_apply()

    assert dlg._config.save_calls == 0


# --------------------------------------------------------------------------- #
# 3. Nav-bar handler — on_diagnose_clicked targets the selected channel        #
# --------------------------------------------------------------------------- #

def test_nav_diagnose_targets_selected_channel(qapp):
    """With a selected channel, on_diagnose_clicked calls diagnose_channel_by_id
    with that channel's id exactly once (the nav-bar action reuses the lookup)."""
    from types import SimpleNamespace
    from metatv.gui.main_window import MainWindow

    host = MainWindow.__new__(MainWindow)
    host.details_pane = SimpleNamespace(current_channel=SimpleNamespace(id="ch-123"))

    called: list[str] = []
    host.diagnose_channel_by_id = lambda cid: called.append(cid)

    MainWindow.on_diagnose_clicked(host)
    assert called == ["ch-123"]


def test_nav_diagnose_no_channel_notifies_and_skips_lookup(qapp):
    """With no selected channel, on_diagnose_clicked must NOT call the lookup and
    must surface a notification instead."""
    from types import SimpleNamespace
    from metatv.gui.main_window import MainWindow

    host = MainWindow.__new__(MainWindow)
    host.details_pane = SimpleNamespace(current_channel=None)

    called: list[str] = []
    host.diagnose_channel_by_id = lambda cid: called.append(cid)

    shown: list[dict] = []
    host.notification_manager = SimpleNamespace(
        show=lambda **kwargs: shown.append(kwargs)
    )

    MainWindow.on_diagnose_clicked(host)
    assert called == []
    assert len(shown) == 1
