"""Starting helper programs (mpv, ffmpeg, git) from a windowed app.

On Windows a GUI app that starts a console program gets a console window
flashing up for it — for every property query, probe and version check. Every
``subprocess`` call in the app passes ``**NO_WINDOW``; it is empty elsewhere, so
Linux and macOS launch exactly as before. ``CREATE_NO_WINDOW`` only suppresses
a console: mpv's own video window is unaffected.

Guard: ``tests/test_child_process_no_window.py`` fails on a call without it.
"""

from __future__ import annotations

import subprocess
import sys

NO_WINDOW: dict = (
    {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
)
