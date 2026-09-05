"""THEME-1 benchmark: per-pass timing of a live ``apply_theme()`` switch on a
large offscreen widget tree.

Deliberately NOT named ``test_*.py`` — pytest's default collection
(``test_*.py`` / ``*_test.py``) never picks this up, so it never runs as part
of the suite (``scripts/pytest_verdict.sh`` / CI). Run it directly:

    QT_QPA_PLATFORM=offscreen venv/bin/python tests/bench_theme_switch.py

Builds ~3,000 widgets — 1,500 registered via ``theme.style()``, 500 with a
composed f-string sheet containing palette values (a bare ``setStyleSheet``,
the pre-registry population ``_rewrite_stale_palette_values`` exists for),
1,000 plain (no stylesheet at all, themed only by the QPalette floor) — then
times ``apply_theme("Daylight")`` -> ``apply_theme("Midnight")`` three times
each and prints the per-pass medians ``_apply_theme_locked`` now logs.
"""

from __future__ import annotations

import os
import re
import statistics
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import loguru  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel, QMainWindow  # noqa: E402

from metatv.gui import theme  # noqa: E402

REGISTERED_COUNT = 1500
COMPOSED_COUNT = 500
PLAIN_COUNT = 1000
REPEATS = 3

_LOG_RE = re.compile(
    r"palette (?P<palette>[\d.]+) ms · registered (?P<registered>[\d.]+) ms/"
    r"(?P<registered_n>\d+) widgets · rewrite (?P<rewrite>[\d.]+) ms/"
    r"(?P<rewrite_n>\d+) sheets · repolish (?P<repolish>[\d.]+) ms/"
    r"(?P<repolish_n>\d+) widgets · total (?P<total>[\d.]+) ms"
)


def _build_tree(parent) -> None:
    for _ in range(REGISTERED_COUNT):
        theme.style(QLabel("x", parent), "SECTION_HINT")
    for _ in range(COMPOSED_COUNT):
        lbl = QLabel("x", parent)
        lbl.setStyleSheet(
            f"color: {theme.COLOR_MUTED}; background: {theme.COLOR_BG_SECTION};"
        )
    for _ in range(PLAIN_COUNT):
        QLabel("x", parent)


def main() -> None:
    app = QApplication.instance() or QApplication([])
    theme.apply_theme("Midnight")
    win = QMainWindow()
    _build_tree(win)
    win.show()

    samples: list[dict[str, float]] = []

    def _sink(message) -> None:
        m = _LOG_RE.search(message.record["message"])
        if m:
            samples.append({k: float(v) for k, v in m.groupdict().items()})

    sink_id = loguru.logger.add(_sink, level="DEBUG")
    try:
        for _ in range(REPEATS):
            theme.apply_theme("Daylight")
            theme.apply_theme("Midnight")
    finally:
        loguru.logger.remove(sink_id)

    win.close()
    app.processEvents()

    cols = ("palette", "registered", "rewrite", "repolish", "total")
    medians = {c: statistics.median(s[c] for s in samples) for c in cols}
    counts = {
        "registered_n": int(samples[0]["registered_n"]),
        "rewrite_n": int(samples[0]["rewrite_n"]),
        "repolish_n": int(samples[0]["repolish_n"]),
    }

    print(f"{len(samples)} switches sampled ({REGISTERED_COUNT + COMPOSED_COUNT + PLAIN_COUNT} widgets)")
    print(f"{'pass':<12}{'median ms':>12}{'items':>10}")
    print(f"{'palette':<12}{medians['palette']:>12.1f}{'':>10}")
    print(f"{'registered':<12}{medians['registered']:>12.1f}{counts['registered_n']:>10}")
    print(f"{'rewrite':<12}{medians['rewrite']:>12.1f}{counts['rewrite_n']:>10}")
    print(f"{'repolish':<12}{medians['repolish']:>12.1f}{counts['repolish_n']:>10}")
    print(f"{'total':<12}{medians['total']:>12.1f}{'':>10}")


if __name__ == "__main__":
    main()
