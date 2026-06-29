"""Behavioral tests for QA checklist navigation (deep-link steps + addressed badge).

Two features under test:
  1. A ``(text, target)`` test step renders a "Go ▸" button that routes the
     target to the host's ``navigate_to`` seam; a plain-string step renders no
     such button (backward compatibility).
  2. The "Addressed PR #N" badge on a failed step is clickable and invokes the
     jump-to-addressing-entry path.

Plus the ``navigate_to`` seam itself: ``view:`` / ``settings:`` resolve to the
right switch/open call, and ``sample:`` resolves to a REAL matching channel
(real ``Database`` on a ``tmp_path`` file, conftest ``_isolate_user_config``).

Headless-Qt pattern mirrors ``tests/test_qa_flag_self_cleaning.py``.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from metatv.gui.main_window_nav import _NavMixin


# ── fixtures / helpers ───────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


class _Cfg:
    """Minimal Config stand-in; config_dir is tmp so digests stay isolated."""

    def __init__(self, config_dir: Path, step_results: dict | None = None) -> None:
        self.qa_verified_id = 0
        self.qa_step_results: dict = step_results or {}
        self.qa_archived_ids: list = []
        self.qa_archived_collapsed = True
        self.qa_flagged_items: list = []
        self.qa_flagged_collapsed = False
        self.qa_resolved_collapsed = True
        self.qa_addressed: dict = {}
        self.config_dir = config_dir
        self.save_calls = 0

    def save(self) -> None:
        self.save_calls += 1


def _entry(eid: int, steps=(), addresses=()) -> SimpleNamespace:
    return SimpleNamespace(
        id=eid, version="0.9.0", date="2026-06-28", title=f"Entry {eid}",
        items=("x",), test_steps=steps, addresses=addresses,
    )


def _make_db(tmp_path, suffix: str = "nav.db"):
    from metatv.core.database import Database
    db = Database(f"sqlite:///{tmp_path / suffix}")
    db.create_tables()
    return db


def _insert(db, cid, *, media_type="movie", progress=0, completed=False, hidden=False):
    from metatv.core.database import ChannelDB
    with db.session_scope() as session:
        session.add(ChannelDB(
            id=cid, source_id="1", provider_id="p", name=f"Ch {cid}",
            media_type=media_type, watch_progress=progress,
            watch_completed=completed, is_hidden=hidden,
        ))


def _go_buttons(win):
    """Return every "Go ▸" deep-link button currently in the window."""
    from PyQt6.QtWidgets import QPushButton
    return [b for b in win.findChildren(QPushButton) if b.text().startswith("Go")]


def _addressed_buttons(win):
    """Return every clickable 'Addressed …' badge button in the window."""
    from PyQt6.QtWidgets import QPushButton
    return [b for b in win.findChildren(QPushButton) if "Addressed" in b.text()]


# ── 1. step model: str | (text, target) ─────────────────────────────────────

def test_step_text_and_target_helpers():
    """step_text/step_target read both a plain str and a (text, target) tuple."""
    from metatv.whats_new import step_target, step_text

    assert step_text("plain step") == "plain step"
    assert step_target("plain step") is None

    tup = ("do the thing", "view:discover")
    assert step_text(tup) == "do the thing"
    assert step_target(tup) == "view:discover"


# ── 2. Go button rendering + routing ─────────────────────────────────────────

def test_tuple_step_renders_go_button_calling_navigate(qapp, tmp_path):
    """A (text, target) step renders a Go button that calls host.navigate_to(target)."""
    from PyQt6.QtWidgets import QWidget

    from metatv.gui.qa_checklist_window import QAChecklistWindow

    class _RecordingParent(QWidget):
        def __init__(self):
            super().__init__()
            self.nav_targets: list[str] = []

        def navigate_to(self, target):
            self.nav_targets.append(target)

    parent = _RecordingParent()
    cfg = _Cfg(tmp_path)
    entry = _entry(50, (("open discover", "view:discover"),))
    win = QAChecklistWindow(cfg, [entry], parent=parent)

    buttons = _go_buttons(win)
    assert len(buttons) == 1, "expected exactly one Go button for the targeted step"
    buttons[0].click()
    assert parent.nav_targets == ["view:discover"]


def test_plain_string_step_renders_no_go_button(qapp, tmp_path):
    """A plain-string step keeps today's behavior — no Go button (backward compat)."""
    cfg = _Cfg(tmp_path)
    from metatv.gui.qa_checklist_window import QAChecklistWindow
    win = QAChecklistWindow(cfg, [_entry(50, ("just a plain step",))])
    assert _go_buttons(win) == []


# ── 3. Addressed-PR badge is clickable → jump-to-entry ───────────────────────

