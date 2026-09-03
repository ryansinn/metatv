"""Behavioral regression: DiscoverView.reload() must not build shelves for a
view the user is not looking at.

Root cause (owner, 2026-09-03): the owner's launch stalls — 3,092 / 3,488 /
6,016ms shelf-build freezes — were sampled with Discover CLOSED.
``_refresh_provider_dependent_views()`` (``main_window_providers.py``) calls
``self.discover_view.reload()`` on EVERY provider mutation, and ``reload()``
ran unconditionally: it always spawned a ``_LoaderWorker`` thread and built
every pinned/expanded shelf's card widgets, whether or not Discover was the
view on screen. A nearby comment claimed similar ``reload()`` methods
"self-guard on visible" — true for ``RecipeView`` (verified: it checks
``self._active``, set in ``on_activate``/``on_deactivate``) but there was no
such guard on ``DiscoverView.reload()`` at all.

Fix: ``DiscoverView`` now tracks ``self._active`` the same way ``RecipeView``
does (True between ``on_activate()`` and ``on_deactivate()``), and
``reload()`` only marks the data dirty (``self._loaded = False``) while
inactive — the real refresh happens the next time ``on_activate()`` runs,
which already checks ``not self._loaded``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_view(tmp_path):
    """A REAL, fully-constructed DiscoverView (not __new__) backed by a real
    file DB — reload()/refresh() spawn a genuine QThread + _LoaderWorker, and
    those need a properly-initialized QObject and a DB that won't raise on a
    background thread (a MagicMock DB does)."""
    from metatv.core.config import Config
    from metatv.core.database import Database
    from metatv.gui.discover_view import DiscoverView

    db = Database(f"sqlite:///{tmp_path / 'reload_guard.db'}")
    db.create_tables()
    cfg = Config(config_dir=tmp_path / "config", data_dir=tmp_path / "data",
                 cache_dir=tmp_path / "cache")
    view = DiscoverView(db, cfg, MagicMock())
    return db, view


def _wait_for_thread(view, timeout_ms: int = 3000) -> None:
    from PyQt6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    view._worker.finished.connect(lambda: loop.quit())
    guard = QTimer()
    guard.setSingleShot(True)
    guard.setInterval(timeout_ms)
    guard.timeout.connect(loop.quit)
    guard.start()
    loop.exec()
    guard.stop()


class TestReloadSelfGuardsOnActivity:

    def test_reload_while_never_activated_marks_dirty_no_loader_no_widgets(self, qapp, tmp_path):
        """The cascade-style call site: reload() before the view has ever been
        shown must not spawn a loader thread or build any shelf widgets."""
        db, view = _make_view(tmp_path)
        try:
            assert view._active is False
            assert view._thread is None

            view.reload()

            assert view._loaded is False, "reload must mark the data dirty"
            assert view._thread is None, "an inactive reload must not start a loader thread"
            assert view._shelf_widgets == {}, "an inactive reload must not build any shelf widgets"
        finally:
            db.close()

    def test_reload_while_inactive_after_a_prior_load_also_no_ops(self, qapp, tmp_path):
        """Same guard on a SECOND reload (the realistic case:
        _refresh_provider_dependent_views fires repeatedly while some other
        view stays on screen) — must not leave stale widgets around either."""
        db, view = _make_view(tmp_path)
        try:
            view._loaded = True  # pretend a load already happened while active, then left
            view._shelf_widgets = {"genre:Stale": MagicMock()}

            view.reload()

            assert view._loaded is False
            assert view._thread is None
            # reload() itself never touches _shelf_widgets while inactive — it
            # only marks dirty. Nothing rebuilds until on_activate().
        finally:
            db.close()

    def test_reload_while_active_refreshes_immediately(self, qapp, tmp_path):
        """reload() while Discover IS the visible view still refreshes right away."""
        db, view = _make_view(tmp_path)
        try:
            view._active = True
            view._loaded = True

            view.reload()

            assert view._loaded is False
            assert view._thread is not None, "an active reload must start a loader thread"
            _wait_for_thread(view)
        finally:
            view._stop_loader(getattr(view, "_worker", None), getattr(view, "_thread", None))
            db.close()

    def test_on_activate_performs_the_deferred_load_set_by_an_inactive_reload(self, qapp, tmp_path):
        """The dirty flag an inactive reload() sets is honoured on the next
        activation — this is what makes deferring safe instead of dropping
        the reload on the floor."""
        db, view = _make_view(tmp_path)
        try:
            view.reload()  # inactive — marks dirty only, no loader
            assert view._thread is None

            view.on_activate()

            assert view._active is True
            assert view._thread is not None, "on_activate must perform the deferred load"
            _wait_for_thread(view)
        finally:
            view._stop_loader(getattr(view, "_worker", None), getattr(view, "_thread", None))
            db.close()

    def test_on_activate_sets_active_on_deactivate_clears_it(self, qapp, tmp_path):
        db, view = _make_view(tmp_path)
        try:
            assert view._active is False
            view.on_activate()
            assert view._active is True
            _wait_for_thread(view)
            view.on_deactivate()
            assert view._active is False
        finally:
            db.close()
