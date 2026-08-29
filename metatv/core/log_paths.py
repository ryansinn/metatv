"""Where the logs are — one answer, for every caller.

``__main__.setup_logging`` derived ``<home>/.config/metatv/logs`` inline and
``qa_checklist_window`` derived the same folder a second way, from a ``Config``.
Two definitions of one location is how they drift: the QA one already carried a
docstring promising it "matches ``__main__.setup_logging``", which is the kind
of promise a comment cannot keep.

The split had a real cause, so this module keeps it addressable rather than
pretending it away: ``setup_logging`` runs BEFORE ``Config.load()``, so it has
no config to ask. ``config`` is therefore optional here, and the fallback is the
same default ``Config`` itself uses. ``Path.home()`` is read at call time, never
cached, because ``tests/conftest.py`` patches it to isolate the user's real
config — a module-level constant would be resolved at import and defeat that.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from metatv.core.config import Config

#: The file loguru writes to. Rotated copies sit beside it with a timestamp in
#: the name; this is always the live one.
ACTIVE_LOG_NAME = "metatv.log"


def config_directory(config: "Optional[Config]" = None) -> Path:
    """Return the config directory, from *config* when there is one.

    Args:
        config: The loaded config, or None before it exists.

    Returns:
        The directory holding ``config.yaml``.
    """
    cdir = getattr(config, "config_dir", None) if config is not None else None
    if cdir is None:
        return Path.home() / ".config" / "metatv"
    return Path(cdir)


def log_directory(config: "Optional[Config]" = None, *, create: bool = False) -> Path:
    """Return ``<config_dir>/logs`` — where every log file lives.

    Args:
        config: The loaded config, or None.
        create: Create the directory if it is missing.

    Returns:
        The log directory.
    """
    d = config_directory(config) / "logs"
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def active_log_file(config: "Optional[Config]" = None) -> Path:
    """Return the log file loguru is currently writing.

    Args:
        config: The loaded config, or None.

    Returns:
        Path to ``metatv.log`` (which need not exist yet).
    """
    return log_directory(config) / ACTIVE_LOG_NAME


def all_log_files(config: "Optional[Config]" = None) -> list[Path]:
    """Return every log file, newest first.

    Rotation leaves timestamped siblings behind, and "clear the logs" has to
    mean all of them — 330 MB of the owner's disk was rotated copies, not the
    active file.

    Args:
        config: The loaded config, or None.

    Returns:
        Log files sorted newest-first; empty when the directory is missing.
    """
    d = log_directory(config)
    if not d.is_dir():
        return []
    try:
        return sorted(d.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:  # silent: a log we cannot stat is a log we cannot offer;
        # the caller renders an empty list, which is the honest answer.
        return []
