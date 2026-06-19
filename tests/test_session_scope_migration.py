"""Tests for B7-6 — session_scope() migration in _FavoritesMixin / _MetadataMixin.

Pins three invariants:
1. UI-thread handlers use session_scope (no raw get_session) → sessions always close.
2. ORM objects passed out of session blocks are expunged before the block exits (so
   the auto-commit on __exit__ does not expire their __dict__).
3. _on_alert_channel_context_menu closes its session BEFORE calling menu.exec(),
   fixing the session-held-during-blocking-menu bug.

The structural (AST/substring) tests below pin the *shape* of the migration. They are
necessary but NOT sufficient: a test that only asserts `"session.expunge" in src` would
still pass if expunge were placed where it doesn't actually prevent the expiry. Section 6
therefore drives the REAL handlers against a REAL in-memory session and asserts the
behavior that would actually regress — that a detached channel's columns are still readable
after the scope commits-and-closes, and (the precondition) that a non-expunged object is
not. Per CLAUDE.md "Tests must prove behavior, not shape."
"""

from __future__ import annotations

import inspect
import ast
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent / "metatv" / "gui"


# ---------------------------------------------------------------------------
# AST-level helpers
# ---------------------------------------------------------------------------

def _source(filename: str) -> str:
    return (ROOT / filename).read_text()


def _func_source(filename: str, funcname: str) -> str:
    """Return the source of a top-level or class method by name."""
    src = _source(filename)
    tree = ast.parse(src)
    lines = src.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == funcname:
            end = node.end_lineno
            start = node.lineno
            return "\n".join(lines[start - 1:end])
    raise AssertionError(f"{funcname} not found in {filename}")


def _contains(filename: str, pattern: str) -> bool:
    return pattern in _source(filename)


def _method_contains(filename: str, funcname: str, pattern: str) -> bool:
    return pattern in _func_source(filename, funcname)


# ---------------------------------------------------------------------------
# 1. No raw get_session() calls on UI thread
#    (allowed only in _apply_favorite_toggle — documented legacy exception)
# ---------------------------------------------------------------------------

def test_favorites_no_raw_get_session_except_apply_toggle():
    """_FavoritesMixin must not call get_session() except in _apply_favorite_toggle."""
    src = _source("main_window_favorites.py")
    lines = src.splitlines()
    in_apply_toggle = False
    violations = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if "def _apply_favorite_toggle" in stripped:
            in_apply_toggle = True
        elif stripped.startswith("def ") and in_apply_toggle:
            in_apply_toggle = False
        if "get_session()" in line and not in_apply_toggle:
            violations.append((i, line.strip()))
    assert not violations, (
        "Unexpected get_session() calls outside _apply_favorite_toggle:\n"
        + "\n".join(f"  L{ln}: {text}" for ln, text in violations)
    )


def test_metadata_no_raw_get_session():
    """_MetadataMixin must not call get_session() at all — all methods use session_scope."""
    src = _source("main_window_metadata.py")
    lines = src.splitlines()
    violations = [(i, l.strip()) for i, l in enumerate(lines, 1) if "get_session()" in l]
    assert not violations, (
        "Unexpected get_session() calls in main_window_metadata.py:\n"
        + "\n".join(f"  L{ln}: {text}" for ln, text in violations)
    )


# ---------------------------------------------------------------------------
# 2. session_scope present in migrated handlers
# ---------------------------------------------------------------------------

def test_context_menu_handlers_are_thin_wrappers():
    """Per-surface context-menu handlers must be thin wrappers delegating to _show_channel_menu.

    The DB work (session_scope) now lives in ``_bg_fetch_ctx_data``
    (``main_window.py``) via the unified ``_show_channel_menu`` seam.
    These thin wrappers must NOT open their own session — that would be a
    regression to the old per-handler DB pattern.
    """
    handlers = [
        "_on_queue_channel_context_menu",
        "_on_rec_channel_context_menu",
        "_on_alert_channel_context_menu",
        "_on_retry_context_menu_requested",
    ]
    for fn in handlers:
        src = _func_source("main_window_favorites.py", fn)
        assert "_show_channel_menu" in src, (
            f"{fn} must delegate to _show_channel_menu (thin wrapper)"
        )
        assert "session_scope" not in src, (
            f"{fn} must not open its own session (DB work moved to _bg_fetch_ctx_data)"
        )


