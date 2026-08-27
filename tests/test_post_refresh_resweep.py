"""Behavioral tests: whole-library title-sibling re-sweep after a content refresh.

The gap this guards (confirmed live): the free, no-network title-sibling tmdb
propagation only ran as a one-time version-gated migration + a per-provider
at-ingestion hook.  An idless row that only *becomes* adoptable later — a refresh
brings in the id-bearing variant after the one-time pass ran, or an incremental
refresh skips an unchanged row, or a lazy ``get_vod/series_info`` stamps it
``tmdb_enrich_state='none'`` — never got folded.

The fix wires ``RefreshQueueManager.all_refreshes_finished`` (fired once when the
whole refresh queue drains) → ``MainWindow._on_all_refreshes_finished``, which
re-runs the EXISTING whole-library propagation off-thread and then refreshes the
provider-dependent views.  The propagation method itself is untouched.

These execute the real changed path against a real file-backed Database
(``tmp_path``, per CLAUDE.md — never ``:memory:``) driven through the actual
``MainWindow`` seam methods.  A single fake, synchronous executor stands in for
the owner's ThreadPoolExecutor so the off-thread hop runs deterministically.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from metatv.core.database import ChannelDB, Database, ProviderDB
from metatv.core.repositories.tag import _clear_tag_cache
from metatv.gui.main_window import MainWindow


# Unbound seam methods (driven with a SimpleNamespace `self`, exactly like
# test_provider_view_refresh.py) — avoids constructing a real QMainWindow.
_ON_ALL = MainWindow._on_all_refreshes_finished
_ON_PROP = MainWindow._on_propagation_finished


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_path: Path):
    """File-backed Database with all tables (never :memory:)."""
    _clear_tag_cache()
    d = Database(f"sqlite:///{tmp_path / 'resweep.db'}")
    d.create_tables()
    yield d
    d.close()


class _SyncExecutor:
    """Drop-in for the owner's ThreadPoolExecutor that runs work inline.

    Makes the deliberately off-thread propagation hop deterministic in tests
    (the production code submits it to ``self.executor``; we just run it now).
    """

    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)
        return None


def _provider(session, pid: str, *, is_active: bool = True) -> str:
    session.add(
        ProviderDB(
            id=pid,
            name=f"Provider {pid}",
            type="xtream",
            url="http://example.com",
            username="u",
            password="p",
            is_active=is_active,
        )
    )
    session.flush()
    return pid


def _channel(
    session,
    provider_id: str,
    *,
    media_type: str = "series",
    detected_title: str,
    detected_year: str | None = None,
    detected_tmdb_id: str | None = None,
    content_key: str | None = None,
    tmdb_enrich_state: str | None = None,
) -> str:
    cid = str(uuid.uuid4())
    session.add(
        ChannelDB(
            id=cid,
            source_id=str(uuid.uuid4()),
            provider_id=provider_id,
            name=detected_title,
            media_type=media_type,
            detected_title=detected_title,
            detected_year=detected_year,
            detected_tmdb_id=detected_tmdb_id,
            content_key=content_key,
            tmdb_enrich_state=tmdb_enrich_state,
        )
    )
    session.flush()
    return cid


def _seam_self(db_obj, refresh_mock):
    """A SimpleNamespace `self` wired so the ``_propagation_finished`` signal is
    delivered synchronously to ``_on_propagation_finished`` (as the real Qt
    connection would), driving the full seam end-to-end.
    """
    me = SimpleNamespace()
    me.db = db_obj
    me.executor = _SyncExecutor()
    me._refresh_provider_dependent_views = refresh_mock
    # Emulate the queued signal → slot connection: emit(n) invokes the slot now.
    me._propagation_finished = SimpleNamespace(
        emit=lambda n: _ON_PROP(me, n)
    )
    return me


# ---------------------------------------------------------------------------
# 1. Cross-provider series convergence through the refresh-completion seam
# ---------------------------------------------------------------------------


def test_resweep_converges_cross_provider_idless_series(db):
    """The exact live gap: an idless 'none'-marked series row on source B adopts
    the id-bearing sibling from source A when the whole refresh queue drains.

    Drives the real ``_on_all_refreshes_finished`` seam.  Must FAIL if the seam
    does not invoke the whole-library propagation.
    """
    with db.session_scope() as session:
        _provider(session, "A")
        _provider(session, "B")
        # Source A ships the id (the TREX-style tmdb:60948|series variant).
        _channel(
            session, "A", media_type="series", detected_title="12 Monkeys",
            detected_tmdb_id="60948", content_key="tmdb:60948|series",
        )
        # Source B has only an idless copy that a lazy detail fetch already
        # marked 'none' — it still qualifies (filter is detected_tmdb_id IS NULL).
        idless = _channel(
            session, "B", media_type="series", detected_title="12  monkeys",
            content_key="12 monkeys|series", tmdb_enrich_state="none",
        )

    refresh = MagicMock()
    me = _seam_self(db, refresh)

    _ON_ALL(me)  # the whole-refresh completion seam

    # The idless row adopted the sibling's id + recomputed the tmdb-first key.
    with db.session_scope(commit=False) as session:
        row = session.query(
            ChannelDB.detected_tmdb_id,
            ChannelDB.content_key,
            ChannelDB.tmdb_enrich_state,
        ).filter_by(id=idless).one()
    assert row.detected_tmdb_id == "60948"
    assert row.content_key == "tmdb:60948|series"   # content_key_for chokepoint
    assert row.tmdb_enrich_state == "propagated"
    # A real fold happened → the canonical view refresh fired exactly once.
    refresh.assert_called_once()


def test_resweep_folds_many_idless_series_from_multiple_sources(db):
    """No provider_id ⇒ whole library: idless copies on *several* sources all
    converge onto the single id-bearing card (not just one provider's rows)."""
    with db.session_scope() as session:
        _provider(session, "A")
        _provider(session, "B")
        _provider(session, "C")
        _channel(
            session, "A", media_type="series", detected_title="Monos",
            detected_tmdb_id="60948", content_key="tmdb:60948|series",
        )
        b = _channel(session, "B", media_type="series", detected_title="monos",
                     content_key="monos|series")
        c = _channel(session, "C", media_type="series", detected_title="MONOS",
                     content_key="monos|series", tmdb_enrich_state="none")

    me = _seam_self(db, MagicMock())
    _ON_ALL(me)

    with db.session_scope(commit=False) as session:
        for cid in (b, c):
            key = session.query(ChannelDB.content_key).filter_by(id=cid).scalar()
            assert key == "tmdb:60948|series", f"{cid} should have folded onto the id"


# ---------------------------------------------------------------------------
# 2. Media-type safety — the sweep never crosses movie ↔ series
# ---------------------------------------------------------------------------


def test_resweep_never_crosses_media_type(db):
    """A MOVIE sharing a title with an id-bearing SERIES must NOT adopt the
    series id — content_key is namespaced and grouping is same-media_type only."""
    with db.session_scope() as session:
        _provider(session, "A")
        _provider(session, "B")
        # Id-bearing SERIES.
        _channel(
            session, "A", media_type="series", detected_title="12 Monkeys",
            detected_tmdb_id="60948", content_key="tmdb:60948|series",
        )
        # Idless MOVIE with the same title (the 1995 film is a distinct card).
        movie = _channel(
            session, "B", media_type="movie", detected_title="12 Monkeys",
            detected_year="1995", content_key="12 monkeys|movie|1995",
        )

    me = _seam_self(db, MagicMock())
    _ON_ALL(me)

    with db.session_scope(commit=False) as session:
        row = session.query(
            ChannelDB.detected_tmdb_id, ChannelDB.content_key
        ).filter_by(id=movie).one()
    assert row.detected_tmdb_id is None, "movie must not adopt the series' id"
    assert row.content_key == "12 monkeys|movie|1995", "movie stays movie-keyed"


# ---------------------------------------------------------------------------
# 3. The seam: whole-library propagation (no provider_id) → view refresh
# ---------------------------------------------------------------------------


def test_seam_invokes_whole_library_propagation_then_refreshes(monkeypatch):
    """``_on_all_refreshes_finished`` must run the propagation with NO provider_id
    (whole library) off-thread, then trigger the canonical view refresh."""
    import metatv.gui.main_window_providers as mwp

    repos = MagicMock()
    repos.channels.propagate_tmdb_from_title_siblings.return_value = 3
    monkeypatch.setattr(mwp, "RepositoryFactory", lambda session: repos)

    fake_db = MagicMock()
    # session_scope() is a context manager yielding a session.
    fake_db.session_scope.return_value.__enter__.return_value = MagicMock()
    fake_db.session_scope.return_value.__exit__.return_value = False

    refresh = MagicMock()
    me = _seam_self(fake_db, refresh)

    _ON_ALL(me)

    # Whole library: called once, with NO provider_id argument.
    repos.channels.propagate_tmdb_from_title_siblings.assert_called_once_with()
    # A positive adopt count → the canonical refresh fired.
    refresh.assert_called_once()


def test_seam_skips_refresh_when_nothing_adopted(monkeypatch):
    """A zero adopt count must NOT trigger a redundant view refresh."""
    import metatv.gui.main_window_providers as mwp

    repos = MagicMock()
    repos.channels.propagate_tmdb_from_title_siblings.return_value = 0
    monkeypatch.setattr(mwp, "RepositoryFactory", lambda session: repos)

    fake_db = MagicMock()
    fake_db.session_scope.return_value.__enter__.return_value = MagicMock()
    fake_db.session_scope.return_value.__exit__.return_value = False

    refresh = MagicMock()
    me = _seam_self(fake_db, refresh)

    _ON_ALL(me)

    repos.channels.propagate_tmdb_from_title_siblings.assert_called_once_with()
    refresh.assert_not_called()


def test_seam_swallows_propagation_error(monkeypatch):
    """A propagation failure must be logged, not raised, and never refresh."""
    import metatv.gui.main_window_providers as mwp

    repos = MagicMock()
    repos.channels.propagate_tmdb_from_title_siblings.side_effect = RuntimeError("boom")
    monkeypatch.setattr(mwp, "RepositoryFactory", lambda session: repos)

    fake_db = MagicMock()
    fake_db.session_scope.return_value.__enter__.return_value = MagicMock()
    fake_db.session_scope.return_value.__exit__.return_value = False

    refresh = MagicMock()
    me = _seam_self(fake_db, refresh)

    _ON_ALL(me)  # must not raise

    refresh.assert_not_called()


def test_on_propagation_finished_refreshes_only_on_positive():
    """The main-thread slot refreshes exactly when a real fold happened."""
    refresh = MagicMock()
    me = SimpleNamespace(_refresh_provider_dependent_views=refresh)

    _ON_PROP(me, 0)
    refresh.assert_not_called()

    _ON_PROP(me, 7)
    refresh.assert_called_once()
