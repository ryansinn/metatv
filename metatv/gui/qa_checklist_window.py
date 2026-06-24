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
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
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
) -> str:
    """Build the Markdown digest of all current failures across *open_entries*.

    For each failed step the digest lists the entry title + id, its PR number
    (from the resolved git refs), the step text, ``tested on <sha> · current
    <HEAD>`` with a stale marker when they differ, the note, attachment paths,
    and the log snapshot path.  When there are no failures the body is a short
    "No failures recorded." note (the file is written, never deleted).

    Args:
        config: App config (read ``qa_step_results``).
        open_entries: The currently-open WhatsNewEntry list.
        git_refs: ``{entry_id: {"pr_number": int|None, ...}}`` from the worker.
        current_sha: The current repo HEAD short sha (``""`` if unresolved).

    Returns:
        The full Markdown document as a string.
    """
    results = config.qa_step_results or {}
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

            lines = [
                f"### {entry.title} (entry {entry.id}, {pr_str})",
                "",
                f"- **Step {idx + 1}:** {step}",
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
) -> str:
    """Render and write ``<config_dir>/qa_failures.md``; return its path.

    Always writes the file (even with zero failures — never deleted).  Errors
    are logged and swallowed; an empty string is returned on failure.
    """
    try:
        text = _build_failures_digest(config, open_entries, git_refs, current_sha)
        dest = _config_dir(config) / "qa_failures.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        return str(dest)
    except Exception:  # noqa: BLE001
        logger.debug("qa_checklist: failed to write failures digest")
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

        self.setWindowTitle("Testing Checklist")
        self.setMinimumWidth(440)
        self.setMinimumHeight(200)
        self.resize(500, 580)

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
        scroll.setWidgetResizable(True)
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
        # Write an initial digest so the file always reflects current state.
        self._write_digest()

    # ── public ───────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Re-read config and redraw the checklist (e.g. after a purge)."""
        self._refresh()

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

    def _refresh(self) -> None:
        """Rebuild the body from current config state."""
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

    def _render_entry(self, entry, *, archived: bool = False) -> None:
        """Render one entry block: header + per-step tri-state rows.

        Args:
            entry: The WhatsNewEntry to render.
            archived: When True the entry is rendered in compact read-only form
                inside the archived section (no step rows; Unarchive button only).
        """
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

        self._body_layout.addWidget(header_widget)

        if archived:
            return

        # ── per-step tri-state rows ───────────────────────────────────────────
        self._step_buttons[entry.id] = {}
        for idx, step in enumerate(entry.test_steps):
            self._render_step_row(entry, idx, step)

        spacer = QWidget()
        spacer.setFixedHeight(6)
        self._body_layout.addWidget(spacer)

    def _render_step_row(self, entry, idx: int, step: str) -> None:
        """Render a single step's row: pass/fail buttons + label + fail comment."""
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

        self._step_buttons[entry.id][idx] = (pass_btn, fail_btn)
        self._body_layout.addWidget(row)

        # Fail comment area — only present when the step is failed.
        if state == "fail":
            self._render_fail_comment(entry.id, idx, rec or {})

    def _render_fail_comment(self, entry_id: int, idx: int, rec: dict) -> None:
        """Render the inline comment box + attach controls for a failed step."""
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

        chips_layout.addStretch(1)
        clayout.addWidget(chips_row)
        self._body_layout.addWidget(container)

    def _render_archived_section(self, archived: list) -> None:
        """Render an 'Archived (N)' section at the bottom of the body."""
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {_theme.COLOR_LINE};")
        self._body_layout.addWidget(sep)

        section_hdr = QLabel(f"Archived ({len(archived)})")
        section_hdr.setStyleSheet(
            f"font-size: {_theme.FONT_SM}; font-weight: bold;"
            f" color: {_theme.COLOR_MUTED_2}; letter-spacing: 1px;"
            f" padding: 8px 0 4px 0;"
        )
        self._body_layout.addWidget(section_hdr)

        for entry in archived:
            self._render_entry(entry, archived=True)
            inner_sep = QFrame()
            inner_sep.setFrameShape(QFrame.Shape.HLine)
            inner_sep.setStyleSheet(f"color: {_theme.COLOR_LINE_DARK};")
            self._body_layout.addWidget(inner_sep)

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
        """Main-thread slot: cache resolved refs, update labels, rewrite digest."""
        self._git_refs = refs
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
            self._config, self._open_entries(), self._git_refs, self._current_sha
        )

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
            self._refresh()
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
        self._refresh()
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
        self._refresh()
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
        self._refresh()
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
        self._refresh()
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
        self._refresh()
        self._write_digest()

    def _on_unarchive(self, entry_id: int) -> None:
        """Restore an archived entry back to the open checklist."""
        archived = list(getattr(self._config, "qa_archived_ids", []))
        if entry_id in archived:
            archived.remove(entry_id)
        self._config.qa_archived_ids = archived
        self._config.save()
        logger.info("QA checklist: unarchived entry id={}", entry_id)
        self._refresh()
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
