"""Tests for B7-6 / B10-1 — session_scope() migration in _FavoritesMixin / _MetadataMixin.

Pins three invariants:
1. UI-thread handlers use session_scope (no raw get_session) → sessions always close.
2. ORM objects no longer cross the session boundary — replaced by PlayableChannelDTO /
   PlayableEpisodeDTO (B10-1).  session.expunge() must be absent from the GUI mixins.
3. _on_alert_channel_context_menu closes its session BEFORE calling menu.exec(),
   fixing the session-held-during-blocking-menu bug.

The structural (AST/substring) tests below pin the *shape* of the migration. They are
necessary but NOT sufficient. Section 6 therefore drives the REAL handlers against a REAL
file-backed Database and asserts the behavior that would actually regress — that every DTO
field is still readable after the session_scope commits-and-closes.
Per CLAUDE.md "Tests must prove behavior, not shape."
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
# 4. B10-1 — expunge replaced by DTO; no ORM object may cross the boundary
# ---------------------------------------------------------------------------

def test_play_handlers_use_dto_not_expunge():
    """B10-1: play/queue/history handlers must use get_playable_dto, never session.expunge."""
    for fn in ("play_queue_item_id", "play_favorite_id", "play_channel_by_id",
               "play_channel_new_window_by_id"):
        src = _func_source("main_window_favorites.py", fn)
        assert "get_playable_dto" in src, (
            f"{fn} must use get_playable_dto() (B10-1 DTO pattern)"
        )
        assert "session.expunge" not in src, (
            f"{fn} must not call session.expunge — ORM boundary is now enforced by DTO"
        )


def test_show_details_handlers_use_dto_not_expunge():
    """B10-1: details-loading handlers must use get_playable_dto, never session.expunge."""
    for fn in ("show_channel_details_by_id", "on_channel_selection_changed"):
        src = _func_source("main_window_metadata.py", fn)
        assert "get_playable_dto" in src, (
            f"{fn} must use get_playable_dto() (B10-1 DTO pattern)"
        )
        assert "session.expunge" not in src, (
            f"{fn} must not call session.expunge — ORM boundary is now enforced by DTO"
        )


def test_no_expunge_in_favorites_mixin():
    """B10-1: session.expunge must not appear anywhere in _FavoritesMixin
    (except _apply_favorite_toggle, which is a documented legacy exception)."""
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
        if "session.expunge" in line and not in_apply_toggle:
            violations.append((i, line.strip()))
    assert not violations, (
        "Unexpected session.expunge() calls outside _apply_favorite_toggle:\n"
        + "\n".join(f"  L{ln}: {text}" for ln, text in violations)
    )


def test_no_expunge_in_metadata_mixin():
    """B10-1: session.expunge must not appear anywhere in _MetadataMixin."""
    src = _source("main_window_metadata.py")
    lines = src.splitlines()
    violations = [(i, l.strip()) for i, l in enumerate(lines, 1) if "session.expunge" in l]
    assert not violations, (
        "Unexpected session.expunge() calls in main_window_metadata.py:\n"
        + "\n".join(f"  L{ln}: {text}" for ln, text in violations)
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
# 6. RUNTIME behavior — the half that actually regresses (B10-1 DTO edition)
#    Drive the real handlers against a real file-backed Database and assert every
#    DTO field is readable after the session_scope commits-and-closes.
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
            stream_url="http://example.com/stream",
            is_favorite=False,
            is_hidden=False,
            is_adult=False,
        ))
    return cid


def _seed_series(db, name="Breaking Bad") -> str:
    """Insert a series channel; return its id."""
    from metatv.core.database import ChannelDB
    cid = str(uuid.uuid4())
    with db.session_scope() as session:
        session.add(ChannelDB(
            id=cid, source_id="series1", provider_id="p1",
            name=name, media_type="series",
        ))
    return cid


def _seed_episode(db, series_id: str, ep_num: int = 1) -> str:
    """Insert an episode for the given series; return episode id."""
    from metatv.core.database import EpisodeDB, SeasonDB
    from datetime import datetime
    season_id = f"{series_id}_s01"
    ep_id = f"{series_id}_e{ep_num}"
    with db.session_scope() as session:
        # SeasonDB row needed for FK integrity
        if not session.get(SeasonDB, season_id):
            session.add(SeasonDB(
                id=season_id, series_id=series_id, provider_id="p1",
                season_number=1, name="Season 1",
            ))
        session.add(EpisodeDB(
            id=ep_id, season_id=season_id, series_id=series_id,
            provider_id="p1", episode_id=str(ep_num),
            episode_num=ep_num, season_num=1,
            title=f"Episode {ep_num}",
            stream_url="http://example.com/ep",
            last_played=datetime.utcnow(),
        ))
    return ep_id


def test_session_scope_expires_attributes_without_dto(db):
    """Precondition: a raw ORM object left attached when session_scope closes has its
    columns expired (expire_on_commit=True by default) and raises DetachedInstanceError.

    This is the exact failure mode that the B10-1 DTO pattern prevents. If this ever
    stops raising (e.g. expire_on_commit=False), every get_playable_dto call site needs
    re-auditing — the DTO would still be correct, but the motivation changes.
    """
    from metatv.core.database import ChannelDB
    from sqlalchemy.orm.exc import DetachedInstanceError

    cid = _seed_movie(db)
    leaked = {}
    with db.session_scope() as session:
        leaked["ch"] = session.get(ChannelDB, cid)  # intentionally NOT converted to DTO
    with pytest.raises(DetachedInstanceError):
        _ = leaked["ch"].name


def test_get_playable_dto_all_fields_readable_after_session_close(db):
    """get_playable_dto() must return a DTO whose every field is readable after
    the session_scope closes — this is the exact regression the B10-1 migration fixes.

    Before B10-1, handlers used session.expunge() to keep the ORM object alive; a
    future relationship or deferred column would silently break that. The DTO has no
    live session reference, so it is always safe to read.
    """
    from metatv.core.repositories import RepositoryFactory
    from metatv.core.repositories.dtos import PlayableChannelDTO

    cid = _seed_movie(db)
    dto: PlayableChannelDTO | None = None
    with db.session_scope() as session:
        dto = RepositoryFactory(session).channels.get_playable_dto(cid)
    # Session is now closed — every field access below would raise if the old
    # expunge path regressed (i.e. if someone swapped back to get_by_id without expunge).
    assert dto is not None
    assert dto.id == cid
    assert dto.name == "Blade Runner"
    assert dto.source_id == "s1"
    assert dto.provider_id == "p1"
    assert dto.media_type == "movie"
    assert dto.stream_url == "http://example.com/stream"
    assert dto.is_favorite is False
    assert dto.is_hidden is False
    assert dto.is_adult is False


def test_get_playable_dto_returns_none_for_unknown_id(db):
    """get_playable_dto must return None (not raise) when channel_id does not exist."""
    from metatv.core.repositories import RepositoryFactory

    with db.session_scope() as session:
        result = RepositoryFactory(session).channels.get_playable_dto("nonexistent-id")
    assert result is None


def test_get_last_played_dto_all_fields_readable_after_session_close(db):
    """get_last_played_dto() must return a PlayableEpisodeDTO whose every field is
    readable after the session_scope closes — B10-1 episode path.
    """
    from metatv.core.repositories import RepositoryFactory
    from metatv.core.repositories.dtos import PlayableEpisodeDTO

    cid = _seed_series(db)
    _seed_episode(db, series_id="series1", ep_num=3)

    dto: PlayableEpisodeDTO | None = None
    with db.session_scope() as session:
        dto = RepositoryFactory(session).episodes.get_last_played_dto(
            series_id="series1", provider_id="p1"
        )
    # Session closed — must still read without DetachedInstanceError
    assert dto is not None
    assert dto.episode_num == 3
    assert dto.season_num == 1
    assert dto.title == "Episode 3"
    assert dto.stream_url == "http://example.com/ep"
    assert dto.provider_id == "p1"
    assert dto.series_id == "series1"


def test_get_last_played_dto_returns_none_for_unwatched_series(db):
    """get_last_played_dto returns None when there are no played episodes."""
    from metatv.core.repositories import RepositoryFactory

    # Seed episode but do NOT set last_played (it's None by default)
    from metatv.core.database import EpisodeDB, SeasonDB
    cid = _seed_series(db)
    with db.session_scope() as session:
        session.add(SeasonDB(
            id="series_unwatched_s01", series_id="series_unwatched", provider_id="p1",
            season_number=1, name="Season 1",
        ))
        session.add(EpisodeDB(
            id="series_unwatched_e1", season_id="series_unwatched_s01",
            series_id="series_unwatched", provider_id="p1",
            episode_id="1", episode_num=1, season_num=1,
            title="Pilot", last_played=None,  # never watched
        ))
    with db.session_scope() as session:
        result = RepositoryFactory(session).episodes.get_last_played_dto(
            series_id="series_unwatched", provider_id="p1"
        )
    assert result is None


def test_play_channel_by_id_dto_is_readable_after_session(db):
    """play_channel_by_id must hand play_media a PlayableChannelDTO whose columns are
    still readable after session_scope exits.

    Drives the actual handler — if get_playable_dto were swapped back to get_by_id
    without expunge, accessing ch.media_type / .name in play_media would raise.
    """
    from metatv.gui.main_window_favorites import _FavoritesMixin

    class _FavHost(_FavoritesMixin):
        def __init__(self, db):
            self.db = db
            self.played = []
            self.drilled = []

        def play_media(self, ch, force_new_window=False):
            self.played.append((ch.id, ch.name, ch.media_type))

        def drill_into_series(self, ch):
            self.drilled.append((ch.id, ch.name))

    cid = _seed_movie(db)
    host = _FavHost(db)
    host.play_channel_by_id(cid)
    assert host.played == [(cid, "Blade Runner", "movie")]
    assert host.drilled == []


def test_show_channel_details_by_id_dto_is_readable_after_session(db):
    """show_channel_details_by_id must hand a still-readable PlayableChannelDTO to
    update_details_pane_for_channel after the session closes (B10-1 metadata side)."""
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


def test_play_from_history_id_series_opens_last_episode(db):
    """play_from_history_id for a series with a played episode must call play_episode
    with a PlayableEpisodeDTO (not an ORM object) — fields must be readable.
    """
    from metatv.gui.main_window_favorites import _FavoritesMixin

    class _FavHost(_FavoritesMixin):
        def __init__(self, db):
            self.db = db
            self.episodes_played = []
            self.drilled = []

        def play_episode(self, ep):
            self.episodes_played.append((ep.id, ep.title, ep.episode_num))

        def drill_into_series(self, ch):
            self.drilled.append(ch.name)

    cid = _seed_series(db)
    _seed_episode(db, series_id="series1", ep_num=5)

    host = _FavHost(db)
    host.play_from_history_id(cid)
    # The series has a played episode → play_episode must be called
    assert len(host.episodes_played) == 1
    _ep_id, title, ep_num = host.episodes_played[0]
    assert title == "Episode 5"
    assert ep_num == 5
    assert not host.drilled
