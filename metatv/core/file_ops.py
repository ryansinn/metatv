"""Replacing, writing and deleting files the same way on every platform.

POSIX lets a program rename over, replace or delete a file that another process
has open; Windows refuses with ``PermissionError`` (a sharing violation). That
bites in two ways:

* **Briefly**, after any write: antivirus scanners and the search indexer open
  a freshly closed file for a moment. :func:`replace` retries that window, so a
  finished download or a settings save does not fail on it.
* **For as long as the other program holds it**: mpv playing a downloaded file
  or writing its deep-cache recording. Retrying cannot help, so :func:`remove`
  reports "in use" (False) and the caller decides — tell the user, or leave it
  for a later sweep.

On Linux and macOS both behave exactly like the plain calls.
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import IO, Callable

from metatv.core import runtime_env

#: How long :func:`replace` keeps retrying a sharing violation on Windows.
_WINDOWS_REPLACE_ATTEMPTS = 10
_WINDOWS_REPLACE_DELAY_S = 0.05


def replace(src: "str | os.PathLike", target: "str | os.PathLike") -> None:
    """``os.replace(src, target)``, retrying a transient Windows sharing violation.

    Raises:
        OSError: The replace failed (on Windows, still locked after ~0.5 s).
    """
    if not runtime_env.is_windows():
        os.replace(src, target)
        return
    for attempt in range(_WINDOWS_REPLACE_ATTEMPTS):
        try:
            os.replace(src, target)
            return
        except PermissionError:
            if attempt == _WINDOWS_REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(_WINDOWS_REPLACE_DELAY_S)


def remove(path: "str | os.PathLike") -> bool:
    """Delete *path* if it exists.

    Returns:
        True when the file is gone (deleted, or was never there); False when
        another process holds it open, which only Windows refuses.

    Raises:
        OSError: Any other failure, including a real permission problem.
    """
    try:
        Path(path).unlink(missing_ok=True)
        return True
    except PermissionError:
        if runtime_env.is_windows():
            return False
        raise


def atomic_write(target: "str | os.PathLike", write: "Callable[[IO[str]], None]", *,
                 suffix: str = ".tmp") -> None:
    """Write a text file through a temp file in the same folder and a replace.

    A reader never sees a half-written file, and a crash mid-write leaves the
    old one intact. UTF-8 and ``\\n`` line endings explicitly, so the file is
    byte-identical on every platform — including a source checkout on Windows,
    which does not run in UTF-8 mode the way the packaged app does.

    Args:
        target: The file to create or overwrite.
        write: Called with the open temp file; writes the content.
        suffix: The temp file's suffix.

    Raises:
        Exception: Whatever *write* or the replace raised; the temp file is
            removed first.
    """
    target = Path(target)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=target.parent, delete=False, suffix=suffix) as tmp:
            tmp_path = Path(tmp.name)
            write(tmp)
        replace(tmp_path, target)
    except BaseException:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass  # best-effort cleanup of a temp file we are already abandoning
        raise
