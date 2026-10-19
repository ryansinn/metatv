"""Where MetaTV keeps things on disk — one answer per location, per platform.

Before this module the same folders were spelled out by hand in about ten
places (``Path.home() / ".config" / "metatv"`` in ``Config``, ``Config.load``,
``log_paths``, ``special_content``, the QA window; ``~/.cache/metatv/...`` in
three config defaults and the IDF corpus; ``~/Videos/MetaTV`` four times), and
``~`` was expanded three different ways. Every one of them assumed a Unix
layout, so a Windows build would have scattered dot-folders into the user's
profile.

**Linux and macOS keep exactly the paths they always had** — moving a user's
database to a more idiomatic folder buys nothing and risks their data. Windows
gets its native roaming/local split. Nothing here is machine-wide: every path
is under the current user.

Every function reads ``Path.home()`` at call time, never at import, because
``tests/conftest.py`` patches it to isolate the user's real config.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from metatv.core import runtime_env

APP_DIR_NAME = "metatv"


def _windows_base(env_var: str, fallback: str) -> Path:
    """``%APPDATA%`` / ``%LOCALAPPDATA%``, else the documented default under home."""
    value = os.environ.get(env_var)
    return Path(value) if value else Path.home() / "AppData" / fallback


def config_dir() -> Path:
    """The folder holding ``config.yaml`` (and logs, QA notes, user overrides)."""
    if runtime_env.is_windows():
        return _windows_base("APPDATA", "Roaming") / "MetaTV"
    return Path.home() / ".config" / APP_DIR_NAME


def data_dir() -> Path:
    """The folder holding ``metatv.db``."""
    if runtime_env.is_windows():
        return _windows_base("LOCALAPPDATA", "Local") / "MetaTV"
    return Path.home() / ".local" / "share" / APP_DIR_NAME


def cache_dir() -> Path:
    """The root for regenerable data (images, deep-cache scratch, IDF table)."""
    if runtime_env.is_windows():
        return _windows_base("LOCALAPPDATA", "Local") / "MetaTV" / "cache"
    return Path.home() / ".cache" / APP_DIR_NAME


def image_cache_dir() -> Path:
    """Default folder for cached posters and logos."""
    return cache_dir() / "images"


def deep_cache_dir() -> Path:
    """Default scratch folder for deep-cache ``.ts`` recordings."""
    return cache_dir() / "deepcache"


def runtime_dir() -> Path:
    """A per-user scratch folder for short-lived files such as IPC sockets.

    ``$XDG_RUNTIME_DIR`` on Linux is private to the user and cleared at logout,
    unlike ``/tmp``, which every user on the machine shares. Elsewhere the
    system temp dir is already per-user (macOS ``$TMPDIR``, Windows ``%TEMP%``).
    """
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg and os.path.isdir(xdg):
        return Path(xdg)
    return Path(tempfile.gettempdir())


def downloads_dir() -> Path:
    """The user's Downloads folder (where the updater saves a new build)."""
    return Path.home() / "Downloads"


def default_library_dir() -> Path:
    """Default home for saved VOD downloads: the platform's videos folder.

    macOS names it ``Movies``; Linux and Windows name it ``Videos``.
    """
    videos = "Movies" if runtime_env.is_macos() else "Videos"
    return Path.home() / videos / "MetaTV"


def expand_user(raw: "str | os.PathLike") -> Path:
    """Expand a leading ``~`` against ``Path.home()``.

    Deliberately not ``os.path.expanduser``: that reads ``$HOME`` (or
    ``%USERPROFILE%``) directly and so bypasses the ``Path.home()`` patch the
    test suite isolates the user's files with — a test could then sweep or
    write under the developer's real home. ``~user`` forms are left as-is.
    """
    text = str(raw)
    if text == "~":
        return Path.home()
    if text.startswith(("~/", "~" + os.sep)):
        return Path.home() / text[2:]
    return Path(text)
