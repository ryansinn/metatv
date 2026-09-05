"""PERF-16 — the Similar-titles lightbox and Explore trail-map build LAZILY.

Both overlays used to be constructed eagerly inside ``MainWindow.setup_ui`` —
paid for at every launch whether or not the user ever opens Similar Titles or
Explore. ``main_window_overlays.py``'s ``_OverlaysMixin`` moved the
construction (same constructor args, same signal connects, same
``_register_cleanable`` call) into two ensure-builders,
``_ensure_similar_lightbox``/``_ensure_trail_map``, that build on first use and
cache the result.

This file proves the construction seam itself: each ensure-builder builds
exactly once and returns the SAME instance on a second call, and the two
public entry points (``_show_similar_lightbox``, ``_show_trail_map``) trigger
that build on first call rather than assuming the widget already exists. The
"a real MainWindow has neither overlay in ``__dict__`` right after
construction" claim is proven in ``tests/test_mainwindow_launch_smoke.py``,
which already boots the real window (and then builds both overlays for real,
post-launch, to prove the init-order hazard class this file's sibling exists
to catch is still covered).

The host below is a real ``QWidget`` — not a ``MainWindow.__new__()``
skeleton — because both builders pass ``self`` as the overlay's QWidget
*parent* (``SimilarTitleLightbox``/``TrailMapView`` are QWidgets whose
``__init__`` calls ``super().__init__(parent)``), and a ``__new__()``'d
QMainWindow's underlying C++ object was never constructed.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

# The handler methods every connect() call in _ensure_similar_lightbox /
# _connect_trail_map_signals needs to exist on the host. This file is testing
# the CONSTRUCTION seam (build once, build lazily), not what these handlers
# do, so each is a no-op recorder.
_HANDLER_STUBS = (
    "play_channel_by_id",
    "_on_details_queue_toggle",
    "toggle_favorite_by_id",
    "_on_hide_from_details_pane",
    "_toggle_rating",
    "_on_suppression_requested",
    "_on_lightbox_lens_search",
    "play_channel_resume_by_id",
    "_on_details_watched_toggled",
    "_on_trail_open_details",
    "_on_trail_recipe_requested",
)


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _fake_metadata_manager():
    """Stand-in MetadataManager — these tests never reach a real network call."""

    class _FakeMM:
        async def get_metadata(self, channel_id, force_refresh=False):
            return None

    return _FakeMM()


def _make_host(tmp_path):
    """A real, shown QWidget mixing in ``_OverlaysMixin``, wired with real
    Config/Database/ImageCache and no-op handler stubs.

    Returns:
        ``(host, db)`` — the caller is responsible for closing ``db`` and
        shutting down any overlay executor it builds.
    """
    from PyQt6.QtWidgets import QWidget

    from metatv.core.config import Config
    from metatv.core.database import Database
    from metatv.core.image_cache import ImageCache
    from metatv.gui.main_window_overlays import _OverlaysMixin

    class _Host(_OverlaysMixin, QWidget):
        """Minimal real host — QWidget so it can parent the overlays."""

    host = _Host()
    host.resize(1200, 800)
    host.show()  # overlay isVisible() checks need a shown ancestor chain

    host.config = Config()
    db = Database(f"sqlite:///{tmp_path / 'overlays.db'}")
    db.create_tables()
    host.db = db
    host.image_cache = ImageCache(cache_dir=str(tmp_path / "imgcache"))
    host.metadata_manager = _fake_metadata_manager()
    host._poster_lightbox = SimpleNamespace(show_pixmap=lambda *a, **k: None)

    host._registered = []
    host._register_cleanable = lambda name, fn: host._registered.append((name, fn))
    for name in _HANDLER_STUBS:
        setattr(host, name, lambda *a, **k: None)

    return host, db


def _teardown(host, db):
    lightbox = host.__dict__.get("_lightbox")
    if lightbox is not None:
        lightbox.shutdown()
    trail_map = host.__dict__.get("_trail_map")
    if trail_map is not None:
        trail_map.shutdown()
    db.close()


class TestEnsureSimilarLightbox:
    def test_builds_once_and_reuses_the_same_instance(self, qapp, tmp_path):
        host, db = _make_host(tmp_path)
        try:
            assert "_lightbox" not in host.__dict__, "must not exist before first use"

            lb1 = host._ensure_similar_lightbox()
            assert lb1 is not None
            assert "_lightbox" in host.__dict__

            lb2 = host._ensure_similar_lightbox()
            assert lb2 is lb1, "a second call must return the SAME instance, not rebuild"

            assert ("lightbox", lb1.shutdown) in host._registered, (
                "the pool-owning widget must be registered for cleanup exactly "
                "as it was when construction was eager"
            )
        finally:
            _teardown(host, db)


class TestEnsureTrailMap:
    def test_builds_once_and_reuses_the_same_instance(self, qapp, tmp_path):
        host, db = _make_host(tmp_path)
        try:
            assert "_trail_map" not in host.__dict__, "must not exist before first use"

            tm1 = host._ensure_trail_map()
            assert tm1 is not None
            assert "_trail_map" in host.__dict__

            tm2 = host._ensure_trail_map()
            assert tm2 is tm1, "a second call must return the SAME instance, not rebuild"

            assert ("trail_map", tm1.shutdown) in host._registered, (
                "the pool-owning widget must be registered for cleanup exactly "
                "as it was when construction was eager"
            )
        finally:
            _teardown(host, db)


class TestShowSimilarLightboxBuildsLazily:
    def test_first_call_builds_and_shows_it(self, qapp, tmp_path):
        host, db = _make_host(tmp_path)
        try:
            assert "_lightbox" not in host.__dict__

            host._show_similar_lightbox(["does-not-exist"], 0, "Some Title")

            assert "_lightbox" in host.__dict__, (
                "_show_similar_lightbox must build the overlay on first call"
            )
            assert host._lightbox.isVisible()
        finally:
            _teardown(host, db)


class TestShowTrailMapBuildsLazily:
    def test_first_call_builds_it(self, qapp, tmp_path):
        host, db = _make_host(tmp_path)
        try:
            assert "_trail_map" not in host.__dict__

            host._show_trail_map(["does-not-exist"])

            assert "_trail_map" in host.__dict__, (
                "_show_trail_map must build the overlay on first call"
            )
        finally:
            _teardown(host, db)

    def test_dismisses_a_visible_similar_lightbox(self, qapp, tmp_path):
        """explore_requested's whole reason to exist: never show both at once."""
        host, db = _make_host(tmp_path)
        try:
            host._show_similar_lightbox(["does-not-exist"], 0, "Title")
            assert host._lightbox.isVisible()

            host._show_trail_map(["does-not-exist"])
            qapp.processEvents()

            assert not host._lightbox.isVisible(), (
                "opening Explore from the lightbox must hide the lightbox"
            )
        finally:
            _teardown(host, db)