def test_bg_fetch_ctx_data_uses_session_scope():
    """The unified context-menu worker _bg_fetch_ctx_data must use session_scope."""
    src = _source("main_window.py")
    # Read the _bg_fetch_ctx_data method from main_window.py
    assert "_bg_fetch_ctx_data" in src, "_bg_fetch_ctx_data must exist in main_window.py"
    assert "session_scope" in _func_source("main_window.py", "_bg_fetch_ctx_data"), (
        "_bg_fetch_ctx_data must use session_scope() for its DB work"
    )


def test_write_handlers_use_session_scope():
    """Write-path handlers must use session_scope."""
    handlers = [
        "_toggle_rating",
        "_toggle_favorite_by_id",
        "_hide_channel_from_alerts",
        "_not_interested",
        "_add_to_queue",
        "_remove_from_queue",
        "_clear_queue",
        "_clear_watched_queue",
        "_on_details_queue_toggle",
        "_hide_channel_from_history",
        "remove_from_history",
        "clear_history",
    ]
    for fn in handlers:
        assert _method_contains("main_window_favorites.py", fn, "session_scope"), (
            f"{fn} must use session_scope()"
        )


def test_play_handlers_use_session_scope():
    """Play-by-id handlers must use session_scope."""
    for fn in ("play_queue_item_id", "play_favorite_id", "play_channel_by_id",
               "play_from_history_id"):
        assert _method_contains("main_window_favorites.py", fn, "session_scope"), (
            f"{fn} must use session_scope()"
        )


def test_metadata_handlers_use_session_scope():
    """Metadata mixin handlers must use session_scope."""
    for fn in (
        "_hide_channel_from_recommendations",
        "show_channel_details_by_id",
        "on_channel_selection_changed",
        "update_details_pane_for_channel",
    ):
        assert _method_contains("main_window_metadata.py", fn, "session_scope"), (
            f"{fn} must use session_scope()"
        )


def test_metadata_workers_use_session_scope():
    """Off-thread workers in metadata mixin must also use session_scope."""
    for fn in ("_bg_fetch_action_state", "_bg_fetch_versions", "_bg_fetch_similar_titles"):
        assert _method_contains("main_window_metadata.py", fn, "session_scope"), (
            f"{fn} must use session_scope()"
        )


# ---------------------------------------------------------------------------
# 3. Session-held-during-menu bug is fixed in _on_alert_channel_context_menu
# ---------------------------------------------------------------------------

def test_ctx_data_ready_session_closed_before_exec():
    """The unified menu path must close the session before exec()-ing the menu.

    After the unified refactor, DB work runs in ``_bg_fetch_ctx_data`` off the
    main thread.  The session_scope is therefore closed before ``_ctx_data_ready``
    fires — the signal/slot boundary is the isolation.  Verify structurally that
    ``_on_ctx_data_ready`` (which receives the signal) does NOT open a session
    itself, ensuring the session is always closed before ``menu.exec``.
    """
    # _on_ctx_data_ready must not have any session_scope of its own
    src = _func_source("main_window.py", "_on_ctx_data_ready")
    assert "session_scope" not in src, (
        "_on_ctx_data_ready must not open a session — the session is closed "
        "in the worker thread before the signal fires (signal/slot = closed boundary)"
    )
    assert "menu.exec" in src, "_on_ctx_data_ready must still call menu.exec()"


# ---------------------------------------------------------------------------
# 4. ORM-object escape: expunge used for play/details handlers
# ---------------------------------------------------------------------------

def test_play_handlers_expunge_before_method_call():
    """Handlers that pass ORM channel to play_media/drill_into_series must expunge first."""
    for fn in ("play_queue_item_id", "play_favorite_id", "play_channel_by_id"):
        src = _func_source("main_window_favorites.py", fn)
        assert "session.expunge" in src, (
            f"{fn} must call session.expunge(channel) before the session block exits "
            "to prevent DetachedInstanceError after session_scope auto-commit"
        )


