"""Which mpv executable to spawn — split out of ``players/mpv.py``.

One question with its own cache, asked by the player, the stream-details probe
and the component-versions report alike.
"""
from __future__ import annotations

import os
import shutil
from typing import Optional

from metatv.core.runtime_env import bundle_resource_path, is_frozen, is_windows

#: Where CI vendors mpv inside a frozen build, relative to the bundle root.
_BUNDLED_MPV = "mpv/mpv.exe" if is_windows() else "mpv/mpv"

# Cached result of _resolve_mpv_binary().  Resolution is stable for a process
# lifetime (frozen-ness, env, and PATH don't change), so resolve once.
_MPV_BINARY_CACHE: Optional[str] = None


def _reset_mpv_binary_cache() -> None:
    """Clear the resolved-mpv cache (test hook — resolution is process-stable)."""
    global _MPV_BINARY_CACHE
    _MPV_BINARY_CACHE = None


def _resolve_mpv_binary() -> str:
    """Resolve the mpv executable to spawn.

    Resolution order (first hit wins), cached after the first call:

    1. **Bundled** ``Resources/mpv/mpv`` (macOS ``.app``) or ``mpv/mpv.exe``
       (Windows folder) when running frozen, so the end user installs nothing.
    2. ``$MPV_BINARY`` env override (a name on ``PATH`` or an absolute path).
    3. ``shutil.which("mpv")`` — the dev/Linux fallback.  This MUST remain so
       running from source and the test suite keep working unchanged.

    Returns:
        The resolved executable path, or the literal ``"mpv"`` as a last resort
        (so a launch still surfaces a clear "not found" error rather than
        passing ``None`` to ``subprocess``).
    """
    global _MPV_BINARY_CACHE
    if _MPV_BINARY_CACHE is not None:
        return _MPV_BINARY_CACHE

    resolved: Optional[str] = None

    # 1. Bundled binary when frozen.
    if is_frozen():
        bundled = bundle_resource_path(_BUNDLED_MPV)
        if bundled.exists():
            resolved = str(bundled)

    # 2. Environment override.
    if resolved is None:
        env_binary = os.environ.get("MPV_BINARY")
        if env_binary and (shutil.which(env_binary) or os.path.exists(env_binary)):
            resolved = env_binary

    # 3. PATH lookup (dev / Linux / any unbundled run).
    if resolved is None:
        which = shutil.which("mpv")
        if which:
            resolved = which

    _MPV_BINARY_CACHE = resolved or "mpv"
    return _MPV_BINARY_CACHE
