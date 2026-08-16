"""Stream-diagnostics modal dialog.

Wraps the headless engine :func:`metatv.core.stream_diagnostics.run_stream_diagnostic`
in a Qt modal. The probe runs off the main thread on the MainWindow's shared
``ThreadPoolExecutor``; the worker emits a private signal carrying the
:class:`~metatv.core.stream_diagnostics.DiagnosticResult` and the connected slot
renders it on the main thread (Qt widgets are not thread-safe).

The dialog answers one question in plain language — *is buffering my provider or my
connection?* — and offers an "Apply tuning & Save" action that writes the structured
Playback settings (``config.buffer_profile`` and ``config.prebuffer_before_play``) so
the Settings → Playback tab remains the single source of truth.
"""

from __future__ import annotations

from loguru import logger

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
)

from metatv.core import stream_diagnostics as _diag
from metatv.core.stream_diagnostics import DiagnosticResult, recommend_buffer_profile
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme


# Human-readable labels for buffer_profile values.
_PROFILE_LABELS: dict[str, str] = {
    "reconnect_only": "Reconnect-only",
    "modest": "Modest",
    "large": "Large",
}


# Plain-language headline per verdict — answers the user's question directly.
_HEADLINES = {
    _diag.HEALTHY: "Stream looks healthy",
    _diag.JITTER: "Connection is jittery — a bigger buffer will help",
    _diag.PROVIDER_LIMITED: "Your source is the bottleneck",
    _diag.INTERNET_LIMITED: "Your internet connection is the bottleneck",
    _diag.UNREACHABLE: "Couldn't reach the stream",
}


def _headline_color(verdict: str) -> str:
    """Return the theme token (hex string) for a verdict's headline color."""
    if verdict == _diag.HEALTHY:
        return _theme.COLOR_OK
    if verdict == _diag.JITTER:
        return _theme.COLOR_WARN
    if verdict in (_diag.PROVIDER_LIMITED, _diag.INTERNET_LIMITED):
        return _theme.COLOR_ERR
    # UNREACHABLE or anything unexpected — muted.
    return _theme.COLOR_MUTED


def _fmt_mbps(value: float | None) -> str:
    return f"{value:.1f} Mbps" if value is not None else "—"


def _fmt_ms(value: float | None) -> str:
    return f"{value:.0f} ms" if value is not None else "—"


def _fmt_ratio(value: float | None) -> str:
    return f"{value:.2f}x" if value is not None else "—"


def _fmt_str(value: str | None) -> str:
    return value if value else "—"


