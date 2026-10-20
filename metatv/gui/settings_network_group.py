"""Settings → Playback → Network: timeouts, reconnects and stream re-checking.

Its own module because it is one cohesive group — how hard MetaTV keeps trying a
source — and the tabs module was at its size pin when the re-check switch
(2026-10-20) joined it.
"""
from __future__ import annotations

from PyQt6.QtWidgets import QCheckBox, QFormLayout, QGroupBox, QSpinBox


def build_network_group(dlg) -> QGroupBox:
    """Build the Network group, setting its controls as attributes on *dlg*."""
    net_group = QGroupBox("Network")
    net_form = QFormLayout(net_group)
    net_form.setSpacing(8)

    dlg._timeout_spin = QSpinBox()
    dlg._timeout_spin.setRange(1, 60)
    dlg._timeout_spin.setSuffix(" s")
    net_form.addRow("Network timeout:", dlg._timeout_spin)

    dlg._reconnect_spin = QSpinBox()
    dlg._reconnect_spin.setRange(0, 10)
    net_form.addRow("Reconnect attempts:", dlg._reconnect_spin)

    dlg._stream_retry_checks_check = QCheckBox(
        "Re-check streams that failed to play"
    )
    dlg._stream_retry_checks_check.setToolTip(
        "Keep re-trying streams that failed, in the background, and tell you\n"
        "in Watch Alerts when one plays again. Each re-check is a real stream\n"
        "connection: on an account with one connection it can block your own\n"
        "playback, so this is off by default."
    )
    net_form.addRow(dlg._stream_retry_checks_check)

    dlg._recheck_failed_on_refresh_check = QCheckBox(
        "Re-check failed streams on source refresh"
    )
    dlg._recheck_failed_on_refresh_check.setToolTip(
        "When a source finishes refreshing, immediately re-probe any of its\n"
        "streams that previously failed (flagged/degraded/dead) instead of\n"
        "waiting for the background retry checker's own schedule. Recovered\n"
        "streams are restored to full visibility right away."
    )
    net_form.addRow(dlg._recheck_failed_on_refresh_check)
    # Depends on the switch above: no re-checking means none on refresh either.
    dlg._stream_retry_checks_check.toggled.connect(
        dlg._recheck_failed_on_refresh_check.setEnabled)

    return net_group
