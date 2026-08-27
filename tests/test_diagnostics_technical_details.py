"""Behavioral tests for the diagnostics on-demand "Technical details" popup.

Owner report: the always-on metrics block (throughput/bitrate/baseline/headroom/
ttfb/codec/resolution as a single word-wrapped QLabel) rendered clipped and
unreadable, and duplicated ~57% of the plain-language summary sentence above it
(``_build_summary`` in ``stream_diagnostics.py`` already states throughput,
bitrate, headroom and baseline). The fix removes the always-on block entirely
and replaces it with a "Technical details…" trigger that opens an on-demand
``_TechnicalDetailsDialog`` popup laid out as a key/value grid.

Coverage:
1. The main dialog no longer carries any VISIBLE label with the old run-on
   metrics text (geometry-adjacent: proves the block is gone, not just renamed).
2/3. The popup's grid — painted GEOMETRY: columns never overlap, and no value
   label is clipped (rendered box smaller than its own size hint).
4. A ``None``-valued field is OMITTED entirely, never shown as a dash.
5. The main dialog's trigger button is hidden until a real result arrives, and
   hidden again after a failed (``None``) result.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication, QLabel

from metatv.core import stream_diagnostics as _diag
from metatv.core.stream_diagnostics import DiagnosticResult
from metatv.gui.diagnostics_dialog import StreamDiagnosticsDialog, _TechnicalDetailsDialog


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _FakeExecutor:
    def submit(self, fn):  # pragma: no cover - never invoked in these tests
        pass


class _FakeConfig:
    diagnostics_sample_seconds = 8
    diagnostics_baseline_url = None


def _full_result(**overrides) -> DiagnosticResult:
    """A fully-populated DiagnosticResult so every possible row renders."""
    base = {
        "reachable": True,
        "verdict": _diag.HEALTHY,
        "summary": (
            "Stream is healthy — comfortable headroom over the bitrate. "
            "(throughput 12.4 Mbps vs bitrate 3.1 Mbps, headroom 4.00x; "
            "baseline 15.2 Mbps)"
        ),
        "connect_ms": 45.0,
        "ttfb_ms": 120.0,
        "throughput_mbps": 12.4,
        "bitrate_mbps": 3.1,
        "baseline_mbps": 15.2,
        "headroom_ratio": 4.0,
        "codec": "h264",
        "resolution": "1920x1080",
    }
    base.update(overrides)
    return DiagnosticResult(**base)


def _make_main_dialog() -> StreamDiagnosticsDialog:
    return StreamDiagnosticsDialog(
        channel_name="Test Channel",
        stream_url="http://server/live/user/pass/123.ts",
        config=_FakeConfig(),
        executor=_FakeExecutor(),
    )


# --------------------------------------------------------------------------- #
# 1. The always-on metrics block is gone                                      #
# --------------------------------------------------------------------------- #

def test_main_dialog_has_no_always_on_metrics_block(qtbot, qapp):
    dialog = _make_main_dialog()
    qtbot.addWidget(dialog)
    dialog.show()
    qapp.processEvents()

    dialog._on_result_ready(_full_result())
    qapp.processEvents()

    offenders = [
        label.text()
        for label in dialog.findChildren(QLabel)
        if label.isVisible() and "Throughput" in label.text() and "Codec" in label.text()
    ]
    assert offenders == [], (
        f"found an always-on metrics block still rendering both fields: {offenders!r}"
    )


# --------------------------------------------------------------------------- #
# 2/3. Popup grid geometry — no overlap, no clipping                          #
# --------------------------------------------------------------------------- #

def _show_details_popup(qtbot, qapp, result):
    dialog = _TechnicalDetailsDialog(result, parent=None)
    qtbot.addWidget(dialog)
    dialog.show()
    qapp.processEvents()
    qapp.processEvents()
    return dialog


def test_details_grid_columns_do_not_overlap(qtbot, qapp):
    dialog = _show_details_popup(qtbot, qapp, _full_result())

    assert dialog._rows, "expected at least one rendered row"
    for key_label, value_label in dialog._rows:
        key_geom = key_label.geometry()
        value_geom = value_label.geometry()
        assert key_geom.width() > 0
        assert value_geom.width() > 0
        assert key_geom.right() <= value_geom.left(), (
            f"key {key_label.text()!r} (right={key_geom.right()}) overlaps "
            f"value {value_label.text()!r} (left={value_geom.left()})"
        )
        assert abs(key_geom.top() - value_geom.top()) <= 2, (
            f"key {key_label.text()!r} and value {value_label.text()!r} are not "
            "on the same row"
        )


def test_details_values_are_not_clipped(qtbot, qapp):
    dialog = _show_details_popup(qtbot, qapp, _full_result())

    assert dialog._rows, "expected at least one rendered row"
    for _key_label, value_label in dialog._rows:
        geom = value_label.geometry()
        hint = value_label.sizeHint()
        assert geom.height() > 0 and hint.height() > 0
        assert geom.width() > 0 and hint.width() > 0
        assert geom.height() >= hint.height(), (
            f"value {value_label.text()!r} clipped vertically: "
            f"geom={geom.height()} < hint={hint.height()}"
        )
        assert geom.width() >= hint.width(), (
            f"value {value_label.text()!r} clipped horizontally: "
            f"geom={geom.width()} < hint={hint.width()}"
        )


# --------------------------------------------------------------------------- #
# 4. None-valued fields are omitted entirely, never shown as a dash           #
# --------------------------------------------------------------------------- #

def test_none_valued_rows_are_omitted(qtbot, qapp):
    sparse = _full_result(codec=None, baseline_mbps=None)
    dialog = _show_details_popup(qtbot, qapp, sparse)

    key_texts = [key_label.text() for key_label, _ in dialog._rows]
    assert not any(t.startswith("Codec") for t in key_texts), (
        f"Codec row must be omitted when codec is None, got keys={key_texts!r}"
    )
    assert not any(t.startswith("Baseline") for t in key_texts), (
        f"Baseline row must be omitted when baseline is None, got keys={key_texts!r}"
    )

    full_dialog = _show_details_popup(qtbot, qapp, _full_result())
    full_key_texts = [key_label.text() for key_label, _ in full_dialog._rows]
    assert any(t.startswith("Codec") for t in full_key_texts)
    assert any(t.startswith("Baseline") for t in full_key_texts)


# --------------------------------------------------------------------------- #
# 5. The trigger button is hidden until a real result arrives                 #
# --------------------------------------------------------------------------- #

def test_details_trigger_hidden_until_result(qtbot, qapp):
    dialog = _make_main_dialog()
    qtbot.addWidget(dialog)

    assert dialog._details_button.isHidden() is True

    dialog._on_result_ready(_full_result())
    assert dialog._details_button.isHidden() is False

    dialog._on_result_ready(None)
    assert dialog._details_button.isHidden() is True
