"""Runtime build/checkout identity for the window title.

Single source of truth for "which code is this?" — the short commit, whether the
tree is dirty, and (when launched via ``run.sh <PR#>``) the PR number. Kept free
of Qt so the main window can call it at startup.

The PR number is never handed to the process (``run.sh`` strips it and sets no
env var); the only reliable signal is the checkout's directory basename, which
``run.sh <PR#>`` sets to ``<repo>-pr-<PR#>``.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


def repo_dir() -> Path:
    """Root of the *running* checkout (the worktree, not the user's CWD).

    ``__file__`` is ``<repo>/metatv/core/build_info.py`` → ``parents[2]`` is the
    repo root. Under ``run.sh <PR#>`` this is ``<repo>-pr-<PR#>``, whose basename
    encodes the PR number.
    """
    return Path(__file__).resolve().parents[2]


def _git(*args: str) -> str:
    """Run a git command in the running checkout; return stdout or "" on failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
            cwd=str(repo_dir()),
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _pr_number() -> str:
    """PR number from the ``run.sh`` worktree dir name (``…-pr-<N>``), else ""."""
    match = re.search(r"-pr-(\d+)$", repo_dir().name)
    return match.group(1) if match else ""


def build_id() -> str:
    """Return the stamped build identifier, or "" when this isn't a CI build.

    The release workflow writes ``metatv/_build_id.py`` just before PyInstaller
    runs, so a packaged app can say exactly which code it is. That matters more
    under rolling releases than it did under version tags: "0.25.0" no longer
    distinguishes two builds a week apart, but ``0.25.0+20260803.a3e7a28``
    does — and a bug report naming it can be checked out directly.

    A development checkout has no such file and falls back to git, which is
    strictly better information when it's available.
    """
    try:
        from metatv import _build_id  # type: ignore[attr-defined]

        return str(getattr(_build_id, "BUILD_ID", "") or "")
    except Exception:
        return ""


def compose_title(
    sha: str,
    dirty: bool,
    pr: str,
    branch: str,
    version: str | None = None,
) -> str:
    """Build the window title from git facts (pure — the unit-testable core).

    Args:
        sha: Short commit hash, or "" when git info is unavailable.
        dirty: True when the working tree has uncommitted changes.
        pr: PR number as a string, or "" when not running a PR checkout.
        branch: Current branch name; "HEAD" when detached.
        version: Release version (used as fallback when sha is empty).
            Defaults to metatv.__version__ if not provided.

    Returns:
        - ``"MetaTV <version>"`` when *sha* is empty (no git).
        - ``"MetaTV (<sha>[*] PR#<pr>)"`` when a PR number is known.
        - ``"MetaTV (<branch> <sha>[*])"`` on a named branch with no PR.
        - ``"MetaTV (<sha>[*])"`` when detached with no PR.
    """
    if not sha:
        # No git — this is a packaged app. Prefer the stamped build id, which
        # identifies the exact commit; fall back to the bare version only when
        # nothing stamped it (a local PyInstaller run, say).
        if version is None:
            version = build_id()
        if not version:
            import metatv

            version = metatv.__version__
        return f"MetaTV {version}"
    commit = f"{sha}*" if dirty else sha
    if pr:
        return f"MetaTV ({commit} PR#{pr})"
    if branch and branch != "HEAD":
        return f"MetaTV ({branch} {commit})"
    return f"MetaTV ({commit})"


def window_title() -> str:
    """Compose the main-window title from the running checkout's git identity.

    Computed once at startup; a testing/debug session doesn't commit mid-run.
    """
    sha = _git("rev-parse", "--short", "HEAD")
    # Only tracked-file modifications count as "dirty" — untracked noise (a borrowed
    # venv symlink, logs, scratch files) must not falsely flag the pristine commit.
    dirty = bool(_git("status", "--porcelain", "--untracked-files=no"))
    pr = _pr_number()
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    return compose_title(sha, dirty, pr, branch)
