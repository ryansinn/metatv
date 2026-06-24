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
progress fraction ("2/3"), plus one ``QCheckBox`` per step.  When ALL steps
for an entry are checked an **Archive** button appears in the entry header;
clicking it adds the entry's id to ``config.qa_archived_ids`` and removes
that entry from the open list without touching others.

Checked state is persisted in ``config.qa_checked_steps`` (a dict mapping
``str(entry_id)`` → list of checked step indices).

When every visible entry is fully checked the window also enables a global
**Purge** button that advances the ``qa_verified_id`` cursor past all current
entries so the list resets.

Enhancement 1 — PR# links
--------------------------
When the window is constructed a single background QThread resolves each
open entry's source file, runs ``git log`` to find the introducing commit,
parses a PR number from the squash-merge subject, derives the GitHub base URL
from ``git remote get-url origin``, and emits a signal back to the main
thread to update the header labels.  No subprocess runs on the UI thread.

Enhancement 2 — per-entry archive
-----------------------------------
When an entry is fully checked a small Archive button appears next to the
entry title.  Clicking it persists the id into ``config.qa_archived_ids``
and refreshes the view.  An "Archived (N)" section at the bottom of the
list shows tucked-away entries with an Unarchive button.
"""

from __future__ import annotations

import glob
import os
import re
import subprocess
from typing import TYPE_CHECKING

from loguru import logger
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
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


# ── background worker ─────────────────────────────────────────────────────────

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
        config: Config,
        entries: list[WhatsNewEntry],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._config = config
        self._all_entries = entries  # full list; re-filter on each refresh
        self._checkboxes: dict[int, list[QCheckBox]] = {}  # entry_id → checkboxes
        self._ref_labels: dict[int, QLabel] = {}           # entry_id → header ref label
        self._git_refs: dict[int, dict] = {}               # entry_id → resolved ref info
        self._git_worker: _GitRefWorker | None = None

        self.setWindowTitle("Testing Checklist")
        self.setMinimumWidth(420)
        self.setMinimumHeight(200)
        self.resize(460, 540)

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
            "Clear all checked items — advances the verified cursor so these"
            " entries no longer appear."
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

    # ── public ───────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Re-read config and redraw the checklist (e.g. after a purge)."""
        self._refresh()

    # ── private helpers ───────────────────────────────────────────────────────

    def _open_entries(self) -> list[WhatsNewEntry]:
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

    def _archived_entries(self) -> list[WhatsNewEntry]:
        """Return entries that have been individually archived, newest-first.

        Only considers entries that passed the basic filter (has test_steps,
        id > qa_verified_id) and are explicitly in qa_archived_ids.
        """
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

    def _is_entry_complete(self, entry: WhatsNewEntry) -> bool:
        """Return True when every step of *entry* is checked in config."""
        checked = set(self._config.qa_checked_steps.get(str(entry.id), []))
        return len(checked) >= len(entry.test_steps) and all(
            i in checked for i in range(len(entry.test_steps))
        )

    def _all_complete(self, open_entries: list[WhatsNewEntry]) -> bool:
        """Return True when every open entry is fully checked."""
        return bool(open_entries) and all(
            self._is_entry_complete(e) for e in open_entries
        )

    def _clear_body(self) -> None:
        """Remove all widgets from the body layout."""
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._checkboxes.clear()
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

        # Render archived section
        archived = self._archived_entries()
        if archived:
            self._render_archived_section(archived)

        # Push content to top
        self._body_layout.addStretch(1)

        # Re-apply already-resolved git refs after each refresh so labels
        # created by _render_entry pick up refs the worker has already found.
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

        sub_lbl = QLabel("All test steps are complete or no entries have steps yet.")
        sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub_lbl.setWordWrap(True)
        sub_lbl.setStyleSheet(f"font-size: {_theme.FONT_MD}; color: {_theme.COLOR_FAINT};")
        layout.addWidget(sub_lbl)

        self._body_layout.addWidget(container)

    def _render_entry(self, entry: WhatsNewEntry, *, archived: bool = False) -> None:
        """Render one entry block: header + checkboxes.

        Args:
            entry: The WhatsNewEntry to render.
            archived: When True the entry is rendered in compact read-only form
                inside the archived section (no checkboxes; Unarchive button only).
        """
        checked_indices = set(self._config.qa_checked_steps.get(str(entry.id), []))
        n_total = len(entry.test_steps)
        n_checked = sum(1 for i in range(n_total) if i in checked_indices)
        is_complete = n_checked >= n_total

        # ── entry header ──────────────────────────────────────────────────────
        header_widget = QWidget()
        header_widget.setContentsMargins(0, 0, 0, 0)
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 10, 0, 6)
        header_layout.setSpacing(6)

        title_color = _theme.COLOR_MUTED if (is_complete or archived) else _theme.COLOR_TEXT
        title_lbl = QLabel(entry.title)
        title_lbl.setStyleSheet(
            f"font-size: {_theme.FONT_LG}; font-weight: bold; color: {title_color};"
        )
        header_layout.addWidget(title_lbl, stretch=1)

        # PR# / date reference label — starts as the entry date; updated
        # to a clickable link once the background git worker finishes.
        ref_lbl = QLabel(entry.date)
        ref_lbl.setStyleSheet(f"font-size: {_theme.FONT_SM}; color: {_theme.COLOR_MUTED_2};")
        ref_lbl.setOpenExternalLinks(True)
        header_layout.addWidget(ref_lbl)
        self._ref_labels[entry.id] = ref_lbl

        if not archived:
            progress_color = _theme.COLOR_OK if is_complete else _theme.COLOR_DIM
            progress_lbl = QLabel(f"{n_checked}/{n_total}")
            progress_lbl.setStyleSheet(
                f"font-size: {_theme.FONT_SM}; color: {progress_color};"
                f" font-weight: bold; padding-left: 4px;"
            )
            header_layout.addWidget(progress_lbl)

            # Archive button — only visible when all steps are checked
            if is_complete:
                archive_btn = QPushButton(f"{_icons.qa_archive_icon}  Archive")
                archive_btn.setToolTip("Archive this checklist entry")
                archive_btn.setStyleSheet(_theme.PANEL_BTN)
                archive_btn.clicked.connect(
                    lambda _, eid=entry.id: self._on_archive(eid)
                )
                header_layout.addWidget(archive_btn)
        else:
            # In archived section: show Unarchive button
            unarchive_btn = QPushButton(f"{_icons.qa_unarchive_icon}  Unarchive")
            unarchive_btn.setToolTip("Restore this entry to the open checklist")
            unarchive_btn.setStyleSheet(_theme.PANEL_BTN)
            unarchive_btn.clicked.connect(
                lambda _, eid=entry.id: self._on_unarchive(eid)
            )
            header_layout.addWidget(unarchive_btn)

        self._body_layout.addWidget(header_widget)

        if archived:
            # Archived mode: no step checkboxes — just the header + unarchive.
            return

        # ── step checkboxes ───────────────────────────────────────────────────
        # QCheckBox.setWordWrap() is not available in PyQt6; instead we use a
        # plain QCheckBox (no text) paired with a word-wrapped QLabel in a row.
        checkboxes: list[QCheckBox] = []
        for idx, step in enumerate(entry.test_steps):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 2, 0, 2)
            row_layout.setSpacing(6)

            cb = QCheckBox()
            cb.setSizePolicy(
                QSizePolicy.Policy.Fixed,
                QSizePolicy.Policy.Fixed,
            )
            step_color = _theme.COLOR_MUTED if idx in checked_indices else _theme.COLOR_TEXT_LOW
            cb.setStyleSheet(
                f"QCheckBox {{ padding: 0; spacing: 0; }}"
                f"QCheckBox::indicator {{ width: 14px; height: 14px; }}"
            )

            step_lbl = QLabel(step)
            step_lbl.setWordWrap(True)
            step_lbl.setStyleSheet(
                f"font-size: {_theme.FONT_MD}; color: {step_color};"
            )
            step_lbl.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Preferred,
            )

            row_layout.addWidget(cb, alignment=Qt.AlignmentFlag.AlignTop)
            row_layout.addWidget(step_lbl, stretch=1)

            # ── set initial checked state (block signals during restore) ──────
            cb.blockSignals(True)
            cb.setChecked(idx in checked_indices)
            cb.blockSignals(False)

            checkboxes.append(cb)
            self._body_layout.addWidget(row)

        # Wire handlers AFTER all widgets are set
        for idx, cb in enumerate(checkboxes):
            cb.toggled.connect(
                lambda checked, eid=entry.id, step_idx=idx: self._on_step_toggled(
                    eid, step_idx, checked
                )
            )

        self._checkboxes[entry.id] = checkboxes

        # Spacing after entry's steps
        spacer = QWidget()
        spacer.setFixedHeight(6)
        self._body_layout.addWidget(spacer)

    def _render_archived_section(self, archived: list[WhatsNewEntry]) -> None:
        """Render an 'Archived (N)' section at the bottom of the body.

        Args:
            archived: List of archived WhatsNewEntry objects (newest-first).
        """
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

    # ── git ref lookup ────────────────────────────────────────────────────────

    def _start_git_lookup(self) -> None:
        """Launch the background QThread to resolve PR# / commit hashes.

        Only started if there are open entries.  The worker is owned by the
        window and connected to ``deleteLater`` on finish so Qt cleans it up.
        """
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

    def _on_git_refs_ready(self, refs: dict) -> None:
        """Main-thread slot: cache resolved refs and update header labels.

        Args:
            refs: dict mapping entry_id (int) → ref_info dict.
        """
        self._git_refs = refs
        self._apply_git_refs(refs)

    def _apply_git_refs(self, refs: dict) -> None:
        """Update all currently-rendered ref labels from *refs*.

        Called after initial resolution and also at the end of each
        ``_refresh()`` so labels re-created during a refresh immediately
        get the already-known ref text.

        Args:
            refs: dict mapping entry_id (int) → ref_info dict.
        """
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

    # ── event handlers ────────────────────────────────────────────────────────

    def _on_step_toggled(self, entry_id: int, step_idx: int, checked: bool) -> None:
        """Persist checkbox state change and update progress + purge button.

        Args:
            entry_id: The entry whose step was toggled.
            step_idx: Index of the step within the entry's test_steps.
            checked: New checked state.
        """
        key = str(entry_id)
        current = list(self._config.qa_checked_steps.get(key, []))

        if checked and step_idx not in current:
            current.append(step_idx)
        elif not checked and step_idx in current:
            current.remove(step_idx)

        # Build updated dict (Pydantic model — must assign a new object to trigger save)
        updated = dict(self._config.qa_checked_steps)
        updated[key] = current
        self._config.qa_checked_steps = updated
        self._config.save()
        logger.debug("QA step {}/{} → {}", entry_id, step_idx, checked)

        # Redraw the full checklist to update step colors, progress fractions,
        # and the purge / archive button states.
        self._refresh()

    def _on_archive(self, entry_id: int) -> None:
        """Archive a single fully-checked entry.

        Adds *entry_id* to ``config.qa_archived_ids``, saves, and refreshes.

        Args:
            entry_id: The entry id to archive.
        """
        archived = list(getattr(self._config, "qa_archived_ids", []))
        if entry_id not in archived:
            archived.append(entry_id)
        self._config.qa_archived_ids = archived
        self._config.save()
        logger.info("QA checklist: archived entry id={}", entry_id)
        self._refresh()

    def _on_unarchive(self, entry_id: int) -> None:
        """Restore an archived entry back to the open checklist.

        Removes *entry_id* from ``config.qa_archived_ids``, saves, and
        refreshes.

        Args:
            entry_id: The entry id to unarchive.
        """
        archived = list(getattr(self._config, "qa_archived_ids", []))
        if entry_id in archived:
            archived.remove(entry_id)
        self._config.qa_archived_ids = archived
        self._config.save()
        logger.info("QA checklist: unarchived entry id={}", entry_id)
        self._refresh()

    def _on_purge(self) -> None:
        """Advance qa_verified_id past all current entries and reset the view."""
        open_entries = self._open_entries()
        if not open_entries:
            return

        max_id = max(e.id for e in open_entries)
        self._config.qa_verified_id = max_id
        self._config.save()
        logger.info("QA checklist purged up to entry id={}", max_id)

        self._refresh()
