"""Stream-diagnostics modal dialog.

Wraps the headless engine :func:`metatv.core.stream_diagnostics.run_stream_diagnostic`
in a Qt modal. The probe runs off the main thread on the MainWindow's shared
``ThreadPoolExecutor``; the worker emits a private signal carrying the
:class:`~metatv.core.stream_diagnostics.DiagnosticResult` and the connected slot
renders it on the main thread (Qt widgets are not thread-safe).

The dialog answers one question in plain language — *is buffering my provider or my
connection?* — and offers an "Apply tuning & Save" action that merges the engine's
recommended mpv cache args into ``config.mpv_extra_args`` idempotently.
"""

from __future__ import annotations

from loguru import logger

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
)

from metatv.core import stream_diagnostics as _diag
from metatv.core.stream_diagnostics import DiagnosticResult
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme


# mpv cache-tuning flags this dialog manages. Any of these present in the user's
# existing args is dropped before appending the recommended set, so Apply is
# idempotent and never duplicates a flag.
_CACHE_ARG_PREFIXES = (
    "--cache=",
    "--cache-secs=",
    "--demuxer-max-bytes=",
    "--demuxer-readahead-secs=",
)


def merge_mpv_cache_args(
    existing: list[str], recommended: tuple[str, ...]
) -> list[str]:
    """Merge recommended mpv cache args into an existing arg list, idempotently.

    Drops any existing cache-tuning args (anything matching ``_CACHE_ARG_PREFIXES``),
    keeps all other user args in their original order, then appends the recommended
    args. Applying the same recommendation twice yields the same list — no duplicate
    flags accumulate.

    Args:
        existing: The user's current ``mpv_extra_args``.
        recommended: The engine's recommended cache args.

    Returns:
        A new list: non-cache user args (order preserved) followed by ``recommended``.
    """
    kept = [
        arg for arg in existing
        if not any(arg.startswith(p) for p in _CACHE_ARG_PREFIXES)
    ]
    return kept + list(recommended)


# Plain-language headline per verdict — answers the user's question directly.
_HEADLINES = {
    _diag.HEALTHY: "Stream looks healthy",
    _diag.JITTER: "Connection is jittery — a bigger buffer will help",
    _diag.PROVIDER_LIMITED: "Your provider is the bottleneck",
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
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._channel_name = channel_name
        self._stream_url = stream_url
        self._config = config
        self._executor = executor
        self._player_active = player_active
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
        title.setStyleSheet(_theme.DETAIL_TITLE)
        title.setWordWrap(True)
        layout.addWidget(title)

        if self._player_active:
            warn = QLabel(
                f"{_icons.notification_warning_icon} A stream is currently playing. "
                "Diagnosing may fail on single-connection providers — stop playback "
                "for an accurate result."
            )
            warn.setWordWrap(True)
            warn.setStyleSheet(_theme.DIAG_PLAYING_WARNING)
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
        self._summary.setStyleSheet(_theme.DIAG_SUMMARY)
        layout.addWidget(self._summary)

        # Key metrics block.
        self._metrics = QLabel("")
        self._metrics.setWordWrap(True)
        self._metrics.setStyleSheet(_theme.DIAG_METRICS)
        self._metrics.hide()
        layout.addWidget(self._metrics)

        # Recommended args / saved confirmation.
        self._recommend = QLabel("")
        self._recommend.setWordWrap(True)
        self._recommend.setStyleSheet(_theme.DIAG_RECOMMEND)
        self._recommend.hide()
        layout.addWidget(self._recommend)

        self._saved = QLabel("")
        self._saved.setWordWrap(True)
        self._saved.setStyleSheet(_theme.DIAG_SAVED)
        self._saved.hide()
        layout.addWidget(self._saved)

        # Footer buttons.
        footer = QHBoxLayout()
        self._apply_button = QPushButton("Apply tuning & Save")
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

        metrics = (
            f"Throughput: {_fmt_mbps(result.throughput_mbps)}   "
            f"Bitrate: {_fmt_mbps(result.bitrate_mbps)}"
        )
        if result.baseline_mbps is not None:
            metrics += f"   Baseline: {_fmt_mbps(result.baseline_mbps)}"
        metrics += (
            f"\nHeadroom: {_fmt_ratio(result.headroom_ratio)}   "
            f"Time-to-first-byte: {_fmt_ms(result.ttfb_ms)}"
            f"\nCodec: {_fmt_str(result.codec)}   "
            f"Resolution: {_fmt_str(result.resolution)}"
        )
        self._metrics.setText(metrics)
        self._metrics.show()

        if result.recommended_args:
            self._recommend.setText(
                "Recommended mpv settings: " + " ".join(result.recommended_args)
            )
            self._recommend.show()
            self._apply_button.setEnabled(True)
        else:
            self._recommend.setText("No tuning changes recommended.")
            self._recommend.show()
            self._apply_button.setEnabled(False)

    # ------------------------------------------------------------------ #
    # Apply tuning                                                         #
    # ------------------------------------------------------------------ #

    def _on_apply(self) -> None:
        """Merge recommended args into config.mpv_extra_args and persist."""
        if not self._result or not self._result.recommended_args:
            return
        merged = merge_mpv_cache_args(
            list(self._config.mpv_extra_args), self._result.recommended_args
        )
        self._config.mpv_extra_args = merged
        self._config.save()
        logger.info("Applied diagnostic tuning to mpv_extra_args")
        self._saved.setText("Saved — takes effect on the next stream you play.")
        self._saved.show()
        self._apply_button.setEnabled(False)
