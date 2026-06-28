"""Dev-only floating QA Testing Checklist window.

Gated by ``METATV_DEV`` environment variable — never constructed or shown
when the gate is closed.  Normal users see zero impact.

The window reads ``test_steps`` from every ``WhatsNewEntry`` in
``metatv.whats_new.WHATS_NEW``, filtering to entries that:
  - have at least one step, AND
  - have ``id > config.qa_verified_id`` (not yet purged), AND
  - have ``id`` not in ``config.qa_archived_ids`` (not individually archived).

Entries are displayed newest-first.  Each entry shows a header with the
title, a clickable PR# link (derived from git off the UI thread), and a
progress fraction ("2/3"), plus a **tri-state** pass / fail affordance per step.

Tri-state per step
------------------
Each step has a ✓ (pass) and ✗ (fail) button.  Clicking sets that state;
clicking the active one again clears back to untested (empty).  State is
persisted in ``config.qa_step_results`` (the consolidated record — see
``Config``).  When a step is marked failed an inline comment box appears
beneath it: a note field that also accepts a pasted clipboard image, plus a
📎 attach button.  Saved screenshots and a tail snapshot of the active log go
to ``<config_dir>/qa_attachments/``; their paths are stored in the record.

Build stamp + re-test nudge
---------------------------
Every mark records the current repo HEAD short sha and an ISO timestamp.  When
a step's stored sha differs from the current HEAD a subtle amber "newer build —
re-test" hint appears next to it.

AI failures digest
------------------
Whenever a mark / note / attachment changes, ``<config_dir>/qa_failures.md`` is
(re)written — a structured Markdown digest of every current failure across open
entries.  This is the file an AI reads to act on the reported bugs.  With zero
failures it says "No failures recorded." (it is never deleted).

Completion
----------
An entry is complete / archivable only when EVERY step is marked **pass**.  Any
failed step keeps the entry open and flags its header red.

Enhancement — PR# links
-----------------------
A single background QThread resolves each open entry's source file → PR number
(``git log``) and derives the GitHub base URL from the remote, then updates the
header labels.  No subprocess runs on the UI thread.

Archived section (collapsible)
------------------------------
Individually-archived entries are shown in a collapsible "Archived (N)" group
at the bottom of the body.  The group is **collapsed by default** (state
``config.qa_archived_collapsed = True``) to avoid horizontal-scroll bulk.
Clicking the toggle button shows/hides the archived rows and persists the state.

Flagged Items section
---------------------
A persistent, open-ended capture section where the tester records observations
that fall outside any specific PR's test_steps.  Items have a title, free-text
notes (with pasted-screenshot capture via ``_FailNoteEdit``), optional
attachments, and an open / triaged status toggle.

Items are persisted in ``config.qa_flagged_items`` (list of dicts).  Whenever
items change the ``<config_dir>/qa_flagged_items.md`` digest is re-written —
the file a future session reads to triage items into tasks/PRs.

Addressed-by-PR linkage
------------------------
A later entry can declare ``addresses=("e82_s4", "flagged:uuid", ...)`` to
announce that its PR fixes a specific prior failure or flagged item.  On the
failing step / open flagged item the window renders:

  ``↺ Addressed in PR #NNN (entry #NNN) — re-test``

…with a jump button (↑) that scrolls to the addressing entry.  The step's state
stays **fail** — auto-pass is explicitly out of scope; the human re-tests and
manually marks pass.  When no forward declaration exists the tester can use the
"Mark addressed" button on the failed step's comment area to persist the same
signal in ``config.qa_addressed`` (string-keyed dict, same "e{id}_s{idx}" /
"flagged:{uuid}" format).  Both paths surface in the ``qa_failures.md`` digest.
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.whats_new import WhatsNewEntry


# ── git helpers (all called off the UI thread) ────────────────────────────────

def _parse_pr_number(subject: str) -> int | None:
    """Extract the PR number from a squash-merge commit subject.

    Squash-merge subjects look like ``"feat(x): thing (#183)"``.

    Args:
        subject: Full commit subject line.

    Returns:
        PR number as an int, or ``None`` if the pattern is absent.
    """
    m = re.search(r'\(#(\d+)\)', subject)
    return int(m.group(1)) if m else None


def _normalize_remote_url(raw: str) -> str:
    """Normalize an SSH or HTTPS git remote URL to an HTTPS GitHub base URL.

    Handles:
    - ``git@github.com:owner/repo.git`` → ``https://github.com/owner/repo``
    - ``https://github.com/owner/repo.git`` → ``https://github.com/owner/repo``

    Args:
        raw: Raw remote URL string from ``git remote get-url origin``.

    Returns:
        HTTPS base URL without trailing ``.git``.
    """
    raw = raw.strip()
    # SSH form: git@github.com:owner/repo.git
    ssh_m = re.match(r'^git@github\.com:(.+?)(?:\.git)?$', raw)
    if ssh_m:
        return f"https://github.com/{ssh_m.group(1)}"
    # HTTPS form: https://github.com/owner/repo.git
    https_m = re.match(r'^(https://github\.com/.+?)(?:\.git)?$', raw)
    if https_m:
        return https_m.group(1)
    # Unknown form — return as-is so the fallback date path triggers
    return raw


def _repo_dir() -> str:
    """Return the repository root directory inferred from this module's path.

    Resolves ``metatv/gui/qa_checklist_window.py`` → repo root (three parents
    up).  Used as the cwd for git invocations so the sha/PR lookups work
    regardless of the process's actual working directory.
    """
    return str(Path(__file__).resolve().parents[2])


def _resolve_head_sha() -> str:
    """Return the current repo HEAD short sha, or ``""`` if git can't be read.

    Runs ``git rev-parse --short HEAD`` off the UI thread (reuses the
    ``_GitRefWorker`` invocation style).  Failures return an empty string so
    the caller falls back gracefully.

    Returns:
        Short commit hash (e.g. ``"a1b2c3d"``) or ``""``.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
            cwd=_repo_dir(),
        )
        return result.stdout.strip()
    except Exception:  # noqa: BLE001
        logger.debug("qa_checklist: could not read HEAD sha")
        return ""


