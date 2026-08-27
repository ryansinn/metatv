"""Runtime environment helpers — frozen (PyInstaller/.app) vs source checkout.

Single source of truth for two questions asked in more than one place:

* "Are we running inside a bundled application?" (``is_frozen``)
* "Where does a bundled resource live?" (``bundle_resource_path``)

Shared by the mpv-binary resolver (``core/players/mpv.py``) and the in-app
update checker (``core/update_checker.py``).  Keeping both here means the
frozen-vs-dev branching logic exists once, not copy-pasted per consumer.
"""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    """Return ``True`` when running from a PyInstaller (or similar) bundle.

    PyInstaller sets ``sys.frozen = True`` on the interpreter it embeds; a
    normal source checkout leaves the attribute absent.
    """
    return bool(getattr(sys, "frozen", False))


def bundle_resource_path(rel: str) -> Path:
    """Resolve *rel* to an absolute path to a bundled resource.

    **Frozen** (``.app`` / one-dir bundle): resources may live either where
    PyInstaller extracts them (``sys._MEIPASS``) or, for a macOS ``.app``, in
    ``Contents/Resources`` (a sibling of the ``Contents/MacOS`` executable dir).
    We probe, in order, ``_MEIPASS/<rel>`` → ``<exe_dir>/<rel>`` →
    ``<exe_dir>/../Resources/<rel>`` and return the first that exists, falling
    back to the first candidate as a best guess.

    **Source checkout**: resolves *rel* against the repository root (two levels
    up from ``metatv/core/runtime_env.py``).

    Args:
        rel: Bundle-relative resource path, e.g. ``"mpv/mpv"``.

    Returns:
        An absolute :class:`~pathlib.Path` (existence not guaranteed — callers
        that care should check ``.exists()``).
    """
    rel_path = Path(rel)

    if is_frozen():
        candidates: list[Path] = []
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / rel_path)
        try:
            exe_dir = Path(sys.executable).resolve().parent
            candidates.append(exe_dir / rel_path)
            candidates.append(exe_dir.parent / "Resources" / rel_path)
        except (OSError, ValueError):  # pragma: no cover — sys.executable is set
            pass  # silent: this path is one candidate of several; the loop tries the rest
        for cand in candidates:
            if cand.exists():
                return cand
        return candidates[0] if candidates else rel_path.resolve()

    # Source checkout: repo root is two parents up from this package file.
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / rel_path
