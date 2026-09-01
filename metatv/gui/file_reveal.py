"""Open a folder, or reveal a file inside one, in the desktop file manager.

Two functions rather than one, because they are not the same request and
collapsing them would quietly change what a caller gets:

* :func:`open_folder` opens a DIRECTORY. That is "show me where my downloads
  live".
* :func:`reveal_file` opens the directory CONTAINING a file. That is "show me
  this one download" — and it deliberately does not open the file itself,
  which on a video would launch a second player alongside MetaTV's.

``QDesktopServices`` must be called on the main thread, so both of these are
main-thread-only by contract; neither does any I/O beyond a stat.
"""

from __future__ import annotations

import os
from pathlib import Path

from loguru import logger


def _open(path: Path) -> bool:
    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QDesktopServices

    try:
        return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))))
    except Exception:
        # A missing file manager is not worth a traceback in the user's face;
        # the caller shows a status message instead.
        logger.exception("could not open {}", path)
        return False


def open_folder(path: "str | os.PathLike | None") -> bool:
    """Open *path* as a directory. False when it does not exist or will not open.

    Returns False rather than creating the directory: a folder button that
    silently conjures an empty folder is worse than one that says there is
    nothing there yet.
    """
    if not path:
        return False
    p = Path(os.path.expanduser(str(path)))
    if not p.is_dir():
        logger.debug("open_folder: {} is not a directory", p)
        return False
    return _open(p)


def reveal_file(path: "str | os.PathLike | None") -> bool:
    """Open the folder CONTAINING *path*. False when the file is gone.

    The file existing is the point of the check, not a nicety: downloads are
    deleted outside the app, and *Catch, Keep, Record* is explicit that a
    "downloaded" claim must come from a filesystem check rather than a stored
    boolean that goes stale — "same failure as a cache key that outlives its
    input". A reveal that opens an empty folder makes exactly that claim.
    """
    if not path:
        return False
    p = Path(os.path.expanduser(str(path)))
    if not p.exists():
        logger.debug("reveal_file: {} is gone", p)
        return False
    return _open(p.parent)