def _resolve_entry_ref(entry_id: int, entries_dir: str) -> dict:
    """Find the git commit / PR that introduced an entry's source file.

    Runs entirely off the UI thread.

    Args:
        entry_id: The WhatsNewEntry id (e.g. 47).
        entries_dir: Absolute path to ``metatv/whats_new/entries/``.

    Returns:
        A dict with keys:
        - ``"pr_number"`` (int | None)
        - ``"commit_hash"`` (str | None)  — short hash, only if no PR found
        Both are ``None`` when the file or git history can't be resolved.
    """
    pattern = os.path.join(entries_dir, f"{entry_id:04d}_*.py")
    matches = glob.glob(pattern)
    if not matches:
        logger.debug("qa_checklist: no source file for entry id={}", entry_id)
        return {"pr_number": None, "commit_hash": None}

    source_file = matches[0]
    try:
        result = subprocess.run(
            [
                "git", "log",
                "--diff-filter=A",    # only the commit that ADDED the file
                "--reverse",
                "--format=%h%x1f%s",  # short hash + FS + subject
                "--",
                source_file,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        first_line = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
        if not first_line:
            return {"pr_number": None, "commit_hash": None}

        short_hash, _, subject = first_line.partition("\x1f")
        pr_number = _parse_pr_number(subject)
        if pr_number:
            return {"pr_number": pr_number, "commit_hash": None}
        return {"pr_number": None, "commit_hash": short_hash.strip() or None}

    except Exception:  # noqa: BLE001
        logger.debug("qa_checklist: git log failed for entry id={}", entry_id)
        return {"pr_number": None, "commit_hash": None}


def _resolve_base_url() -> str | None:
    """Derive the GitHub repo base URL from the git remote.

    Returns:
        HTTPS base URL (e.g. ``"https://github.com/ryansinn/metatv"``),
        or ``None`` if the remote can't be read or isn't a GitHub URL.
    """
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
            cwd=_repo_dir(),
        )
        raw = result.stdout.strip()
        if not raw:
            return None
        normalized = _normalize_remote_url(raw)
        if not normalized.startswith("https://github.com/"):
            return None
        return normalized
    except Exception:  # noqa: BLE001
        logger.debug("qa_checklist: could not read git remote URL")
        return None


# ── config-dir-derived paths (honor test isolation: derive from Config) ───────

def _config_dir(config: "Config") -> Path:
    """Return the directory that ``config.yaml`` lives in.

    Derived from ``config.config_dir`` so test isolation (which monkeypatches
    ``Path.home()``) keeps every QA artefact inside the throwaway tmp dir.
    Falls back to the real default only when ``config_dir`` is absent (e.g. a
    minimal stub) — never a hardcoded ``~`` expansion in the normal path.
    """
    cdir = getattr(config, "config_dir", None)
    if cdir is None:
        cdir = Path.home() / ".config" / "metatv"
    return Path(cdir)


def _attachments_dir(config: "Config") -> Path:
    """Return (and create) ``<config_dir>/qa_attachments/``."""
    d = _config_dir(config) / "qa_attachments"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _log_dir(config: "Config") -> Path:
    """Return ``<config_dir>/logs/`` — where loguru writes ``metatv.log``.

    Matches ``__main__.setup_logging`` (``<config_dir>/logs``).  Derived from
    the config dir so it tracks test isolation.
    """
    return _config_dir(config) / "logs"


def _snapshot_log(config: "Config", entry_id: int, step_idx: int, *, tail: int = 200) -> str:
    """Copy the tail of the most-recent log file into the attachments dir.

    Picks the most-recently-modified ``*.log`` under ``<config_dir>/logs/`` and
    writes its last ``tail`` lines to
    ``<config_dir>/qa_attachments/e{entry}_s{idx}_log.txt``.  Safe to call when
    the log dir is missing or empty (returns ``""``).  Runs disk I/O — call off
    the UI thread.

    Returns:
        Absolute path to the snapshot file, or ``""`` when no log was found /
        an error occurred.
    """
    try:
        log_dir = _log_dir(config)
        if not log_dir.is_dir():
            return ""
        candidates = sorted(
            log_dir.glob("*.log"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            return ""
        src = candidates[0]
        with open(src, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        snippet = "".join(lines[-tail:])
        dest = _attachments_dir(config) / f"e{entry_id}_s{step_idx}_log.txt"
        dest.write_text(snippet, encoding="utf-8")
        return str(dest)
    except Exception:  # noqa: BLE001
        logger.debug("qa_checklist: log snapshot failed e={} s={}", entry_id, step_idx)
        return ""


# ── AI failures digest (Markdown) ─────────────────────────────────────────────

def _build_failures_digest(
    config: "Config",
    open_entries: list,
    git_refs: dict,
    current_sha: str,
    addressed: dict | None = None,
) -> str:
    """Build the Markdown digest of all current failures across *open_entries*.

    For each failed step the digest lists the entry title + id, its PR number
    (from the resolved git refs), the step text, ``tested on <sha> · current
    <HEAD>`` with a stale marker when they differ, the note, attachment paths,
    the log snapshot path, and an addressed badge when the failure has been
    claimed by a newer PR.  When there are no failures the body is a short
    "No failures recorded." note (the file is written, never deleted).

    Args:
        config: App config (read ``qa_step_results``).
        open_entries: The currently-open WhatsNewEntry list.
        git_refs: ``{entry_id: {"pr_number": int|None, ...}}`` from the worker.
        current_sha: The current repo HEAD short sha (``""`` if unresolved).
        addressed: Pre-merged addressed dict mapping string key
            ``"e{id}_s{idx}"`` → ``{"addressing_entry_id": int|None,
            "pr_number": int|None}`` (may also carry ``"pr"`` from manual marks).
            ``None`` means no addressed info.

    Returns:
        The full Markdown document as a string.
    """
    results = config.qa_step_results or {}
    addressed = addressed or {}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    fail_blocks: list[str] = []
    fail_count = 0
    for entry in open_entries:
        ent_results = results.get(str(entry.id), {})
        steps = list(entry.test_steps)
        for idx, step in enumerate(steps):
            rec = ent_results.get(str(idx))
            if not rec or rec.get("state") != "fail":
                continue
            fail_count += 1
            pr_number = (git_refs.get(entry.id) or {}).get("pr_number")
            pr_str = f"PR #{pr_number}" if pr_number else "PR unknown"
            tested_sha = rec.get("sha") or "?"
            stale = bool(
                current_sha and tested_sha not in ("", "?") and tested_sha != current_sha
            )
            stale_marker = "  ⚠ STALE — re-test" if stale else ""
            note = (rec.get("note") or "").strip() or "_(no note)_"
            attachments = rec.get("attachments") or []
            log_path = rec.get("log") or ""

            # Addressed-by-PR status — check the pre-merged index.
            addr_key = f"e{entry.id}_s{idx}"
            addr_info = addressed.get(addr_key)
            if addr_info:
                addr_pr = addr_info.get("pr_number") or addr_info.get("pr")
                addr_eid = addr_info.get("addressing_entry_id") or addr_info.get("entry_id")
                parts = ["↺ Addressed"]
                if addr_pr:
                    parts.append(f"in PR #{addr_pr}")
                if addr_eid:
                    parts.append(f"(entry #{addr_eid})")
                parts.append("— re-test pending")
                addr_status = " ".join(parts)
            else:
                addr_status = "open — not yet addressed"

            lines = [
                f"### {entry.title} (entry {entry.id}, {pr_str})",
                "",
                f"- **Step {idx + 1}:** {step}",
                f"- **Status:** {addr_status}",
                f"- tested on `{tested_sha}` · current `{current_sha or '?'}`{stale_marker}",
                f"- **Note:** {note}",
            ]
            if attachments:
                lines.append("- **Screenshots:**")
                lines.extend(f"    - `{p}`" for p in attachments)
            else:
                lines.append("- **Screenshots:** none")
            lines.append(f"- **Log snapshot:** {('`' + log_path + '`') if log_path else 'none'}")
            lines.append("")
            fail_blocks.append("\n".join(lines))

    header = [
        "# QA Failures Digest",
        "",
        f"_Generated {now} · {fail_count} failure(s) · current build `{current_sha or '?'}`_",
        "",
    ]
    if fail_count == 0:
        return "\n".join(header + ["No failures recorded.", ""])
    return "\n".join(header + fail_blocks)


def _write_failures_digest(
    config: "Config",
    open_entries: list,
    git_refs: dict,
    current_sha: str,
    addressed: dict | None = None,
) -> str:
    """Render and write ``<config_dir>/qa_failures.md``; return its path.

    Always writes the file (even with zero failures — never deleted).  Errors
    are logged and swallowed; an empty string is returned on failure.
    """
    try:
        text = _build_failures_digest(
            config, open_entries, git_refs, current_sha, addressed=addressed
        )
        dest = _config_dir(config) / "qa_failures.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        return str(dest)
    except Exception:  # noqa: BLE001
        logger.debug("qa_checklist: failed to write failures digest")
        return ""


# ── flagged items digest (Markdown) ──────────────────────────────────────────

def _build_flagged_digest(config: "Config", addressed: dict | None = None) -> str:
    """Build the Markdown digest of all tester-flagged items.

    Each item lists its title, note, attachment paths, build_sha, timestamp,
    status, and an addressed badge when the item has been claimed by a newer PR.
    The header explains these are tester-flagged observations queued for triage
    into tasks/PRs.  When there are no items the body is a short "No flagged
    items." note (the file is written, never deleted).

    Args:
        config: App config (reads ``qa_flagged_items``).
        addressed: Pre-merged addressed dict mapping ``"flagged:{item_id}"``
            keys → addressed info.  ``None`` means no addressed info available.

    Returns:
        The full Markdown document as a string.
    """
    items: list[dict] = getattr(config, "qa_flagged_items", []) or []
    addressed = addressed or {}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    header = [
        "# QA Flagged Items",
        "",
        "_Tester-flagged observations queued for triage into tasks/PRs._",
        "",
        f"_Generated {now} · {len(items)} item(s)_",
        "",
    ]

    if not items:
        return "\n".join(header + ["No flagged items.", ""])

    blocks: list[str] = []
    for item in items:
        status = item.get("status", "open")
        item_type = item.get("type", "bug")
        title = item.get("title", "").strip() or "_(untitled)_"
        note = (item.get("note", "") or "").strip() or "_(no note)_"
        sha = item.get("build_sha", "") or "?"
        created = item.get("created", "") or "?"
        attachments = item.get("attachments") or []
        last_retested = item.get("last_retested") or ""

        # Addressed-by-PR status for this flagged item.
        item_id = item.get("id", "")
        addr_info = addressed.get(f"flagged:{item_id}") if item_id else None
        if addr_info:
            addr_pr = addr_info.get("pr_number") or addr_info.get("pr")
            addr_eid = addr_info.get("addressing_entry_id") or addr_info.get("entry_id")
            parts = ["↺ Addressed"]
            if addr_pr:
                parts.append(f"in PR #{addr_pr}")
            if addr_eid:
                parts.append(f"(entry #{addr_eid})")
            parts.append("— re-test pending")
            display_status = " ".join(parts)
        else:
            display_status = status

        lines = [
            f"### [{item_type.upper()}] {title}",
            "",
            f"- **Type:** {item_type}",
            f"- **Status:** {display_status}",
            f"- **Flagged:** `{created}` on build `{sha}`",
        ]
        if last_retested:
            lines.append(f"- **Last re-reviewed:** `{last_retested}`")
        lines += [
            f"- **Note:** {note}",
        ]
        if attachments:
            lines.append("- **Screenshots:**")
            lines.extend(f"    - `{p}`" for p in attachments)
        else:
            lines.append("- **Screenshots:** none")
        lines.append("")
        blocks.append("\n".join(lines))

    return "\n".join(header + blocks)


def _write_flagged_digest(config: "Config", addressed: dict | None = None) -> str:
    """Render and write ``<config_dir>/qa_flagged_items.md``; return its path.

    Always writes the file (even with zero items — never deleted).  Errors are
    logged and swallowed; an empty string is returned on failure.
    """
    try:
        text = _build_flagged_digest(config, addressed=addressed)
        dest = _config_dir(config) / "qa_flagged_items.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        return str(dest)
    except Exception:  # noqa: BLE001
        logger.debug("qa_checklist: failed to write flagged items digest")
        return ""


# ── background workers ────────────────────────────────────────────────────────

class _GitRefWorker(QThread):
    """Off-thread worker that resolves PR# / commit hash for each open entry.

    Emits ``refs_ready`` on the main thread when all entries have been
    resolved.  Failures are silently swallowed; the UI falls back to the
    entry date.

    Signals:
        refs_ready: Emits a dict mapping entry_id (int) → ref_info dict
            with keys ``"pr_number"`` (int|None), ``"commit_hash"`` (str|None),
            and ``"base_url"`` (str|None).
    """

    refs_ready = pyqtSignal(object)  # dict[int, dict]

    def __init__(self, entry_ids: list[int], entries_dir: str) -> None:
        super().__init__()
        self._entry_ids = entry_ids
        self._entries_dir = entries_dir

    def run(self) -> None:
        base_url = _resolve_base_url()
        results: dict[int, dict] = {}
        for eid in self._entry_ids:
            ref = _resolve_entry_ref(eid, self._entries_dir)
            ref["base_url"] = base_url
            results[eid] = ref
            logger.debug(
                "qa_checklist: entry id={} → pr={} hash={} base={}",
                eid, ref["pr_number"], ref["commit_hash"], base_url,
            )
        self.refs_ready.emit(results)


class _HeadShaWorker(QThread):
    """Off-thread worker that resolves the current repo HEAD short sha once.

    Signals:
        sha_ready: Emits the short sha string (``""`` if unresolved).
    """

    sha_ready = pyqtSignal(str)

    def run(self) -> None:
        self.sha_ready.emit(_resolve_head_sha())


class _LogSnapshotWorker(QThread):
    """Off-thread worker that copies the active log tail for a failed step.

    Signals:
        snapshot_ready: Emits ``(entry_id, step_idx, path)``; ``path`` is ``""``
            when no log was captured.
    """

    snapshot_ready = pyqtSignal(int, int, str)

    def __init__(self, config: "Config", entry_id: int, step_idx: int) -> None:
        super().__init__()
        self._config = config
        self._entry_id = entry_id
        self._step_idx = step_idx

    def run(self) -> None:
        path = _snapshot_log(self._config, self._entry_id, self._step_idx)
        self.snapshot_ready.emit(self._entry_id, self._step_idx, path)


# ── fail-note editor (handles pasted clipboard images) ────────────────────────

class _FailNoteEdit(QPlainTextEdit):
    """A plain-text note box that captures a pasted clipboard image.

    On Ctrl+V / paste, if the clipboard holds an image it is saved to PNG (via
    the owning window's main-thread handler) instead of being dropped; plain
    text paste behaves normally.

    Signals:
        image_pasted: Emits a ``QImage`` when an image is pasted.
        text_committed: Emits the current plain text whenever it changes.
    """

    image_pasted = pyqtSignal(object)   # QImage
    text_committed = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.textChanged.connect(lambda: self.text_committed.emit(self.toPlainText()))

    def insertFromMimeData(self, source) -> None:  # noqa: N802 (Qt override)
        """Intercept paste: route an image to the save handler, else paste text."""
        clip = QApplication.clipboard().mimeData()
        if source.hasImage() or (clip is not None and clip.hasImage()):
            mime = source if source.hasImage() else clip
            img = mime.imageData()
            if isinstance(img, QImage) and not img.isNull():
                self.image_pasted.emit(img)
                return
        super().insertFromMimeData(source)


# ── main window ───────────────────────────────────────────────────────────────

class QAChecklistWindow(QWidget):
    """Floating, always-on-top dev QA checklist window.

    Args:
        config: App config instance (read/write for persistence).
        entries: Full ``WHATS_NEW`` list; filtered inside ``__init__``.
        parent: Parent widget (MainWindow); child destruction is automatic.
    """

    def __init__(
        self,
        config: "Config",
        entries: list["WhatsNewEntry"],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._config = config
        self._all_entries = entries  # full list; re-filter on each refresh
        # entry_id → {step_idx: (pass_btn, fail_btn)}
        self._step_buttons: dict[int, dict[int, tuple[QPushButton, QPushButton]]] = {}
        self._note_edits: dict[tuple[int, int], _FailNoteEdit] = {}
        self._ref_labels: dict[int, QLabel] = {}           # entry_id → header ref label
        self._git_refs: dict[int, dict] = {}               # entry_id → resolved ref info
        self._git_worker: _GitRefWorker | None = None
        self._sha_worker: _HeadShaWorker | None = None
        self._log_workers: list[_LogSnapshotWorker] = []   # keep refs alive until done
        self._current_sha: str = ""
        # Addressed-by-PR reverse index: built from entries' addresses= declarations.
        # Maps (entry_id: int, step_idx: int) → {"addressing_entry_id": int, "pr_number": int|None}
        # or "flagged:{item_id}" str → same shape.
        self._addressed_index: dict = {}
        # Archived section collapse: toggle button + container (rebuilt on refresh)
        self._archived_toggle_btn: QPushButton | None = None
        self._archived_container: QWidget | None = None
        # Flagged items: item_id → (title_edit, note_edit, status_btn, remove_btn,
        #                            attachments_container_layout)
        self._flagged_note_edits: dict[str, _FailNoteEdit] = {}
        self._flagged_title_edits: dict[str, QLineEdit] = {}
        # Flagged section container (rebuilt on refresh; stored for section-order tests)
        self._flagged_container: QWidget | None = None
        # Resolved sub-section container (addressed flags auto-file here; None when empty)
        self._resolved_container: QWidget | None = None

        self.setWindowTitle("Testing Checklist")
        self.setMinimumWidth(560)
        self.setMinimumHeight(200)
        self.resize(720, 600)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── header bar ────────────────────────────────────────────────────────
        header_bar = QWidget()
        header_bar.setStyleSheet(
            f"background: {_theme.COLOR_BG_BAR};"
            f" border-bottom: 1px solid {_theme.COLOR_LINE};"
        )
        hbar_layout = QHBoxLayout(header_bar)
        hbar_layout.setContentsMargins(12, 8, 12, 8)

        icon_label = QLabel(_icons.qa_checklist_icon)
        icon_label.setStyleSheet(f"font-size: {_theme.FONT_2XL};")
        hbar_layout.addWidget(icon_label)

        title_label = QLabel("Testing Checklist")
        title_label.setStyleSheet(
            f"font-size: {_theme.FONT_LG}; font-weight: bold;"
            f" color: {_theme.COLOR_TEXT};"
        )
        hbar_layout.addWidget(title_label, stretch=1)

        self._purge_btn = QPushButton(f"{_icons.qa_purge_icon}  Mark all done")
        self._purge_btn.setToolTip(
            "Clear all passed items — advances the verified cursor so these"
            " entries no longer appear.  Entries with failures are kept."
        )
        self._purge_btn.setEnabled(False)
        self._purge_btn.setStyleSheet(_theme.PANEL_BTN)
        self._purge_btn.clicked.connect(self._on_purge)
        hbar_layout.addWidget(self._purge_btn)

        root.addWidget(header_bar)

        # ── scrollable body ───────────────────────────────────────────────────
        scroll = QScrollArea()
        # Store reference so handlers can preserve scroll position across rebuilds.
        self._scroll = scroll
        scroll.setWidgetResizable(True)
        # Never scroll horizontally — fail-note boxes / step rows wrap to the
        # viewport width instead of forcing a horizontal scrollbar or a resize.
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(12, 12, 12, 12)
        self._body_layout.setSpacing(0)

        scroll.setWidget(self._body)
        root.addWidget(scroll, stretch=1)

        self._refresh()
        self._start_git_lookup()
        self._start_sha_lookup()
        # Write initial digests so the files always reflect current state.
        self._write_digest()
        _write_flagged_digest(self._config, addressed={})

    # ── public ───────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Re-read config and redraw the checklist (e.g. after a purge)."""
        self._refresh()

    # ── scroll-preserving rebuild ─────────────────────────────────────────────

    def _refresh_preserving_scroll(self) -> None:
        """Rebuild the body while restoring the vertical scroll position.

        Captures the scrollbar value, rebuilds, then restores it **synchronously**
        after forcing a layout pass — followed by a deferred restore as a backstop.

        The synchronous restore matters for the Re-test path: it kicks off an
        async log snapshot whose completion fires a *second*
        ``_refresh_preserving_scroll``.  With a deferred-only restore, that second
        pass could read (and re-save) the scroll value while the first restore was
        still pending — capturing the post-rebuild ``0`` and snapping to the top.
        Forcing the rebuilt body's layout (``activate()``) makes the scrollbar
        range valid so the immediate ``setValue`` actually sticks instead of being
        clamped to a stale maximum.
        """
        scrollbar = self._scroll.verticalScrollBar()
        saved = scrollbar.value()
        self._refresh()
        # Force the rebuilt body to compute its real height so the scrollbar range
        # is valid for an immediate, synchronous restore (defeats both the
        # clamp-to-top and the async-retest re-save race).
        body_layout = self._body.layout()
        if body_layout is not None:
            body_layout.activate()
        scrollbar.setValue(saved)
        # Backstop for any geometry update still deferred to the next tick.
        QTimer.singleShot(0, lambda v=saved: scrollbar.setValue(v))

    # ── per-step record access ────────────────────────────────────────────────

    def _step_record(self, entry_id: int, step_idx: int) -> dict | None:
        """Return the stored record dict for a step, or ``None`` if untested."""
        return (self._config.qa_step_results.get(str(entry_id)) or {}).get(str(step_idx))

    def _step_state(self, entry_id: int, step_idx: int) -> str | None:
        """Return ``"pass"`` / ``"fail"`` / ``None`` (untested) for a step."""
        rec = self._step_record(entry_id, step_idx)
        return rec.get("state") if rec else None

    def _write_step_record(self, entry_id: int, step_idx: int, record: dict | None) -> None:
        """Persist (or clear) a step's record in ``qa_step_results`` and save.

        Assigns a *new* nested dict so Pydantic sees the mutation; passing
        ``None`` removes the step (and the entry key when it empties).
        """
        results = {
            k: dict(v) for k, v in (self._config.qa_step_results or {}).items()
        }
        ent = dict(results.get(str(entry_id), {}))
        if record is None:
            ent.pop(str(step_idx), None)
        else:
            ent[str(step_idx)] = record
        if ent:
            results[str(entry_id)] = ent
        else:
            results.pop(str(entry_id), None)
        self._config.qa_step_results = results
        self._config.save()

    # ── private helpers ───────────────────────────────────────────────────────

    def _open_entries(self) -> list:
        """Return entries with test_steps that haven't been purged or archived.

        Excludes:
        - Entries with no test_steps.
        - Entries with id <= qa_verified_id (globally purged).
        - Entries whose id is in qa_archived_ids (individually archived).

        Returns entries newest-first.
        """
        verified = self._config.qa_verified_id
        archived = set(getattr(self._config, "qa_archived_ids", []))
        return sorted(
            (
                e for e in self._all_entries
                if e.test_steps and e.id > verified and e.id not in archived
            ),
            key=lambda e: e.id,
            reverse=True,
        )

    def _archived_entries(self) -> list:
        """Return entries that have been individually archived, newest-first."""
        archived_ids = set(getattr(self._config, "qa_archived_ids", []))
        verified = self._config.qa_verified_id
        return sorted(
            (
                e for e in self._all_entries
                if e.test_steps and e.id > verified and e.id in archived_ids
            ),
            key=lambda e: e.id,
            reverse=True,
        )

    def _entry_pass_count(self, entry) -> int:
        """Return how many of *entry*'s steps are marked pass."""
        return sum(
            1 for i in range(len(entry.test_steps))
            if self._step_state(entry.id, i) == "pass"
        )

    def _entry_has_failure(self, entry) -> bool:
        """Return True when any of *entry*'s steps is marked fail."""
        return any(
            self._step_state(entry.id, i) == "fail"
            for i in range(len(entry.test_steps))
        )

    def _is_entry_complete(self, entry) -> bool:
        """Return True only when EVERY step of *entry* is marked pass."""
        n = len(entry.test_steps)
        return n > 0 and self._entry_pass_count(entry) == n

    def _all_complete(self, open_entries: list) -> bool:
        """Return True when every open entry has all steps passed."""
        return bool(open_entries) and all(
            self._is_entry_complete(e) for e in open_entries
        )

    def _clear_body(self) -> None:
        """Remove all widgets from the body layout."""
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._step_buttons.clear()
        self._note_edits.clear()
        self._ref_labels.clear()
        self._flagged_note_edits.clear()
        self._flagged_title_edits.clear()
        self._archived_toggle_btn = None
        self._archived_container = None
        self._flagged_container = None
        self._resolved_container = None

    def _refresh(self) -> None:
        """Rebuild the body from current config state."""
        # Rebuild the reverse addressed index so step rows see up-to-date info.
        self._addressed_index = self._build_addressed_index()
        self._clear_body()
        open_entries = self._open_entries()

        if not open_entries:
            self._render_empty_state()
            self._purge_btn.setEnabled(False)
        else:
            for entry in open_entries:
                self._render_entry(entry)
                sep = QFrame()
                sep.setFrameShape(QFrame.Shape.HLine)
                sep.setStyleSheet(f"color: {_theme.COLOR_LINE};")
                self._body_layout.addWidget(sep)

            all_done = self._all_complete(open_entries)
            self._purge_btn.setEnabled(all_done)

        # Flagged Items before Archived — active capture is more important for
        # workflow than reviewing what was already individually archived.
        self._render_flagged_section()

        archived = self._archived_entries()
        if archived:
            self._render_archived_section(archived)

        self._body_layout.addStretch(1)

        if self._git_refs:
            self._apply_git_refs(self._git_refs)

    def _render_empty_state(self) -> None:
        """Show a friendly 'nothing to test' message."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 40, 0, 40)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_lbl = QLabel(_icons.qa_all_clear_icon)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet(f"font-size: {_theme.FONT_4XL};")
        layout.addWidget(icon_lbl)

        msg_lbl = QLabel("Nothing to test")
        msg_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg_lbl.setStyleSheet(
            f"font-size: {_theme.FONT_XL}; color: {_theme.COLOR_MUTED}; padding: 8px 0 4px 0;"
        )
        layout.addWidget(msg_lbl)

        sub_lbl = QLabel("All test steps pass or no entries have steps yet.")
        sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub_lbl.setWordWrap(True)
        sub_lbl.setStyleSheet(f"font-size: {_theme.FONT_MD}; color: {_theme.COLOR_FAINT};")
        layout.addWidget(sub_lbl)

        self._body_layout.addWidget(container)

    def _render_entry(
        self,
        entry,
        *,
        archived: bool = False,
        parent_layout: QVBoxLayout | None = None,
    ) -> None:
        """Render one entry block: header + per-step tri-state rows.

        Args:
            entry: The WhatsNewEntry to render.
            archived: When True the entry is rendered in compact read-only form
                inside the archived section (no step rows; Unarchive button only).
            parent_layout: Layout to append widgets to.  Defaults to
                ``self._body_layout`` when ``None``.
        """
        layout = parent_layout if parent_layout is not None else self._body_layout
        n_total = len(entry.test_steps)
        n_pass = self._entry_pass_count(entry)
        has_failure = self._entry_has_failure(entry)
        is_complete = self._is_entry_complete(entry)

        # ── entry header ──────────────────────────────────────────────────────
        header_widget = QWidget()
        header_widget.setContentsMargins(0, 0, 0, 0)
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 10, 0, 6)
        header_layout.setSpacing(6)

        title_lbl = QLabel(entry.title)
        if has_failure and not archived:
            title_lbl.setStyleSheet(_theme.QA_ENTRY_FAILED_TITLE)
        else:
            title_color = (
                _theme.COLOR_MUTED if (is_complete or archived) else _theme.COLOR_TEXT
            )
            title_lbl.setStyleSheet(
                f"font-size: {_theme.FONT_LG}; font-weight: bold; color: {title_color};"
            )
        header_layout.addWidget(title_lbl, stretch=1)

        if has_failure and not archived:
            fail_badge = QLabel(f"{_icons.qa_fail_icon} FAILED")
            fail_badge.setStyleSheet(_theme.QA_FAIL_BADGE)
            header_layout.addWidget(fail_badge)

        ref_lbl = QLabel(entry.date)
        ref_lbl.setStyleSheet(f"font-size: {_theme.FONT_SM}; color: {_theme.COLOR_MUTED_2};")
        ref_lbl.setOpenExternalLinks(True)
        header_layout.addWidget(ref_lbl)
        self._ref_labels[entry.id] = ref_lbl

        if not archived:
            progress_color = _theme.COLOR_OK if is_complete else _theme.COLOR_DIM
            progress_lbl = QLabel(f"{n_pass}/{n_total}")
            progress_lbl.setStyleSheet(
                f"font-size: {_theme.FONT_SM}; color: {progress_color};"
                f" font-weight: bold; padding-left: 4px;"
            )
            header_layout.addWidget(progress_lbl)

            # Archive only when every step passes (no failures).
            if is_complete:
                archive_btn = QPushButton(f"{_icons.qa_archive_icon}  Archive")
                archive_btn.setToolTip("Archive this checklist entry")
                archive_btn.setStyleSheet(_theme.PANEL_BTN)
                archive_btn.clicked.connect(
                    lambda _, eid=entry.id: self._on_archive(eid)
                )
                header_layout.addWidget(archive_btn)
        else:
            unarchive_btn = QPushButton(f"{_icons.qa_unarchive_icon}  Unarchive")
            unarchive_btn.setToolTip("Restore this entry to the open checklist")
            unarchive_btn.setStyleSheet(_theme.PANEL_BTN)
            unarchive_btn.clicked.connect(
                lambda _, eid=entry.id: self._on_unarchive(eid)
            )
            header_layout.addWidget(unarchive_btn)

        layout.addWidget(header_widget)

        if archived:
            return

        # ── per-step tri-state rows ───────────────────────────────────────────
        self._step_buttons[entry.id] = {}
        for idx, step in enumerate(entry.test_steps):
            self._render_step_row(entry, idx, step, parent_layout=layout)

        spacer = QWidget()
        spacer.setFixedHeight(6)
        layout.addWidget(spacer)

    def _render_step_row(
        self,
        entry,
        idx: int,
        step: str,
        *,
        parent_layout: QVBoxLayout | None = None,
    ) -> None:
        """Render a single step's row: pass/fail buttons + label + fail comment."""
        layout = parent_layout if parent_layout is not None else self._body_layout
        state = self._step_state(entry.id, idx)
        rec = self._step_record(entry.id, idx)

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 2, 0, 2)
        row_layout.setSpacing(6)

        pass_btn = QPushButton(_icons.qa_pass_icon)
        pass_btn.setToolTip("Mark passed")
        pass_btn.setFixedWidth(28)
        pass_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        pass_btn.setStyleSheet(
            _theme.QA_PASS_BTN_ACTIVE if state == "pass" else _theme.QA_PASS_BTN
        )
        pass_btn.clicked.connect(
            lambda _, eid=entry.id, si=idx: self._on_mark(eid, si, "pass")
        )

        fail_btn = QPushButton(_icons.qa_fail_icon)
        fail_btn.setToolTip("Mark failed")
        fail_btn.setFixedWidth(28)
        fail_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        fail_btn.setStyleSheet(
            _theme.QA_FAIL_BTN_ACTIVE if state == "fail" else _theme.QA_FAIL_BTN
        )
        fail_btn.clicked.connect(
            lambda _, eid=entry.id, si=idx: self._on_mark(eid, si, "fail")
        )

        step_color = _theme.COLOR_MUTED if state == "pass" else _theme.COLOR_TEXT_LOW
        step_lbl = QLabel(step)
        step_lbl.setWordWrap(True)
        step_lbl.setStyleSheet(f"font-size: {_theme.FONT_MD}; color: {step_color};")
        step_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        row_layout.addWidget(pass_btn, alignment=Qt.AlignmentFlag.AlignTop)
        row_layout.addWidget(fail_btn, alignment=Qt.AlignmentFlag.AlignTop)
        row_layout.addWidget(step_lbl, stretch=1)

        # Stale "re-test" hint when this step's sha differs from current HEAD.
        if rec and self._current_sha and rec.get("sha") and rec["sha"] != self._current_sha:
            stale_lbl = QLabel(f"{_icons.qa_stale_icon} re-test")
            stale_lbl.setToolTip(
                f"Marked on {rec.get('sha')}; current build is {self._current_sha}."
            )
            stale_lbl.setStyleSheet(_theme.QA_STALE_HINT)
            row_layout.addWidget(stale_lbl, alignment=Qt.AlignmentFlag.AlignTop)

        # Addressed-by-PR badge — shown when a newer entry's PR claims this failure.
        if state == "fail":
            addr_info = self._effective_addressed(entry.id, idx)
            if addr_info:
                addr_pr = addr_info.get("pr_number")
                addr_eid = addr_info.get("addressing_entry_id")
                badge_parts = [_icons.qa_addressed_icon, "Addressed"]
                if addr_pr:
                    badge_parts.append(f"PR #{addr_pr}")
                if addr_eid:
                    badge_parts.append(f"(entry #{addr_eid})")
                badge_parts.append("— re-test")
                badge_lbl = QLabel(" ".join(badge_parts))
                badge_lbl.setToolTip(
                    "This failure was addressed in a later PR.\n"
                    "Re-test and mark pass once confirmed."
                )
                badge_lbl.setStyleSheet(_theme.QA_ADDRESSED_BADGE)
                row_layout.addWidget(badge_lbl, alignment=Qt.AlignmentFlag.AlignTop)

                # Jump button — scroll to the addressing entry if it's visible.
                if addr_eid and addr_eid in self._ref_labels:
                    jump_btn = QPushButton(_icons.qa_jump_icon)
                    jump_btn.setToolTip(
                        f"Jump to addressing entry #{addr_eid} in this checklist"
                    )
                    jump_btn.setFixedWidth(24)
                    jump_btn.setStyleSheet(
                        f"QPushButton {{ border: none; color: {_theme.COLOR_OK};"
                        f" font-size: {_theme.FONT_MD}; }}"
                        f" QPushButton:hover {{ color: {_theme.COLOR_TEXT}; }}"
                    )
                    jump_btn.clicked.connect(
                        lambda _, eid=addr_eid: self._jump_to_entry(eid)
                    )
                    row_layout.addWidget(jump_btn, alignment=Qt.AlignmentFlag.AlignTop)

        self._step_buttons[entry.id][idx] = (pass_btn, fail_btn)
        layout.addWidget(row)

        # Fail comment area — only present when the step is failed.
        if state == "fail":
            self._render_fail_comment(entry.id, idx, rec or {}, parent_layout=layout)

    def _render_fail_comment(
        self,
        entry_id: int,
        idx: int,
        rec: dict,
        *,
        parent_layout: QVBoxLayout | None = None,
    ) -> None:
        """Render the inline comment box + attach controls for a failed step."""
        layout = parent_layout if parent_layout is not None else self._body_layout
        container = QWidget()
        clayout = QVBoxLayout(container)
        clayout.setContentsMargins(40, 2, 0, 6)
        clayout.setSpacing(4)

        note_edit = _FailNoteEdit()
        note_edit.setPlaceholderText("What went wrong? (Ctrl+V pastes a screenshot)")
        note_edit.setStyleSheet(_theme.QA_FAIL_NOTE_BOX)
        note_edit.setFixedHeight(56)
        note_edit.setPlainText(rec.get("note", ""))
        note_edit.text_committed.connect(
            lambda text, eid=entry_id, si=idx: self._on_note_changed(eid, si, text)
        )
        note_edit.image_pasted.connect(
            lambda img, eid=entry_id, si=idx: self._on_image_pasted(eid, si, img)
        )
        self._note_edits[(entry_id, idx)] = note_edit
        clayout.addWidget(note_edit)

        # Attach button + attachment chips row.
        chips_row = QWidget()
        chips_layout = QHBoxLayout(chips_row)
        chips_layout.setContentsMargins(0, 0, 0, 0)
        chips_layout.setSpacing(4)

        attach_btn = QPushButton(f"{_icons.qa_attach_icon} Attach")
        attach_btn.setToolTip("Attach a screenshot file to this failure")
        attach_btn.setStyleSheet(_theme.QA_ATTACH_BTN)
        attach_btn.clicked.connect(
            lambda _, eid=entry_id, si=idx: self._on_attach_clicked(eid, si)
        )
        chips_layout.addWidget(attach_btn)

        retest_btn = QPushButton(f"{_icons.qa_retest_icon} Re-test")
        retest_btn.setToolTip(
            "Re-run the log snapshot and record that this item was re-reviewed,\n"
            "making it visually distinct from a stale unreviewed failure."
        )
        retest_btn.setStyleSheet(_theme.QA_ATTACH_BTN)
        retest_btn.clicked.connect(
            lambda _, eid=entry_id, si=idx: self._on_retest_clicked(eid, si)
        )
        chips_layout.addWidget(retest_btn)

        # Addressed-by-PR: "Mark addressed" when not yet addressed; or an info
        # chip when the step is already addressed (auto or manual).
        addr_info = self._effective_addressed(entry_id, idx)
        if addr_info:
            # Already addressed — show a compact chip so the tester knows.
            addr_pr = addr_info.get("pr_number")
            addr_lbl_text = f"{_icons.qa_addressed_icon} Addressed"
            if addr_pr:
                addr_lbl_text += f" PR #{addr_pr}"
            addr_chip = QLabel(addr_lbl_text)
            addr_chip.setToolTip(
                "This failure has been claimed by a later PR. Re-test to confirm."
            )
            addr_chip.setStyleSheet(_theme.QA_ADDRESSED_BADGE)
            chips_layout.addWidget(addr_chip)
        else:
            # Not yet addressed — offer a manual-mark button.
            mark_addr_btn = QPushButton(f"{_icons.qa_addressed_icon} Mark addressed")
            mark_addr_btn.setToolTip(
                "Record that a later PR addresses this failure.\n"
                "The step stays FAILED until you re-test and mark it pass."
            )
            mark_addr_btn.setStyleSheet(_theme.QA_ATTACH_BTN)
            mark_addr_btn.clicked.connect(
                lambda _, eid=entry_id, si=idx: self._on_mark_step_addressed(eid, si)
            )
            chips_layout.addWidget(mark_addr_btn)

        for path in (rec.get("attachments") or []):
            name = os.path.basename(path)
            chip = QPushButton(f"{name}  {_icons.close_icon}")
            chip.setToolTip(f"Remove {path}")
            chip.setStyleSheet(_theme.QA_ATTACHMENT_CHIP)
            chip.clicked.connect(
                lambda _, eid=entry_id, si=idx, p=path: self._on_remove_attachment(eid, si, p)
            )
            chips_layout.addWidget(chip)

        log_path = rec.get("log")
        if log_path:
            log_chip = QLabel(f"{_icons.info_icon} {os.path.basename(log_path)}")
            log_chip.setToolTip(f"Log snapshot: {log_path}")
            log_chip.setStyleSheet(_theme.QA_FAIL_BADGE)
            chips_layout.addWidget(log_chip)

        last_retested = rec.get("last_retested")
        if last_retested:
            retested_lbl = QLabel(f"re-reviewed {last_retested[:10]}")
            retested_lbl.setToolTip(f"Last re-reviewed at {last_retested}")
            retested_lbl.setStyleSheet(
                f"font-size: {_theme.FONT_XS}; color: {_theme.COLOR_OK};"
            )
            chips_layout.addWidget(retested_lbl)

        chips_layout.addStretch(1)
        clayout.addWidget(chips_row)
        layout.addWidget(container)

    def _render_archived_section(self, archived: list) -> None:
        """Render a collapsible 'Archived (N)' section at the bottom of the body.

        The section is collapsed by default (``config.qa_archived_collapsed = True``).
        The toggle button uses ``icons.collapse_icon`` when expanded and
        ``icons.expand_icon`` when collapsed — never the ordering arrows.
        """
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {_theme.COLOR_LINE};")
        self._body_layout.addWidget(sep)

        # ── header row with toggle ────────────────────────────────────────────
        collapsed: bool = getattr(self._config, "qa_archived_collapsed", True)

        hdr_row = QWidget()
        hdr_layout = QHBoxLayout(hdr_row)
        hdr_layout.setContentsMargins(0, 6, 0, 4)
        hdr_layout.setSpacing(6)

        toggle_icon = _icons.expand_icon if collapsed else _icons.collapse_icon
        toggle_btn = QPushButton(toggle_icon)
        toggle_btn.setToolTip(
            "Show archived entries" if collapsed else "Hide archived entries"
        )
        toggle_btn.setFixedWidth(24)
        toggle_btn.setStyleSheet(
            f"QPushButton {{ border: none; color: {_theme.COLOR_MUTED_2};"
            f" font-size: {_theme.FONT_SM}; }}"
        )
        self._archived_toggle_btn = toggle_btn
        hdr_layout.addWidget(toggle_btn)

        section_hdr = QLabel(f"Archived ({len(archived)})")
        section_hdr.setStyleSheet(
            f"font-size: {_theme.FONT_SM}; font-weight: bold;"
            f" color: {_theme.COLOR_MUTED_2}; letter-spacing: 1px;"
        )
        hdr_layout.addWidget(section_hdr, stretch=1)
        self._body_layout.addWidget(hdr_row)

        # ── collapsible container ─────────────────────────────────────────────
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        self._archived_container = container

        for entry in archived:
            self._render_entry(entry, archived=True, parent_layout=container_layout)
            inner_sep = QFrame()
            inner_sep.setFrameShape(QFrame.Shape.HLine)
            inner_sep.setStyleSheet(f"color: {_theme.COLOR_LINE_DARK};")
            container_layout.addWidget(inner_sep)

        # Track the hidden attribute explicitly — Qt's isVisible() returns False
        # on widgets inside non-shown parent windows (common in headless tests).
        container.setVisible(not collapsed)
        container._qa_collapsed = collapsed   # type: ignore[attr-defined]
        self._body_layout.addWidget(container)

        # Wire toggle after container is wired so the lambda captures it safely.
        def _on_toggle() -> None:
            # Use the explicit _qa_collapsed flag, not isVisible(), so the toggle
            # works correctly in headless test environments too.
            current_collapsed: bool = getattr(
                self._archived_container, "_qa_collapsed", True
            )
            want_collapsed = not current_collapsed
            self._archived_container.setVisible(not want_collapsed)
            self._archived_container._qa_collapsed = want_collapsed   # type: ignore[attr-defined]
            self._archived_toggle_btn.setText(
                _icons.expand_icon if want_collapsed else _icons.collapse_icon
            )
            self._archived_toggle_btn.setToolTip(
                "Show archived entries" if want_collapsed else "Hide archived entries"
            )
            self._config.qa_archived_collapsed = want_collapsed
            self._config.save()
            logger.debug("QA checklist: archived section collapsed={}", want_collapsed)

        toggle_btn.clicked.connect(_on_toggle)

    # ── flagged items section ─────────────────────────────────────────────────

    def _render_flagged_section(self) -> None:
        """Render the collapsible '🚩 Flagged Items' section.

        Active (unaddressed) items render in the main list.  Items a later PR has
        claimed via ``WhatsNewEntry.addresses=("flagged:<id>")`` auto-file into a
        collapsed "✓ Resolved (N)" sub-group so the active list shows only what
        still needs work — the tester never manually triages a fixed flag.

        Default expanded (``config.qa_flagged_collapsed = False``).  A
        "+ Add item" button creates a new persisted flagged item row.  Items
        have a title, notes box (reuses ``_FailNoteEdit`` for screenshot paste),
        attachment chips, a status toggle, and a remove button.
        """
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {_theme.COLOR_LINE};")
        self._body_layout.addWidget(sep)

        collapsed: bool = getattr(self._config, "qa_flagged_collapsed", False)
        all_items: list[dict] = list(getattr(self._config, "qa_flagged_items", []) or [])
        active_items = [
            i for i in all_items if not self._is_flagged_resolved(i.get("id", ""))
        ]
        resolved_items = [
            i for i in all_items if self._is_flagged_resolved(i.get("id", ""))
        ]

        # ── section header row ────────────────────────────────────────────────
        hdr_row = QWidget()
        hdr_layout = QHBoxLayout(hdr_row)
        hdr_layout.setContentsMargins(0, 6, 0, 4)
        hdr_layout.setSpacing(6)

        toggle_icon = _icons.expand_icon if collapsed else _icons.collapse_icon
        flagged_toggle_btn = QPushButton(toggle_icon)
        flagged_toggle_btn.setToolTip(
            "Show flagged items" if collapsed else "Hide flagged items"
        )
        flagged_toggle_btn.setFixedWidth(24)
        flagged_toggle_btn.setStyleSheet(
            f"QPushButton {{ border: none; color: {_theme.COLOR_MUTED_2};"
            f" font-size: {_theme.FONT_SM}; }}"
        )
        hdr_layout.addWidget(flagged_toggle_btn)

        section_hdr = QLabel(
            f"{_icons.qa_flag_icon} Flagged Items ({len(active_items)})"
        )
        section_hdr.setStyleSheet(
            f"font-size: {_theme.FONT_SM}; font-weight: bold;"
            f" color: {_theme.COLOR_MUTED_2}; letter-spacing: 1px;"
        )
        hdr_layout.addWidget(section_hdr, stretch=1)

        add_btn = QPushButton(f"+ Add item")
        add_btn.setToolTip("Add a new flagged observation to capture something noticed during testing")
        add_btn.setStyleSheet(_theme.QA_ATTACH_BTN)
        hdr_layout.addWidget(add_btn)

        self._body_layout.addWidget(hdr_row)

        # ── collapsible items container (ACTIVE items only) ───────────────────
        flagged_container = QWidget()
        self._flagged_container = flagged_container  # stored for section-order tests
        flagged_layout = QVBoxLayout(flagged_container)
        flagged_layout.setContentsMargins(0, 4, 0, 4)
        flagged_layout.setSpacing(8)

        for item in active_items:
            self._render_flagged_item(item, flagged_layout)

        flagged_container.setVisible(not collapsed)
        self._body_layout.addWidget(flagged_container)

        # Wire toggle button.
        def _on_flagged_toggle() -> None:
            want_collapsed = flagged_container.isVisible()
            flagged_container.setVisible(not want_collapsed)
            flagged_toggle_btn.setText(
                _icons.expand_icon if want_collapsed else _icons.collapse_icon
            )
            flagged_toggle_btn.setToolTip(
                "Show flagged items" if want_collapsed else "Hide flagged items"
            )
            self._config.qa_flagged_collapsed = want_collapsed
            self._config.save()
            logger.debug("QA checklist: flagged section collapsed={}", want_collapsed)

        flagged_toggle_btn.clicked.connect(_on_flagged_toggle)

        # Wire "+ Add item" button.
        def _on_add_item() -> None:
            item_dict = self._create_flagged_item()
            # Reveal the container and update the toggle if it was collapsed.
            if not flagged_container.isVisible():
                flagged_container.setVisible(True)
                flagged_toggle_btn.setText(_icons.collapse_icon)
                flagged_toggle_btn.setToolTip("Hide flagged items")
                self._config.qa_flagged_collapsed = False
                self._config.save()
            # Insert the new card at position 0 (top of the list) so it's
            # immediately visible without any scrolling.
            self._render_flagged_item(item_dict, flagged_layout, insert_at=0)
            # Update the section label count (active items only — a new item is
            # never already-addressed).
            new_active = [
                i for i in (getattr(self._config, "qa_flagged_items", []) or [])
                if not self._is_flagged_resolved(i.get("id", ""))
            ]
            section_hdr.setText(
                f"{_icons.qa_flag_icon} Flagged Items ({len(new_active)})"
            )

        add_btn.clicked.connect(_on_add_item)

        # ── resolved sub-section (addressed items auto-file here) ──────────────
        if resolved_items:
            self._render_resolved_subsection(resolved_items)

    def _is_flagged_resolved(self, item_id: str) -> bool:
        """Return True when a flagged item has been claimed by a later PR.

        A flag is "resolved" once any entry declares
        ``addresses=("flagged:<item_id>")`` — surfaced through the reverse
        addressed index.  Resolved flags auto-file into the collapsed Resolved
        sub-section so the active Flagged list stays focused on outstanding work;
        the tester never manually marks a fixed flag done.
        """
        return bool(item_id) and self._flagged_effective_addressed(item_id) is not None

    def _render_resolved_subsection(self, resolved: list[dict]) -> None:
        """Render the collapsible '✓ Resolved (N)' flagged sub-section.

        Collapsed by default (``config.qa_resolved_collapsed = True``).  Items
        here were addressed by a later PR's ``addresses=`` declaration; they keep
        their Addressed badge and stay removable, but no longer clutter the
        active Flagged list.
        """
        collapsed: bool = getattr(self._config, "qa_resolved_collapsed", True)

        hdr_row = QWidget()
        hdr_layout = QHBoxLayout(hdr_row)
        hdr_layout.setContentsMargins(0, 4, 0, 4)
        hdr_layout.setSpacing(6)

        toggle_icon = _icons.expand_icon if collapsed else _icons.collapse_icon
        toggle_btn = QPushButton(toggle_icon)
        toggle_btn.setToolTip(
            "Show resolved items" if collapsed else "Hide resolved items"
        )
        toggle_btn.setFixedWidth(24)
        toggle_btn.setStyleSheet(
            f"QPushButton {{ border: none; color: {_theme.COLOR_MUTED_2};"
            f" font-size: {_theme.FONT_SM}; }}"
        )
        hdr_layout.addWidget(toggle_btn)

        section_hdr = QLabel(f"{_icons.qa_addressed_icon} Resolved ({len(resolved)})")
        section_hdr.setToolTip(
            "Flagged items a later PR has addressed — re-test, then remove."
        )
        section_hdr.setStyleSheet(
            f"font-size: {_theme.FONT_SM}; font-weight: bold;"
            f" color: {_theme.COLOR_OK}; letter-spacing: 1px;"
        )
        hdr_layout.addWidget(section_hdr, stretch=1)
        self._body_layout.addWidget(hdr_row)

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 4, 0, 4)
        container_layout.setSpacing(8)
        self._resolved_container = container
        for item in resolved:
            self._render_flagged_item(item, container_layout)

        # Track the collapse flag explicitly — isVisible() is unreliable inside
        # non-shown parent windows (headless tests).
        container.setVisible(not collapsed)
        container._qa_collapsed = collapsed  # type: ignore[attr-defined]
        self._body_layout.addWidget(container)

        def _on_toggle() -> None:
            want_collapsed = not getattr(container, "_qa_collapsed", True)
            container.setVisible(not want_collapsed)
            container._qa_collapsed = want_collapsed  # type: ignore[attr-defined]
            toggle_btn.setText(
                _icons.expand_icon if want_collapsed else _icons.collapse_icon
            )
            toggle_btn.setToolTip(
                "Show resolved items" if want_collapsed else "Hide resolved items"
            )
            self._config.qa_resolved_collapsed = want_collapsed
            self._config.save()
            logger.debug("QA checklist: resolved section collapsed={}", want_collapsed)

        toggle_btn.clicked.connect(_on_toggle)

    def _flagged_type_label(self, item_type: str) -> str:
        """Return the display label for a flagged item type cycle button."""
        return {
            "bug": f"{_icons.qa_type_bug_icon} bug",
            "feature": f"{_icons.qa_type_feature_icon} feature",
            "note": f"{_icons.qa_type_note_icon} note",
        }.get(item_type, f"{_icons.qa_type_bug_icon} bug")

    def _render_flagged_item(
        self,
        item: dict,
        parent_layout: QVBoxLayout,
        *,
        insert_at: int | None = None,
    ) -> None:
        """Render one flagged item row into *parent_layout*.

        Each row contains:
        - One-line title QLineEdit.
        - Type cycle button (bug / feature / note).
        - Notes box (reuses _FailNoteEdit — captures pasted screenshots).
        - Attachment chips.
        - Status toggle (open / triaged).
        - Remove (×) button.

        Args:
            item: The flagged item dict from ``config.qa_flagged_items``.
            parent_layout: Layout to add the card to.
            insert_at: If given, insert the card at this position in the layout
                (e.g. ``0`` places it at the top).  Otherwise the card is
                appended to the end.
        """
        item_id: str = item.get("id", "")
        if not item_id:
            return

        card = QWidget()
        card.setStyleSheet(
            f"QWidget {{ background: {_theme.OVERLAY_04};"
            f" border: 1px solid {_theme.COLOR_LINE}; border-radius: 4px; }}"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(8, 6, 8, 6)
        card_layout.setSpacing(4)

        # ── title row ─────────────────────────────────────────────────────────
        title_row = QWidget()
        title_row_layout = QHBoxLayout(title_row)
        title_row_layout.setContentsMargins(0, 0, 0, 0)
        title_row_layout.setSpacing(4)

        title_edit = QLineEdit()
        title_edit.setClearButtonEnabled(True)
        title_edit.setPlaceholderText("What did you notice?")
        title_edit.setText(item.get("title", ""))
        title_edit.setToolTip("Brief title for this observation")
        title_edit.setStyleSheet(
            f"QLineEdit {{ background: {_theme.OVERLAY_05}; border: 1px solid {_theme.COLOR_LINE};"
            f" border-radius: 3px; padding: 2px 6px; color: {_theme.COLOR_TEXT};"
            f" font-size: {_theme.FONT_MD}; }}"
        )
        self._flagged_title_edits[item_id] = title_edit
        title_row_layout.addWidget(title_edit, stretch=1)

        # Type cycle button: bug → feature → note → bug
        item_type = item.get("type", "bug")
        type_btn = QPushButton(self._flagged_type_label(item_type))
        type_btn.setToolTip(
            "Item type — click to cycle: bug → feature → note.\n"
            "bug = reproducible defect  feature = enhancement request  note = observation"
        )
        type_btn.setFixedWidth(88)
        type_btn.setStyleSheet(
            f"QPushButton {{ border: 1px solid {_theme.COLOR_LINE}; border-radius: 3px;"
            f" color: {_theme.COLOR_TEXT_LOW}; font-size: {_theme.FONT_SM};"
            f" padding: 1px 4px; }}"
            f" QPushButton:hover {{ color: {_theme.COLOR_TEXT}; }}"
        )
        title_row_layout.addWidget(type_btn)

        status = item.get("status", "open")
        status_label = _icons.qa_triaged_icon if status == "triaged" else _icons.qa_flag_icon
        status_btn = QPushButton(status_label)
        status_btn.setToolTip(
            "Mark as triaged (converted to a task/PR)" if status == "open"
            else "Mark as open (not yet triaged)"
        )
        status_btn.setFixedWidth(28)
        status_btn.setStyleSheet(
            f"QPushButton {{ border: none; color: {_theme.COLOR_OK if status == 'triaged' else _theme.COLOR_WARN};"
            f" font-size: {_theme.FONT_MD}; }}"
        )
        title_row_layout.addWidget(status_btn)

        remove_btn = QPushButton(_icons.close_icon)
        remove_btn.setToolTip("Remove this flagged item")
        remove_btn.setFixedWidth(24)
        remove_btn.setStyleSheet(
            f"QPushButton {{ border: none; color: {_theme.COLOR_MUTED_2};"
            f" font-size: {_theme.FONT_MD}; }}"
        )
        title_row_layout.addWidget(remove_btn)

        card_layout.addWidget(title_row)

        # ── note box ──────────────────────────────────────────────────────────
        note_edit = _FailNoteEdit()
        note_edit.setPlaceholderText("Notes… (Ctrl+V pastes a screenshot)")
        note_edit.setStyleSheet(_theme.QA_FAIL_NOTE_BOX)
        note_edit.setFixedHeight(56)
        note_edit.setPlainText(item.get("note", ""))
        note_edit.setToolTip("Free-text notes for this observation; Ctrl+V pastes a clipboard screenshot")
        self._flagged_note_edits[item_id] = note_edit
        card_layout.addWidget(note_edit)

        # ── attachment chips row ──────────────────────────────────────────────
        chips_row = QWidget()
        chips_layout = QHBoxLayout(chips_row)
        chips_layout.setContentsMargins(0, 0, 0, 0)
        chips_layout.setSpacing(4)

        attach_btn = QPushButton(f"{_icons.qa_attach_icon} Attach")
        attach_btn.setToolTip("Attach a screenshot file to this observation")
        attach_btn.setStyleSheet(_theme.QA_ATTACH_BTN)
        chips_layout.addWidget(attach_btn)

        # Addressed-by-PR badge for this flagged item. Flagged items are a one-way
        # FEEDER — the tester never resolves them; a flag evolves to "addressed" ONLY
        # via a later PR's WhatsNewEntry addresses=("flagged:<id>") declaration.
        # There is deliberately NO manual "mark addressed" button on flags.
        flagged_addr_info = self._flagged_effective_addressed(item_id)
        if flagged_addr_info:
            fa_pr = flagged_addr_info.get("pr_number")
            fa_text = f"{_icons.qa_addressed_icon} Addressed"
            if fa_pr:
                fa_text += f" PR #{fa_pr}"
            fa_chip = QLabel(fa_text)
            fa_chip.setToolTip(
                "This flagged item has been addressed by a later PR. Re-test to confirm."
            )
            fa_chip.setStyleSheet(_theme.QA_ADDRESSED_BADGE)
            chips_layout.addWidget(fa_chip)

        for att_path in (item.get("attachments") or []):
            att_name = os.path.basename(att_path)
            chip = QPushButton(f"{att_name}  {_icons.close_icon}")
            chip.setToolTip(f"Remove attachment: {att_path}")
            chip.setStyleSheet(_theme.QA_ATTACHMENT_CHIP)
            chip.clicked.connect(
                lambda _, iid=item_id, p=att_path: self._on_flagged_remove_attachment(iid, p)
            )
            chips_layout.addWidget(chip)

        chips_layout.addStretch(1)

        # meta: build sha + created timestamp
        sha = item.get("build_sha", "") or "?"
        created = item.get("created", "") or "?"
        meta_lbl = QLabel(f"build {sha} · {created[:10]}")
        meta_lbl.setToolTip(f"Flagged on build {sha} at {created}")
        meta_lbl.setStyleSheet(
            f"font-size: {_theme.FONT_XS}; color: {_theme.COLOR_FAINT};"
        )
        chips_layout.addWidget(meta_lbl)

        card_layout.addWidget(chips_row)
        if insert_at is not None:
            parent_layout.insertWidget(insert_at, card)
        else:
            parent_layout.addWidget(card)

        # ── wire signals ──────────────────────────────────────────────────────
        title_edit.textChanged.connect(
            lambda text, iid=item_id: self._on_flagged_title_changed(iid, text)
        )
        note_edit.text_committed.connect(
            lambda text, iid=item_id: self._on_flagged_note_changed(iid, text)
        )
        note_edit.image_pasted.connect(
            lambda img, iid=item_id: self._on_flagged_image_pasted(iid, img)
        )
        attach_btn.clicked.connect(
            lambda _, iid=item_id: self._on_flagged_attach_clicked(iid)
        )
        status_btn.clicked.connect(
            lambda _, iid=item_id: self._on_flagged_status_toggle(iid)
        )
        type_btn.clicked.connect(
            lambda _, iid=item_id: self._on_flagged_type_cycle(iid)
        )
        remove_btn.clicked.connect(
            lambda _, iid=item_id: self._on_flagged_remove(iid)
        )

    # ── flagged item data helpers ─────────────────────────────────────────────

    def _get_flagged_items(self) -> list[dict]:
        """Return a mutable copy of the current flagged items list."""
        return list(getattr(self._config, "qa_flagged_items", []) or [])

    def _save_flagged_items(self, items: list[dict]) -> None:
        """Persist *items* to config and rewrite the digest."""
        self._config.qa_flagged_items = items
        self._config.save()
        _write_flagged_digest(self._config, addressed=self._merge_addressed())

    def _create_flagged_item(self) -> dict:
        """Create, persist, and return a new empty flagged item dict.

        The new item is **prepended** to ``config.qa_flagged_items`` (index 0)
        so it appears at the top of the section without any scrolling needed.
        """
        item: dict = {
            "id": str(uuid.uuid4()),
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "build_sha": self._current_sha or "",
            "title": "",
            "note": "",
            "attachments": [],
            "status": "open",
            "type": "bug",
        }
        items = self._get_flagged_items()
        items.insert(0, item)  # prepend so newest is always at the top
        self._save_flagged_items(items)
        logger.debug("QA checklist: created flagged item id={}", item["id"])
        return item

    def _find_flagged_item(self, item_id: str) -> dict | None:
        """Return the flagged item dict with *item_id*, or ``None``."""
        for item in self._get_flagged_items():
            if item.get("id") == item_id:
                return item
        return None

    def _update_flagged_item(self, item_id: str, **kwargs) -> None:
        """Patch fields on a flagged item and save."""
        items = self._get_flagged_items()
        for item in items:
            if item.get("id") == item_id:
                item.update(kwargs)
                break
        self._save_flagged_items(items)

    # ── flagged item event handlers ───────────────────────────────────────────

    def _on_flagged_title_changed(self, item_id: str, text: str) -> None:
        """Persist a changed title (does not redraw — avoids cursor loss)."""
        item = self._find_flagged_item(item_id)
        if item and item.get("title", "") != text:
            self._update_flagged_item(item_id, title=text)

    def _on_flagged_note_changed(self, item_id: str, text: str) -> None:
        """Persist a changed note (does not redraw — avoids cursor loss)."""
        item = self._find_flagged_item(item_id)
        if item and item.get("note", "") != text:
            self._update_flagged_item(item_id, note=text)

    def _on_flagged_image_pasted(self, item_id: str, image: QImage) -> None:
        """Save a pasted clipboard image for a flagged item."""
        path = self._save_flagged_image(item_id, image)
        if path:
            self._on_flagged_append_attachment(item_id, path)

    def _save_flagged_image(self, item_id: str, image: QImage) -> str:
        """Save *image* to a PNG in the attachments dir; return its abs path."""
        adir = _attachments_dir(self._config)
        short_id = item_id[:8]
        n = 1
        while True:
            candidate = adir / f"flagged_{short_id}_{n}.png"
            if not candidate.exists():
                break
            n += 1
        if image.save(str(candidate), "PNG"):
            logger.debug("QA: saved flagged item image to {}", candidate)
            return str(candidate)
        logger.debug("QA: failed to save flagged item image for id={}", item_id)
        return ""

    def _on_flagged_attach_clicked(self, item_id: str) -> None:
        """Open a file dialog to attach a screenshot to a flagged item."""
        start_dir = str(_attachments_dir(self._config))
        path, _ = QFileDialog.getOpenFileName(
            self, "Attach screenshot", start_dir,
            "Images (*.png *.jpg *.jpeg *.gif *.webp)",
        )
        if not path:
            return
        try:
            adir = _attachments_dir(self._config)
            short_id = item_id[:8]
            ext = (os.path.splitext(path)[1].lstrip(".") or "png").lower()
            n = 1
            while True:
                candidate = adir / f"flagged_{short_id}_{n}.{ext}"
                if not candidate.exists():
                    break
                n += 1
            shutil.copy2(path, candidate)
            self._on_flagged_append_attachment(item_id, str(candidate))
        except Exception:  # noqa: BLE001
            logger.debug("QA: failed to copy flagged attachment {}", path)

    def _on_flagged_append_attachment(self, item_id: str, path: str) -> None:
        """Append *path* to a flagged item's attachments and redraw."""
        item = self._find_flagged_item(item_id)
        if not item:
            return
        atts = list(item.get("attachments") or [])
        if path not in atts:
            atts.append(path)
        self._update_flagged_item(item_id, attachments=atts)
        self._refresh_preserving_scroll()

    def _on_flagged_remove_attachment(self, item_id: str, path: str) -> None:
        """Remove an attachment path from a flagged item and redraw."""
        item = self._find_flagged_item(item_id)
        if not item:
            return
        atts = [p for p in (item.get("attachments") or []) if p != path]
        self._update_flagged_item(item_id, attachments=atts)
        self._refresh_preserving_scroll()

    def _on_flagged_status_toggle(self, item_id: str) -> None:
        """Toggle a flagged item between 'open' and 'triaged' and redraw."""
        item = self._find_flagged_item(item_id)
        if not item:
            return
        new_status = "triaged" if item.get("status", "open") == "open" else "open"
        self._update_flagged_item(item_id, status=new_status)
        logger.debug("QA checklist: flagged item {} → {}", item_id, new_status)
        self._refresh_preserving_scroll()

    def _on_flagged_type_cycle(self, item_id: str) -> None:
        """Cycle the flagged item type: bug → feature → note → bug and redraw."""
        item = self._find_flagged_item(item_id)
        if not item:
            return
        cycle = {"bug": "feature", "feature": "note", "note": "bug"}
        new_type = cycle.get(item.get("type", "bug"), "bug")
        self._update_flagged_item(item_id, type=new_type)
        logger.debug("QA checklist: flagged item {} type → {}", item_id, new_type)
        self._refresh_preserving_scroll()

    def _on_flagged_remove(self, item_id: str) -> None:
        """Remove a flagged item from config and redraw."""
        items = [i for i in self._get_flagged_items() if i.get("id") != item_id]
        self._save_flagged_items(items)
        logger.debug("QA checklist: removed flagged item id={}", item_id)
        self._refresh_preserving_scroll()

    # ── git ref + sha lookups ─────────────────────────────────────────────────

    def _start_git_lookup(self) -> None:
        """Launch the background QThread to resolve PR# / commit hashes."""
        open_entries = self._open_entries()
        if not open_entries:
            return

        import metatv.whats_new as _wn_pkg
        entries_dir = os.path.join(os.path.dirname(_wn_pkg.__file__), "entries")

        entry_ids = [e.id for e in open_entries]
        self._git_worker = _GitRefWorker(entry_ids, entries_dir)
        self._git_worker.refs_ready.connect(self._on_git_refs_ready)
        self._git_worker.finished.connect(self._git_worker.deleteLater)
        self._git_worker.start()

    def _start_sha_lookup(self) -> None:
        """Resolve the current repo HEAD short sha off-thread."""
        self._sha_worker = _HeadShaWorker()
        self._sha_worker.sha_ready.connect(self._on_sha_ready)
        self._sha_worker.finished.connect(self._sha_worker.deleteLater)
        self._sha_worker.start()

    def _on_sha_ready(self, sha: str) -> None:
        """Main-thread slot: cache the current HEAD sha and redraw stale hints."""
        self._current_sha = sha
        self._refresh()
        self._write_digest()

    def _on_git_refs_ready(self, refs: dict) -> None:
        """Main-thread slot: cache resolved refs, update labels, rewrite digest.

        Also rebuilds the addressed index — PR numbers are now available so the
        index may gain ``pr_number`` values that were ``None`` at startup.  When
        the index is non-empty a full re-render is needed to populate the PR#
        inside any addressed badges (lightweight path: just update labels when
        there are no addressed steps to show).
        """
        self._git_refs = refs
        new_index = self._build_addressed_index()
        if new_index:
            # Addressed steps exist: full re-render so PR# appears in the badges.
            self._addressed_index = new_index
            self._refresh_preserving_scroll()
        else:
            # No addressed steps: just update the header ref labels (lightweight).
            self._addressed_index = new_index
            self._apply_git_refs(refs)
        self._write_digest()

    def _apply_git_refs(self, refs: dict) -> None:
        """Update all currently-rendered ref labels from *refs*."""
        for entry_id, ref_info in refs.items():
            lbl = self._ref_labels.get(entry_id)
            if lbl is None:
                continue

            pr_number = ref_info.get("pr_number")
            commit_hash = ref_info.get("commit_hash")
            base_url = ref_info.get("base_url")

            if pr_number and base_url:
                url = f"{base_url}/pull/{pr_number}"
                lbl.setText(
                    f'<a href="{url}" style="color:{_theme.COLOR_LINK};'
                    f' text-decoration:none;">PR #{pr_number}</a>'
                )
                lbl.setToolTip(f"Open PR #{pr_number} on GitHub")
            elif commit_hash and base_url:
                url = f"{base_url}/commit/{commit_hash}"
                lbl.setText(
                    f'<a href="{url}" style="color:{_theme.COLOR_LINK};'
                    f' text-decoration:none;">{commit_hash}</a>'
                )
                lbl.setToolTip("Open commit on GitHub")
            # else: leave the label showing entry.date (set in _render_entry)

    # ── digest ────────────────────────────────────────────────────────────────

    def _write_digest(self) -> str:
        """(Re)write ``<config_dir>/qa_failures.md`` for the current state."""
        return _write_failures_digest(
            self._config, self._open_entries(), self._git_refs, self._current_sha,
            addressed=self._merge_addressed(),
        )

    # ── addressed-by-PR helpers ───────────────────────────────────────────────

    @staticmethod
    def _parse_address_ref(ref: str):
        """Parse an addresses reference string into a dict key.

        Args:
            ref: ``"e{id}_s{idx}"`` for a step, or ``"flagged:{uuid}"`` for a
                tester-flagged item.

        Returns:
            A ``(entry_id: int, step_idx: int)`` tuple for step refs, the
            original ``"flagged:{uuid}"`` string for flagged refs, or ``None``
            when the format is unrecognised.
        """
        if ref.startswith("flagged:"):
            return ref  # string key
        m = re.match(r'^e(\d+)_s(\d+)$', ref)
        if m:
            return (int(m.group(1)), int(m.group(2)))
        return None

    def _build_addressed_index(self) -> dict:
        """Build the reverse index from entries' ``addresses`` declarations.

        Iterates every entry in ``self._all_entries`` looking for an
        ``addresses`` attribute, then maps each reference to the addressing
        entry's id and resolved PR number (from ``self._git_refs``).

        Returns:
            Dict mapping:
            - ``(entry_id: int, step_idx: int)`` → ``{"addressing_entry_id": int,
              "pr_number": int|None}`` for step refs.
            - ``"flagged:{item_id}"`` str → same shape for flagged-item refs.
        """
        index: dict = {}
        for entry in self._all_entries:
            addresses = getattr(entry, "addresses", ()) or ()
            if not addresses:
                continue
            pr_number = (self._git_refs.get(entry.id) or {}).get("pr_number")
            for ref in addresses:
                key = self._parse_address_ref(ref)
                if key is None:
                    logger.warning(
                        "qa_checklist: unrecognised address ref '{}' on entry {} — skipped",
                        ref, entry.id,
                    )
                    continue
                index[key] = {
                    "addressing_entry_id": entry.id,
                    "pr_number": pr_number,
                }
        return index

    def _effective_addressed(self, entry_id: int, step_idx: int) -> dict | None:
        """Return addressed info for a failed step, or ``None`` if not addressed.

        Checks the auto reverse index (from ``addresses`` declarations) first,
        then the manual ``config.qa_addressed`` dict.

        Returns:
            Dict with keys ``"addressing_entry_id"`` (int|None),
            ``"pr_number"`` (int|None) — or ``None`` if not addressed.
        """
        info = self._addressed_index.get((entry_id, step_idx))
        if info:
            return info
        # Manual fallback from config.
        manual_key = f"e{entry_id}_s{step_idx}"
        manual = (getattr(self._config, "qa_addressed", {}) or {}).get(manual_key)
        if manual:
            return {
                "addressing_entry_id": manual.get("entry_id"),
                "pr_number": manual.get("pr"),
            }
        return None

    def _flagged_effective_addressed(self, item_id: str) -> dict | None:
        """Return AUTO addressed info for a flagged item, or ``None``.

        Flagged items are a one-way feeder — they evolve to "addressed" ONLY via a
        later PR's ``WhatsNewEntry.addresses=("flagged:<id>")`` declaration (the
        reverse index). There is no manual/tester resolution path for flags.
        """
        return self._addressed_index.get(f"flagged:{item_id}")

    def _merge_addressed(self) -> dict:
        """Merge auto-indexed and manually-marked addressed info into string-keyed dict.

        Returns:
            Dict mapping string keys (``"e{id}_s{idx}"`` or ``"flagged:{id}"``)
            → addressed info dicts.  Auto-indexed entries take precedence over
            manual ones when both exist for the same key.
        """
        merged: dict = {}
        # Auto from addresses declarations (tuple or string keys).
        for key, info in self._addressed_index.items():
            str_key = f"e{key[0]}_s{key[1]}" if isinstance(key, tuple) else key
            merged[str_key] = info
        # Manual from config.qa_addressed (string keys; auto takes precedence).
        for mkey, minfo in (getattr(self._config, "qa_addressed", {}) or {}).items():
            if mkey not in merged:
                merged[mkey] = minfo
        return merged

    def _jump_to_entry(self, entry_id: int) -> None:
        """Scroll the body so the header of *entry_id* is visible."""
        lbl = self._ref_labels.get(entry_id)
        if lbl is not None:
            self._scroll.ensureWidgetVisible(lbl)

    def _on_mark_step_addressed(self, entry_id: int, step_idx: int) -> None:
        """Manually mark a failed step as addressed by a later PR.

        Opens an input dialog asking for the PR number (optional), persists
        the addressed state in ``config.qa_addressed``, then redraws + rewrites
        the digest.  The step's ``qa_step_results`` state stays ``"fail"`` —
        the human must still re-test and manually mark it pass.

        Args:
            entry_id: Entry whose step is being marked addressed.
            step_idx: Index of the failed step.
        """
        pr_text, ok = QInputDialog.getText(
            self,
            "Mark Addressed",
            "PR number that addresses this failure\n"
            "(leave blank to mark addressed without a specific PR number):",
        )
        if not ok:
            return  # tester cancelled

        pr_num: int | None = None
        stripped = pr_text.strip().lstrip("#")
        if stripped:
            try:
                pr_num = int(stripped)
            except ValueError:
                pass  # non-numeric entry → no PR number stored

        key = f"e{entry_id}_s{step_idx}"
        addressed = dict(getattr(self._config, "qa_addressed", {}) or {})
        addressed[key] = {
            "pr": pr_num,
            "entry_id": None,
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "manual": True,
        }
        self._config.qa_addressed = addressed
        self._config.save()
        logger.debug(
            "QA: step e{}_s{} manually marked addressed (PR {})",
            entry_id, step_idx, pr_num,
        )
        self._refresh_preserving_scroll()
        self._write_digest()

    # ── event handlers ────────────────────────────────────────────────────────

    def _on_mark(self, entry_id: int, step_idx: int, target: str) -> None:
        """Set a step's tri-state, toggling off when the active state is re-clicked.

        Args:
            entry_id: Entry whose step changed.
            step_idx: Index of the step within ``test_steps``.
            target: ``"pass"`` or ``"fail"`` — the button that was clicked.
        """
        current = self._step_state(entry_id, step_idx)
        if current == target:
            # Re-clicking the active state clears it back to untested.
            self._write_step_record(entry_id, step_idx, None)
            logger.debug("QA step {}/{} → untested", entry_id, step_idx)
            self._refresh_preserving_scroll()
            self._write_digest()
            return

        prev = self._step_record(entry_id, step_idx) or {}
        record: dict = {
            "state": target,
            "sha": self._current_sha,
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if target == "fail":
            # Preserve any prior note / attachments; capture a fresh log snapshot.
            record["note"] = prev.get("note", "")
            record["attachments"] = list(prev.get("attachments") or [])
            record["log"] = prev.get("log", "")
            self._write_step_record(entry_id, step_idx, record)
            self._start_log_snapshot(entry_id, step_idx)
        else:
            self._write_step_record(entry_id, step_idx, record)

        logger.debug("QA step {}/{} → {}", entry_id, step_idx, target)
        self._refresh_preserving_scroll()
        self._write_digest()

    def _start_log_snapshot(self, entry_id: int, step_idx: int) -> None:
        """Capture the active log tail off-thread for a freshly-failed step."""
        worker = _LogSnapshotWorker(self._config, entry_id, step_idx)
        worker.snapshot_ready.connect(self._on_log_snapshot_ready)
        worker.finished.connect(
            lambda w=worker: self._log_workers.remove(w) if w in self._log_workers else None
        )
        worker.finished.connect(worker.deleteLater)
        self._log_workers.append(worker)
        worker.start()

    def _on_log_snapshot_ready(self, entry_id: int, step_idx: int, path: str) -> None:
        """Main-thread slot: store the captured log path on the step record."""
        if not path:
            return
        rec = self._step_record(entry_id, step_idx)
        if not rec or rec.get("state") != "fail":
            return  # state changed before the snapshot landed
        updated = dict(rec)
        updated["log"] = path
        self._write_step_record(entry_id, step_idx, updated)
        self._refresh_preserving_scroll()
        self._write_digest()

    def _on_retest_clicked(self, entry_id: int, step_idx: int) -> None:
        """Re-run log snapshot and stamp a re-review timestamp on the record.

        Called from the "↻ Re-test" button on a failed step's comment area.
        Records ``last_retested`` (ISO timestamp) so a freshly-reviewed failure
        is visually distinct from a stale unreviewed one, then kicks off a fresh
        log snapshot off-thread.
        """
        rec = self._step_record(entry_id, step_idx)
        if not rec or rec.get("state") != "fail":
            return
        updated = dict(rec)
        updated["last_retested"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._write_step_record(entry_id, step_idx, updated)
        self._start_log_snapshot(entry_id, step_idx)
        logger.debug("QA: re-test requested e={} s={}", entry_id, step_idx)
        self._refresh_preserving_scroll()
        self._write_digest()

    def _on_note_changed(self, entry_id: int, step_idx: int, text: str) -> None:
        """Persist a failed step's note (does not redraw — avoids cursor loss)."""
        rec = self._step_record(entry_id, step_idx)
        if not rec or rec.get("state") != "fail":
            return
        if rec.get("note", "") == text:
            return
        updated = dict(rec)
        updated["note"] = text
        self._write_step_record(entry_id, step_idx, updated)
        self._write_digest()

    def _on_image_pasted(self, entry_id: int, step_idx: int, image: QImage) -> None:
        """Save a pasted clipboard image (main thread) and attach it."""
        path = self._save_image(entry_id, step_idx, image)
        if path:
            self._append_attachment(entry_id, step_idx, path)

    def _on_attach_clicked(self, entry_id: int, step_idx: int) -> None:
        """Open a file dialog to attach an existing screenshot to a failure."""
        start_dir = str(_attachments_dir(self._config))
        path, _ = QFileDialog.getOpenFileName(
            self, "Attach screenshot", start_dir,
            "Images (*.png *.jpg *.jpeg *.gif *.webp)",
        )
        if not path:
            return
        # Copy the chosen file into the attachments dir for a stable abs path.
        dest = self._copy_into_attachments(entry_id, step_idx, path)
        if dest:
            self._append_attachment(entry_id, step_idx, dest)

    def _on_remove_attachment(self, entry_id: int, step_idx: int, path: str) -> None:
        """Remove an attachment path from a failed step's record."""
        rec = self._step_record(entry_id, step_idx)
        if not rec:
            return
        updated = dict(rec)
        updated["attachments"] = [p for p in (rec.get("attachments") or []) if p != path]
        self._write_step_record(entry_id, step_idx, updated)
        self._refresh_preserving_scroll()
        self._write_digest()

    # ── attachment save helpers (QImage on main thread) ───────────────────────

    def _next_attachment_path(self, entry_id: int, step_idx: int, ext: str) -> Path:
        """Return the next free ``e{entry}_s{idx}_{n}.{ext}`` path in the dir."""
        adir = _attachments_dir(self._config)
        n = 1
        while True:
            candidate = adir / f"e{entry_id}_s{step_idx}_{n}.{ext}"
            if not candidate.exists():
                return candidate
            n += 1

    def _save_image(self, entry_id: int, step_idx: int, image: QImage) -> str:
        """Save *image* to a PNG in the attachments dir; return its abs path.

        QImage save is a GUI op — this runs on the main thread.
        """
        dest = self._next_attachment_path(entry_id, step_idx, "png")
        if image.save(str(dest), "PNG"):
            logger.debug("QA: saved pasted image to {}", dest)
            return str(dest)
        logger.debug("QA: failed to save pasted image for e={} s={}", entry_id, step_idx)
        return ""

    def _copy_into_attachments(self, entry_id: int, step_idx: int, src: str) -> str:
        """Copy a chosen file into the attachments dir; return the new abs path."""
        try:
            ext = (os.path.splitext(src)[1].lstrip(".") or "png").lower()
            dest = self._next_attachment_path(entry_id, step_idx, ext)
            shutil.copy2(src, dest)
            return str(dest)
        except Exception:  # noqa: BLE001
            logger.debug("QA: failed to copy attachment {}", src)
            return ""

    def _append_attachment(self, entry_id: int, step_idx: int, path: str) -> None:
        """Append *path* to a failed step's ``attachments`` list and redraw."""
        rec = self._step_record(entry_id, step_idx)
        if not rec or rec.get("state") != "fail":
            return
        updated = dict(rec)
        atts = list(updated.get("attachments") or [])
        if path not in atts:
            atts.append(path)
        updated["attachments"] = atts
        self._write_step_record(entry_id, step_idx, updated)
        self._refresh_preserving_scroll()
        self._write_digest()

    # ── archive / purge ───────────────────────────────────────────────────────

    def _on_archive(self, entry_id: int) -> None:
        """Archive a single fully-passed entry."""
        archived = list(getattr(self._config, "qa_archived_ids", []))
        if entry_id not in archived:
            archived.append(entry_id)
        self._config.qa_archived_ids = archived
        self._config.save()
        logger.info("QA checklist: archived entry id={}", entry_id)
        self._refresh_preserving_scroll()
        self._write_digest()

    def _on_unarchive(self, entry_id: int) -> None:
        """Restore an archived entry back to the open checklist."""
        archived = list(getattr(self._config, "qa_archived_ids", []))
        if entry_id in archived:
            archived.remove(entry_id)
        self._config.qa_archived_ids = archived
        self._config.save()
        logger.info("QA checklist: unarchived entry id={}", entry_id)
        self._refresh_preserving_scroll()
        self._write_digest()

    def _on_purge(self) -> None:
        """Advance qa_verified_id past all currently-passing entries.

        Entries with any failure are kept visible: the cursor only advances to
        the highest id that has no failure, so a failed entry is never silently
        purged away.  When every open entry passes, the cursor jumps past all.
        """
        open_entries = self._open_entries()
        if not open_entries:
            return

        clearable = [e for e in open_entries if not self._entry_has_failure(e)]
        if not clearable:
            return
        # Advance only as far as the lowest failing id allows, so failures stay.
        failing_ids = [e.id for e in open_entries if self._entry_has_failure(e)]
        max_clearable = max(e.id for e in clearable)
        if failing_ids:
            max_clearable = min(max_clearable, min(failing_ids) - 1)
        if max_clearable <= self._config.qa_verified_id:
            return

        self._config.qa_verified_id = max_clearable
        self._config.save()
        logger.info("QA checklist purged up to entry id={}", max_clearable)

        self._refresh()
        self._write_digest()