def test_addressed_badge_click_invokes_jump(qapp, tmp_path):
    """Clicking the 'Addressed …' badge calls _jump_to_entry(addressing_entry_id)."""
    from metatv.gui.qa_checklist_window import QAChecklistWindow

    # Entry 50 has a FAILED step; entry 51's PR addresses it (e50_s0).
    cfg = _Cfg(tmp_path, step_results={"50": {"0": {"state": "fail", "sha": "abc"}}})
    failing = _entry(50, ("verify the thing",))
    addressing = _entry(51, ("the fix",), addresses=("e50_s0",))
    win = QAChecklistWindow(cfg, [failing, addressing])

    jumped: list = []
    win._jump_to_entry = lambda eid: jumped.append(eid)  # spy (lambda resolves at call time)

    badges = _addressed_buttons(win)
    assert badges, "expected a clickable Addressed badge on the failed step"
    badges[0].click()
    assert jumped == [51], "badge click should jump to the addressing entry"


# ── 4. navigate_to seam: view / settings / sample ────────────────────────────

class _FakeChip:
    def __init__(self):
        self.enabled = False

    def blockSignals(self, _b):
        pass

    def set_enabled(self, v):
        self.enabled = v


class _FakeHost(_NavMixin):
    """Minimal host mixing in _NavMixin to exercise navigate_to in isolation."""

    def __init__(self, db=None):
        self.calls: list = []
        self.shown: list = []
        self.db = db
        self.search_chip = _FakeChip()
        self.epg_chip = _FakeChip()
        self.prefs_chip = _FakeChip()
        self.discover_chip = _FakeChip()
        self.recipe_chip = _FakeChip()

    # switch_to_* / open_settings / details — record invocations
    def switch_to_discover_view(self):
        self.calls.append("discover")

    def switch_to_list_view(self):
        self.calls.append("list")

    def open_settings(self, tab=None):
        self.calls.append(("settings", tab))

    def show_channel_details_by_id(self, channel_id):
        self.shown.append(channel_id)

    # Synchronous stand-in for the async read seam: run the query against the
    # real DB and deliver to the main-thread slot, mirroring _run_query's contract.
    def _run_query(self, query_fn, on_result, *, token_ref=None, on_error=None):
        from metatv.core.repositories import RepositoryFactory
        with self.db.session_scope(commit=False) as session:
            data = query_fn(RepositoryFactory(session))
        on_result(data)


def test_navigate_to_view_resolves_to_switch():
    """navigate_to('view:discover') lights the chip and calls switch_to_discover_view."""
    host = _FakeHost()
    assert host.navigate_to("view:discover") is True
    assert host.calls == ["discover"]
    assert host.discover_chip.enabled is True


def test_navigate_to_settings_opens_tab():
    """navigate_to('settings:Interface') calls open_settings(tab='Interface')."""
    host = _FakeHost()
    assert host.navigate_to("settings:Interface") is True
    assert host.calls == [("settings", "Interface")]


def test_navigate_to_unknown_is_noop():
    """A malformed or unknown target no-ops (returns False, no calls)."""
    host = _FakeHost()
    assert host.navigate_to("nonsense") is False        # no ':' separator
    assert host.navigate_to("view:nope") is False        # unknown view
    assert host.navigate_to("bogus:x") is False          # unknown kind
    assert host.calls == []


def test_navigate_to_sample_resolves_real_channel(tmp_path):
    """navigate_to('sample:vod') resolves a REAL matching channel and opens it in Browse."""
    db = _make_db(tmp_path)
    _insert(db, "live1", media_type="live")
    _insert(db, "movie1", media_type="movie")
    _insert(db, "part1", media_type="movie", progress=600, completed=False)

    host = _FakeHost(db=db)
    assert host.navigate_to("sample:vod") is True
    # Lands on Browse, then opens a real movie's details.
    assert host.calls == ["list"]
    assert host.shown and host.shown[0] in ("movie1", "part1")


# ── 5. repository sample resolution (real DB) ────────────────────────────────

def test_get_sample_channel_id_matches_kind(tmp_path):
    """get_sample_channel_id returns a real id per kind; None for unknown / no-match."""
    from metatv.core.repositories import RepositoryFactory

    db = _make_db(tmp_path, "sample.db")
    _insert(db, "live1", media_type="live")
    _insert(db, "movie1", media_type="movie")
    _insert(db, "series1", media_type="series")
    _insert(db, "part1", media_type="movie", progress=900, completed=False)
    _insert(db, "done1", media_type="movie", progress=900, completed=True)
    _insert(db, "hidden_live", media_type="live", hidden=True)

    with db.session_scope(commit=False) as session:
        repo = RepositoryFactory(session).channels
        assert repo.get_sample_channel_id("live") == "live1"
        assert repo.get_sample_channel_id("series") == "series1"
        assert repo.get_sample_channel_id("vod") in ("movie1", "part1", "done1")
        # partial = progress > 0 AND not completed → part1, never done1.
        assert repo.get_sample_channel_id("partial") == "part1"
        assert repo.get_sample_channel_id("bogus") is None
