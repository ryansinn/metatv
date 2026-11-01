"""Release the main window before the interpreter exits (GUARD-7).

At exit PyQt runs its own handler (``cleanup_on_exit``) that walks every Qt
wrapper it still tracks and deletes each top-level object Python owns. A
live main window is one: deleting it frees hundreds of child wrappers in the
middle of that walk, and the walk then reads a freed one — a segfault (rc -11,
no Python frame, ``cleanup_qobject`` → ``sip_api_get_address``) after all the
real work is done. It grew with the widget count: the Analytics tab's tiles
(#991) took a window boot from 0 to 12 crashes in 16 under load, and the same
boot with the window released first crashed 0 times in 24.

The app's ``main()`` and every test that boots the window in a subprocess end
through :func:`release_before_exit`, so the exit path the tests check is the
one the app takes.
"""

from __future__ import annotations

import sys

from PyQt6 import sip
from PyQt6.QtWidgets import QWidget


def release_before_exit(window: QWidget) -> None:
    """Flush output and delete *window* now, outside PyQt's exit-time walk."""
    sys.stdout.flush()
    sys.stderr.flush()
    if not sip.isdeleted(window):
        sip.delete(window)