class StreamDiagnosticsDialog(QDialog):
    """Modal dialog that runs a stream diagnostic and renders the verdict.

    The probe runs on the passed-in shared executor (never a dialog-owned pool);
    the worker only emits ``_result_ready`` — all widget access happens on the
    main-thread slot.
    """

    # Private — carries a DiagnosticResult (or None on unexpected worker failure)
    # from the executor worker back to the main thread.
    _result_ready = pyqtSignal(object)

    def __init__(
        self,
        *,
        channel_name: str,
        stream_url: str,
        config,
        executor,
        player_active: bool = False,
        episode_label: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._channel_name = channel_name
        self._stream_url = stream_url
        self._config = config
        self._executor = executor
        self._player_active = player_active
        self._episode_label = episode_label
        self._result: DiagnosticResult | None = None

        self.setWindowTitle("Stream diagnostics")
        self.setMinimumWidth(420)
        self._setup_ui()
        self._result_ready.connect(self._on_result_ready)

    # ------------------------------------------------------------------ #
    # UI                                                                   #
    # ------------------------------------------------------------------ #

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        title = QLabel(f"{_icons.diagnose_icon} {self._channel_name}")
        _theme.style(title, "DETAIL_TITLE")
        title.setWordWrap(True)
        layout.addWidget(title)

        # Always-visible URL line (redacted for security).
        url_display = f"Testing {_diag._redact(self._stream_url)}"
        if self._episode_label:
            url_display = f"Testing {self._episode_label}: {_diag._redact(self._stream_url)}"
        self._url_line = QLabel(url_display)
        _theme.style(self._url_line, "DIAG_URL")
        self._url_line.setWordWrap(True)
        layout.addWidget(self._url_line)

        if self._player_active:
            warn = QLabel(
                f"{_icons.notification_warning_icon} A stream is currently playing. "
                "Diagnosing may fail on single-connection providers — stop playback "
                "for an accurate result."
            )
            warn.setWordWrap(True)
            _theme.style(warn, "DIAG_PLAYING_WARNING")
            layout.addWidget(warn)

        self._run_button = QPushButton("Run diagnostic")
        self._run_button.setToolTip("Probe this stream and diagnose buffering causes")
        self._run_button.clicked.connect(self._on_run)
        layout.addWidget(self._run_button)

        # Verdict headline (color set per result).
        self._headline = QLabel("")
        self._headline.setWordWrap(True)
        self._headline.hide()
        layout.addWidget(self._headline)

        # Plain-language summary.
        self._summary = QLabel("Run a diagnostic to see results.")
        self._summary.setWordWrap(True)
        _theme.style(self._summary, "DIAG_SUMMARY")
        layout.addWidget(self._summary)

        # On-demand trigger for the raw-measurements popup (throughput / bitrate /
        # baseline / headroom / ttfb / codec / resolution) — the summary sentence
        # above already states throughput, bitrate, headroom and baseline in
        # plain language, so these are a detail-on-demand, not an always-on block.
        self._details_button = QPushButton("Technical details…")
        self._details_button.setFlat(True)
        self._details_button.setToolTip(
            "Show the raw measurements behind this verdict"
        )
        self._details_button.clicked.connect(self._on_show_details)
        self._details_button.hide()
        layout.addWidget(self._details_button)

        # Recommended args / saved confirmation.
        self._recommend = QLabel("")
        self._recommend.setWordWrap(True)
        _theme.style(self._recommend, "DIAG_RECOMMEND")
        self._recommend.hide()
        layout.addWidget(self._recommend)

        self._saved = QLabel("")
        self._saved.setWordWrap(True)
        _theme.style(self._saved, "DIAG_SAVED")
        self._saved.hide()
        layout.addWidget(self._saved)

        # Footer buttons.
        footer = QHBoxLayout()
        self._apply_button = QPushButton("Apply tuning && Save")
        self._apply_button.setToolTip(
            "Save the recommended mpv cache settings — takes effect on the next stream you play"
        )
        self._apply_button.setEnabled(False)
        self._apply_button.clicked.connect(self._on_apply)
        footer.addWidget(self._apply_button)

        footer.addStretch()

        close_button = QPushButton("Close")
        close_button.setToolTip("Close this dialog")
        close_button.clicked.connect(self.reject)
        footer.addWidget(close_button)

        layout.addLayout(footer)

    # ------------------------------------------------------------------ #
    # Run — worker emits signal, slot renders on main thread               #
    # ------------------------------------------------------------------ #

    def _on_run(self) -> None:
        self._run_button.setEnabled(False)
        self._saved.hide()
        self._summary.setText(f"{_icons.loading_icon} Running diagnostic…")
        self._executor.submit(self._worker)

    def _worker(self) -> None:
        """Run the headless probe off the main thread. NEVER touches widgets.

        Emits ``_result_ready`` with the result, or with a synthetic failed result
        (or ``None``) on unexpected error — an exception must never escape here.
        """
        try:
            result = _diag.run_stream_diagnostic(
                self._stream_url,
                sample_seconds=self._config.diagnostics_sample_seconds,
                baseline_url=self._config.diagnostics_baseline_url,
            )
        except Exception as exc:  # pragma: no cover - defensive; engine is hardened
            logger.warning(f"Stream diagnostic raised unexpectedly: {type(exc).__name__}")
            result = DiagnosticResult(
                reachable=False,
                verdict=_diag.UNREACHABLE,
                summary="The diagnostic failed unexpectedly. Please try again.",
                error=type(exc).__name__,
            )
        self._result_ready.emit(result)

    def _on_result_ready(self, result: DiagnosticResult | None) -> None:
        """Render a diagnostic result. MAIN THREAD ONLY."""
        self._run_button.setEnabled(True)

        if result is None:
            self._result = None
            self._summary.setText("The diagnostic failed unexpectedly. Please try again.")
            self._apply_button.setEnabled(False)
            self._details_button.hide()
            return

        self._result = result

        headline = _HEADLINES.get(result.verdict, "Diagnostic complete")
        color = _headline_color(result.verdict)
        self._headline.setText(headline)
        self._headline.setStyleSheet(
            f"color: {color}; {_theme.DIAG_VERDICT_HEADLINE}"
        )
        self._headline.show()

        self._summary.setText(result.summary)

        self._details_button.show()

        profile, prebuffer = recommend_buffer_profile(result.verdict)
        if profile is not None:
            label = _PROFILE_LABELS.get(profile, profile)
            rec_text = f"Recommended buffering: {label}"
            if prebuffer:
                rec_text += " + pre-buffer"
            self._recommend.setText(rec_text)
            self._recommend.show()
            self._apply_button.setEnabled(True)
        else:
            self._recommend.setText("No buffering change recommended.")
            self._recommend.show()
            self._apply_button.setEnabled(False)

    # ------------------------------------------------------------------ #
    # Technical details popup                                              #
    # ------------------------------------------------------------------ #

    def _on_show_details(self) -> None:
        """Open the on-demand technical-details popup for the last result."""
        if self._result is None:
            return
        dialog = _TechnicalDetailsDialog(self._result, parent=self)
        dialog.exec()

    # ------------------------------------------------------------------ #
    # Apply tuning                                                         #
    # ------------------------------------------------------------------ #

    def _on_apply(self) -> None:
        """Write the recommended buffer profile to structured Playback config and persist."""
        if not self._result:
            return
        profile, prebuffer = recommend_buffer_profile(self._result.verdict)
        if profile is None:
            return
        self._config.buffer_profile = profile
        self._config.prebuffer_before_play = prebuffer
        self._config.save()
        label = _PROFILE_LABELS.get(profile, profile)
        prebuf_str = ", pre-buffer on" if prebuffer else ""
        saved_msg = (
            f"Saved — buffering set to {label}{prebuf_str}. "
            "Takes effect on the next stream you play."
        )
        if getattr(self._config, "mpv_args_override_all", False):
            saved_msg += (
                " (Override-all is on — this change won't take effect until "
                "Override-all is turned off in Settings → Playback.)"
            )
        logger.info(
            f"Applied diagnostic tuning: buffer_profile={profile!r} "
            f"prebuffer_before_play={prebuffer}"
        )
        self._saved.setText(saved_msg)
        self._saved.show()
        self._apply_button.setEnabled(False)


class _TechnicalDetailsDialog(QDialog):
    """On-demand popup showing the raw measurements behind a diagnostic verdict.

    The main dialog's summary sentence already states throughput, bitrate,
    headroom and baseline in plain language — this popup is the detail-on-demand
    view for the reader who wants the raw numbers, laid out as a key/value grid.
    A row whose underlying :class:`~metatv.core.stream_diagnostics.DiagnosticResult`
    field is ``None`` is omitted entirely, never rendered as a dash placeholder.
    Never renders the raw (unredacted) stream URL — the result carries no
    credentials, but this stays deliberate.
    """

    def __init__(self, result: DiagnosticResult, parent: QDialog | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Technical details")
        self.setMinimumWidth(360)

        rows: list[tuple[str, str]] = []
        if result.connect_ms is not None:
            rows.append(("Connect time", _fmt_ms(result.connect_ms)))
        if result.ttfb_ms is not None:
            rows.append(("Time to first byte", _fmt_ms(result.ttfb_ms)))
        if result.throughput_mbps is not None:
            rows.append(("Throughput", _fmt_mbps(result.throughput_mbps)))
        if result.bitrate_mbps is not None:
            rows.append(("Bitrate", _fmt_mbps(result.bitrate_mbps)))
        if result.baseline_mbps is not None:
            rows.append(("Baseline", _fmt_mbps(result.baseline_mbps)))
        if result.headroom_ratio is not None:
            rows.append(("Headroom", _fmt_ratio(result.headroom_ratio)))
        if result.codec is not None:
            rows.append(("Codec", _fmt_str(result.codec)))
        if result.resolution is not None:
            rows.append(("Resolution", _fmt_str(result.resolution)))

        layout = QVBoxLayout(self)

        # Exposed for tests: the (key label, value label) pair for every rendered
        # row, in display order. Not consulted by any production code.
        self._rows: list[tuple[QLabel, QLabel]] = []

        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        for row_index, (key_text, value_text) in enumerate(rows):
            key_label = QLabel(key_text)
            key_label.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            _theme.style(key_label, "DIAG_METRIC_KEY")
            grid.addWidget(key_label, row_index, 0)

            value_label = QLabel(value_text)
            value_label.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            _theme.style(value_label, "DIAG_METRICS")
            grid.addWidget(value_label, row_index, 1)

            self._rows.append((key_label, value_label))
        layout.addLayout(grid)

        close_button = QPushButton("Close")
        close_button.setToolTip("Close technical details")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)

        self.adjustSize()
