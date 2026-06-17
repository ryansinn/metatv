"""Behavioral tests for the stream-diagnostics dialog (UI half).

The worker half (off-thread probe) is the boring try/except over the headless
engine — these pin the half that regresses: the main-thread render slot
(verdict headline text + Apply enabled/disabled), the Apply handler
(config.mpv_extra_args rewritten via merge_mpv_cache_args + save() called), the
pure merge helper, and the details-pane → diagnose_requested signal wiring.

Widgets are constructed via __new__ (no full QDialog __init__) and handed real
QLabels/QPushButtons through the module qapp fixture, so the slots run headless.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QLabel, QPushButton

from metatv.core import stream_diagnostics as _diag
from metatv.core.stream_diagnostics import DiagnosticResult
from metatv.gui.diagnostics_dialog import (
    StreamDiagnosticsDialog,
    merge_mpv_cache_args,
)


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


# --------------------------------------------------------------------------- #
# 1. merge_mpv_cache_args — the pure, idempotent merge helper                   #
# --------------------------------------------------------------------------- #

def test_merge_strips_existing_cache_args_keeps_others_appends_recommended():
    existing = ["--foo", "--cache=no", "--demuxer-max-bytes=10MiB"]
    recommended = ("--cache=yes", "--demuxer-max-bytes=128MiB", "--cache-secs=30")
    assert merge_mpv_cache_args(existing, recommended) == [
        "--foo",
        "--cache=yes",
        "--demuxer-max-bytes=128MiB",
        "--cache-secs=30",
    ]


def test_merge_empty_existing_returns_recommended():
    assert merge_mpv_cache_args([], ("--cache=yes",)) == ["--cache=yes"]


def test_merge_keeps_only_non_cache_args_in_order():
    existing = ["--foo", "--bar", "--volume=50"]
    assert merge_mpv_cache_args(existing, ("--cache=yes",)) == [
        "--foo",
        "--bar",
        "--volume=50",
        "--cache=yes",
    ]


def test_merge_empty_recommended_returns_existing_non_cache_unchanged():
    # No recommendation → strip cache args, keep the rest verbatim.
    assert merge_mpv_cache_args(["--foo", "--bar"], ()) == ["--foo", "--bar"]


def test_merge_is_idempotent():
    recommended = ("--cache=yes", "--demuxer-max-bytes=128MiB")
    once = merge_mpv_cache_args(["--foo"], recommended)
    twice = merge_mpv_cache_args(once, recommended)
    assert once == twice == ["--foo", "--cache=yes", "--demuxer-max-bytes=128MiB"]


# --------------------------------------------------------------------------- #
# 2. The result-render slot — verdict headline + Apply enable/disable           #
# --------------------------------------------------------------------------- #

def _bare_dialog(qapp) -> StreamDiagnosticsDialog:
    """Construct a dialog without running QDialog.__init__ and wire the widgets
    the render slot touches (real Qt widgets via the qapp fixture)."""
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
    # Metrics render the populated fields, not the None placeholder.
    assert "6.0 Mbps" in dlg._metrics.text()
    assert "50.0 Mbps" in dlg._metrics.text()


def test_render_internet_limited_headline(qapp):
    dlg = _bare_dialog(qapp)
    result = DiagnosticResult(
        reachable=True,
        verdict=_diag.INTERNET_LIMITED,
        summary="Pipe too thin.",
        recommended_args=("--cache=yes",),
    )
    dlg._on_result_ready(result)
    assert dlg._headline.text() == "Your internet connection is the bottleneck"
    assert dlg._apply_button.isEnabled() is True


def test_render_healthy_headline_and_apply_enabled(qapp):
    dlg = _bare_dialog(qapp)
    result = DiagnosticResult(
        reachable=True,
        verdict=_diag.HEALTHY,
        summary="Comfortable headroom.",
        recommended_args=("--cache=yes",),
    )
    dlg._on_result_ready(result)
    assert dlg._headline.text() == "Stream looks healthy"
    assert dlg._apply_button.isEnabled() is True


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
# 3. The Apply handler — rewrites config.mpv_extra_args via merge + saves        #
# --------------------------------------------------------------------------- #

class _FakeConfig:
    def __init__(self, mpv_extra_args):
        self.mpv_extra_args = mpv_extra_args
        self.save_calls = 0

    def save(self):
        self.save_calls += 1


def test_apply_rewrites_mpv_extra_args_and_saves(qapp):
    dlg = _bare_dialog(qapp)
    dlg._config = _FakeConfig(["--foo", "--cache=no"])
    dlg._result = DiagnosticResult(
        reachable=True,
        verdict=_diag.PROVIDER_LIMITED,
        summary="x",
        recommended_args=("--cache=yes", "--demuxer-max-bytes=256MiB"),
    )

    dlg._on_apply()

    assert dlg._config.mpv_extra_args == [
        "--foo",
        "--cache=yes",
        "--demuxer-max-bytes=256MiB",
    ]
    assert dlg._config.save_calls == 1
    # Apply disables itself and shows the confirmation.
    assert dlg._apply_button.isEnabled() is False
    assert dlg._saved.isVisible() or dlg._saved.text() != ""


def test_apply_noop_without_recommended_args(qapp):
    dlg = _bare_dialog(qapp)
    dlg._config = _FakeConfig(["--foo"])
    dlg._result = DiagnosticResult(
        reachable=False, verdict=_diag.UNREACHABLE, summary="x", recommended_args=()
    )
    dlg._on_apply()
    assert dlg._config.mpv_extra_args == ["--foo"]
    assert dlg._config.save_calls == 0


# --------------------------------------------------------------------------- #
# 4. Signal wiring — action bar diagnose_clicked → DetailsPane.diagnose_requested #
# --------------------------------------------------------------------------- #

def test_details_pane_reemits_diagnose_with_channel_id(qapp):
    """Firing the action bar's diagnose_clicked must re-emit DetailsPane.diagnose_requested
    with the current channel's id (the wrapper that adds the channel_id)."""
    from metatv.core.config import Config
    from metatv.core.image_cache import ImageCache
    from metatv.gui.details_pane import DetailsPaneWidget

    class _FakeChannel:
        id = "chan-123"

    dp = DetailsPaneWidget(Config(), ImageCache(), db=None)
    dp.current_channel = _FakeChannel()

    received: list[str] = []
    dp.diagnose_requested.connect(lambda cid: received.append(cid))

    dp._action_bar.diagnose_clicked.emit()
    assert received == ["chan-123"]


def test_details_pane_diagnose_noop_without_channel(qapp):
    """With no current channel the wrapper must not emit (guards against None.id)."""
    from metatv.core.config import Config
    from metatv.core.image_cache import ImageCache
    from metatv.gui.details_pane import DetailsPaneWidget

    dp = DetailsPaneWidget(Config(), ImageCache(), db=None)
    dp.current_channel = None

    received: list[str] = []
    dp.diagnose_requested.connect(lambda cid: received.append(cid))

    dp._action_bar.diagnose_clicked.emit()
    assert received == []
