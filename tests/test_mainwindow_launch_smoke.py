"""Launch smoke test — the full ``MainWindow`` constructs without crashing.

Regression guard for a class of bug the rest of the suite could not catch: an
init-ordering crash in ``setup_ui()`` where ``create_content_area()`` wired the
embedded Full-History view's trail-map to ``self._poster_lightbox`` *before*
that attribute was created, so the real app raised ``AttributeError`` on launch
while ``pytest tests/ -q`` stayed green (nothing else boots the window).

Run in a SUBPROCESS: constructing the real ``MainWindow`` spins up ~20 managers
plus background threads, and doing that in-process inside the shared pytest
``QApplication`` both crashes at teardown and destabilises later tests. A child
process isolates all of it — a launch crash (or a segfault) then shows up
cleanly as a non-zero exit this test asserts against. ``HOME`` is pointed at a
tmp dir so the child never touches the real user config (the ``_isolate_user_config``
guarantee, enforced across the process boundary).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("PyQt6")

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Constructs the full window with only the mpv player + async pool stubbed, then
# asserts setup_ui() completed (both trail-maps wired — the exact crash point).
_CHILD = r"""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from pathlib import Path
from unittest.mock import MagicMock

for sub in (".config/metatv", ".local/share/metatv", ".cache/metatv/images"):
    (Path.home() / sub).mkdir(parents=True, exist_ok=True)

from PyQt6.QtWidgets import QApplication
import metatv.gui.main_window as mw

mw.PlayerManager = lambda *a, **k: MagicMock()        # no real mpv process
mw.MainWindow._run_query = lambda self, *a, **k: None  # no background pool

from metatv.core.config import Config

app = QApplication([])
config, _ = Config.load()
win = mw.MainWindow(config)

# setup_ui() ran to completion — the crash was create_content_area() ->
# _connect_trail_map_signals(full_history_view.trail_map) ->
# self._poster_lightbox.show_pixmap, before _poster_lightbox existed.
assert win._poster_lightbox is not None
assert win._trail_map is not None
assert win.full_history_view is not None
assert win.full_history_view.trail_map is not None
print("SMOKE_OK")
"""


def test_mainwindow_launches(tmp_path):
    env = {
        "HOME": str(tmp_path),  # isolate config/data from the real user dirs
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(_REPO_ROOT),  # import THIS checkout's metatv, not a stale install
        "QT_QPA_PLATFORM": "offscreen",
    }
    result = subprocess.run(
        [sys.executable, "-c", _CHILD],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0 and "SMOKE_OK" in result.stdout, (
        f"MainWindow failed to launch (rc={result.returncode}).\n"
        f"--- stdout ---\n{result.stdout[-2000:]}\n"
        f"--- stderr ---\n{result.stderr[-3000:]}"
    )