def test_show_details_handlers_expunge():
    """show_channel_details_by_id and on_channel_selection_changed must expunge."""
    for fn in ("show_channel_details_by_id", "on_channel_selection_changed"):
        src = _func_source("main_window_metadata.py", fn)
        assert "session.expunge" in src, (
            f"{fn} must expunge channel before session_scope exits"
        )


# ---------------------------------------------------------------------------
# 5. _apply_favorite_toggle documents its legacy exception
# ---------------------------------------------------------------------------

def test_apply_favorite_toggle_documents_legacy_reason():
    """_apply_favorite_toggle must have a docstring explaining why it keeps legacy pattern."""
    src = _func_source("main_window_favorites.py", "_apply_favorite_toggle")
    assert "expire_on_commit" in src or "legacy" in src.lower(), (
        "_apply_favorite_toggle must document why it keeps the legacy try/finally pattern"
    )


# ---------------------------------------------------------------------------
# 6. RUNTIME behavior — the half that actually regresses
#    Drive the real handlers against a real in-memory session. These would
#    catch a removed/misplaced expunge that the substring tests above cannot.
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path):
    # File-backed (not :memory:) so every pooled connection shares the same tables.
    from metatv.core.database import Database
    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.create_tables()
    yield d
    d.close()


def _seed_movie(db, name="Blade Runner") -> str:
    """Insert a movie channel; return its id."""
    from metatv.core.database import ChannelDB
    cid = str(uuid.uuid4())
    with db.session_scope() as session:
        session.add(ChannelDB(
            id=cid, source_id="s1", provider_id="p1",
            name=name, media_type="movie",
        ))
    return cid


def test_session_scope_expires_attributes_without_expunge(db):
    """Precondition the whole expunge pattern rests on.

    A channel left ATTACHED when session_scope commits-and-closes has its columns
    expired (expire_on_commit defaults True) and is then detached — accessing any
    column raises. This is *why* the handlers expunge. If this ever stops raising
    (e.g. someone sets expire_on_commit=False), the expunge calls and their
    documented rationale must be revisited.
    """
    from metatv.core.database import ChannelDB
    from sqlalchemy.orm.exc import DetachedInstanceError

    cid = _seed_movie(db)
    leaked = {}
    with db.session_scope() as session:
        leaked["ch"] = session.get(ChannelDB, cid)  # NOT expunged
    with pytest.raises(DetachedInstanceError):
        _ = leaked["ch"].name


def test_play_channel_by_id_detached_channel_is_readable(db):
    """play_channel_by_id must hand play_media a channel whose columns are still
    readable after session_scope exits — proving the real expunge line works.

    Drives the actual handler; if the expunge were removed or misplaced, accessing
    channel.media_type / .name outside the block would raise DetachedInstanceError.
    """
    from metatv.gui.main_window_favorites import _FavoritesMixin

    class _FavHost(_FavoritesMixin):
        def __init__(self, db):
            self.db = db
            self.played = []
            self.drilled = []

        def play_media(self, ch):
            self.played.append((ch.id, ch.name, ch.media_type))

        def drill_into_series(self, ch):
            self.drilled.append((ch.id, ch.name))

    cid = _seed_movie(db)
    host = _FavHost(db)
    host.play_channel_by_id(cid)
    assert host.played == [(cid, "Blade Runner", "movie")]
    assert host.drilled == []


def test_show_channel_details_by_id_detached_channel_is_readable(db):
    """show_channel_details_by_id must hand a still-readable detached channel to the
    details pane after the session closes (real expunge line, metadata mixin side)."""
    from metatv.gui.main_window_metadata import _MetadataMixin

    class _MetaHost(_MetadataMixin):
        def __init__(self, db):
            self.db = db
            self.shown = []

        def update_details_pane_for_channel(self, ch):
            self.shown.append((ch.id, ch.name, ch.provider_id))

    cid = _seed_movie(db)
    host = _MetaHost(db)
    host.show_channel_details_by_id(cid)
    assert host.shown == [(cid, "Blade Runner", "p1")]
