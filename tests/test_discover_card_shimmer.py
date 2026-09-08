"""Behavioral tests for the discover-card shimmer CPU fix.

Regression: when a poster image fails to load (404/403 etc.), the card's
infinite shimmer animation was never stopped — ImageCache emits image_failed
but the card only connected image_loaded.  With many failed-image cards on
screen this pegged a CPU core continuously.

These tests pin the exact behavior the fix introduces:
- shimmer starts on request_image()
- image_failed stops the shimmer (the regression that was pegging CPU)
- image_loaded still stops the shimmer (success path not broken)
- a non-matching URL in image_failed is ignored (shared signal guard)
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from PyQt6.QtCore import QAbstractAnimation, QObject, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication

from metatv.core.discovery_engine import ContentCard
from metatv.gui.discover_card import _ContentCard


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    """Headless QApplication — created once for the module."""
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeImageCache(QObject):
    """Minimal stand-in for ImageCache: the two signals plus subscribe(), no I/O.

    ``subscribe`` is what a card uses now — a poster is routed to the one card
    that asked for it rather than broadcast to every waiting card. The signals
    are kept because the one-per-view listeners (details pane, lightbox, trail
    map, channel-list thumbnails) still use them, and because these tests drive
    delivery by emitting.

    Emission therefore also has to reach subscribers, or a card built through
    the real code path would never hear about its own image.
    """

    image_loaded = pyqtSignal(str, QPixmap)
    image_failed = pyqtSignal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self._subs: dict[str, list[tuple]] = {}
        self.image_loaded.connect(
            lambda url, pixmap: self._deliver(url, 0, url, pixmap)
        )
        self.image_failed.connect(
            lambda url, error: self._deliver(url, 1, url, error)
        )

    def subscribe(self, url: str, on_loaded, on_failed=None) -> None:  # noqa: ANN001
        self._subs.setdefault(url, []).append((on_loaded, on_failed))

    def _deliver(self, url: str, index: int, *args) -> None:  # noqa: ANN002
        for entry in self._subs.pop(url, ()):
            callback = entry[index]
            if callback is not None:
                callback(*args)

    def get_image_async(self, url: str, provider_urls=None) -> None:  # noqa: ANN001
        # Do nothing — tests drive delivery by emitting.
        pass


def _make_card(
    qapp,  # noqa: ANN001 — ensures QApplication is live
    qtbot,  # noqa: ANN001 — registers the widget for real teardown (below)
    thumbnail_url: str = "http://example.com/poster.jpg",
) -> tuple[_ContentCard, _FakeImageCache]:
    """Build a _ContentCard widget backed by a FakeImageCache.

    A test that calls ``request_image()`` without ever emitting a delivery
    signal leaves ``cache._subs`` holding the widget's own bound methods —
    a genuine widget<->cache reference cycle Python's plain refcounting can't
    break at function-return, only cyclic GC can, on its own schedule. That
    made teardown's top-level-widget leak guard flag PRE-EXISTING tests here
    nondeterministically (confirmed: reproducible with no other change in this
    file). ``qtbot.addWidget()`` is the guard's own documented way out — the
    widget is destroyed for real at teardown regardless of any Python
    reference cycle, so every test built through this one factory gets it.
    """
    cache = _FakeImageCache()

    config = MagicMock()
    config.movie_icon = "🎬"
    config.series_icon = "📺"
    config.rating_star_icon = "⭐"
    config.like_icon = "👍"
    config.favorite_icon = "❤️"
    config.queue_icon = "🕒"
    config.watched_icon = "✓"
    config.discover_zoom = 1.0  # required by card_metrics()

    card_data = ContentCard(
        channel_id="ch-001",
        title="Test Movie",
        media_type="movie",
        thumbnail_url=thumbnail_url,
        rating=7.5,
        year=2023,
        genre="Action",
    )

    widget = _ContentCard(card_data, cache, config)
    qtbot.addWidget(widget)
    return widget, cache


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_shimmer_starts_on_request_image(qapp, qtbot):
    """request_image() starts the shimmer animation."""
    widget, cache = _make_card(qapp, qtbot)
    assert widget._shimmer is not None, "shimmer should be created for a card with thumbnail_url"

    widget.request_image()

    assert widget._shimmer.state() == QAbstractAnimation.State.Running, (
        "shimmer must be Running after request_image()"
    )


def test_shimmer_stops_on_image_failed(qapp, qtbot):
    """image_failed signal stops the shimmer — this is the CPU regression."""
    widget, cache = _make_card(qapp, qtbot)
    widget.request_image()

    assert widget._shimmer.state() == QAbstractAnimation.State.Running

    # Simulate a failed load (e.g. 404)
    cache.image_failed.emit(widget._card.thumbnail_url, "404 Not Found")

    assert widget._shimmer.state() == QAbstractAnimation.State.Stopped, (
        "shimmer must stop when image_failed fires — this was the CPU pegging bug"
    )


def test_shimmer_opacity_reset_on_failure(qapp, qtbot):
    """After image_failed, poster opacity is restored to 1.0 (no semi-transparent ghost)."""
    widget, cache = _make_card(qapp, qtbot)
    widget.request_image()

    cache.image_failed.emit(widget._card.thumbnail_url, "connection refused")

    effect = widget._poster_lbl.graphicsEffect()
    assert effect is not None
    assert effect.opacity() == pytest.approx(1.0), (
        "opacity must reset to 1.0 after failure so the card doesn't stay dimmed"
    )


def test_icon_not_hidden_after_failure(qapp, qtbot):
    """The placeholder icon must not be hidden when the poster fails to load.

    Uses isHidden() rather than isVisible() because Qt reports isVisible()=False
    for widgets whose top-level parent has never been shown (headless test).
    isHidden() reflects whether hide() was explicitly called, which is all we
    need to assert here.
    """
    widget, cache = _make_card(qapp, qtbot)
    widget.request_image()

    cache.image_failed.emit(widget._card.thumbnail_url, "timeout")

    assert not widget._icon_lbl.isHidden(), (
        "_icon_lbl must not be hidden — it is the fallback display when no poster loaded"
    )


def test_non_matching_url_ignored_by_failed_handler(qapp, qtbot):
    """image_failed for a different URL must not stop this card's shimmer."""
    widget, cache = _make_card(qapp, qtbot)
    widget.request_image()

    assert widget._shimmer.state() == QAbstractAnimation.State.Running

    # Different URL — should be ignored by this card
    cache.image_failed.emit("http://example.com/other_poster.jpg", "404")

    assert widget._shimmer.state() == QAbstractAnimation.State.Running, (
        "shimmer must keep running when the failed URL belongs to a different card"
    )


def test_shimmer_stops_on_image_loaded(qapp, qtbot):
    """Success path: image_loaded still stops the shimmer (not broken by the fix)."""
    widget, cache = _make_card(qapp, qtbot)
    widget.request_image()

    assert widget._shimmer.state() == QAbstractAnimation.State.Running

    # Create a minimal valid pixmap on the main thread (Qt requirement)
    pixmap = QPixmap(120, 175)
    pixmap.fill()

    cache.image_loaded.emit(widget._card.thumbnail_url, pixmap)

    assert widget._shimmer.state() == QAbstractAnimation.State.Stopped, (
        "shimmer must stop on successful image load"
    )


def test_icon_hidden_after_success(qapp, qtbot):
    """Placeholder icon is hidden when the real poster image loads successfully."""
    widget, cache = _make_card(qapp, qtbot)
    widget.request_image()

    pixmap = QPixmap(120, 175)
    pixmap.fill()

    cache.image_loaded.emit(widget._card.thumbnail_url, pixmap)

    assert widget._icon_lbl.isHidden(), (
        "_icon_lbl must be hidden once a real poster is displayed"
    )


def test_request_image_idempotent(qapp, qtbot):
    """Calling request_image() twice does not double-connect or double-start."""
    widget, cache = _make_card(qapp, qtbot)

    widget.request_image()
    widget.request_image()  # second call must be a no-op

    # If connections were doubled, disconnecting once inside the handler would
    # leave a dangling connection, causing a second (mis-matched) handler call.
    # Verify: after one failure emit, shimmer is stopped — not stuck running
    # because of an extra connected slot.
    cache.image_failed.emit(widget._card.thumbnail_url, "404")
    assert widget._shimmer.state() == QAbstractAnimation.State.Stopped


def test_no_shimmer_for_card_without_thumbnail(qapp, qtbot):
    """Cards with no thumbnail_url must not have a shimmer at all."""
    widget, cache = _make_card(qapp, qtbot, thumbnail_url=None)

    assert widget._shimmer is None, (
        "shimmer must be None when there is no thumbnail_url to load"
    )

    # request_image() must be safe to call (no-op on a card without a URL)
    widget.request_image()  # must not raise


# ---------------------------------------------------------------------------
# IMG-4: the shimmer is self-limiting — it must not run forever
# ---------------------------------------------------------------------------
#
# Regression: setLoopCount(-1) made the shimmer infinite, stopped ONLY by
# _on_image_loaded/_on_image_failed. IMG-3's delivery hole (the resident-LRU
# fast path never reached subscribe() callers) left hundreds of cards
# un-notified, so hundreds of infinite QPropertyAnimations kept repainting —
# ~1.1s main-thread stalls whose Python stack was empty (the work is Qt
# C++). The animation itself must now cap its own lifetime so a FUTURE
# delivery hole can't cost that again, independent of whatever bug caused
# the card to never hear back.
#
# These tests never wait out the real ~18s runtime (20 loops * 900ms) — that
# would make the suite slow for no benefit. Qt's own setCurrentTime() jump to
# the animation's total duration is what the Qt event loop does internally
# when a running, finite-loop animation reaches its end: it transitions to
# Stopped and emits finished() exactly once (verified against real
# QPropertyAnimation/QGraphicsOpacityEffect objects before writing this
# assertion). That is what "the image never arrives" looks like from the
# animation's point of view, so it is what these tests drive.

def test_shimmer_has_a_finite_loop_count(qapp, qtbot):
    """The regression itself: -1 (infinite) must never come back. This is the
    one property that would break if someone reverted the fix — not a pin on
    the exact number of loops, which is free to change."""
    widget, cache = _make_card(qapp, qtbot)

    assert widget._shimmer.loopCount() > 0, (
        "shimmer loop count must be finite — -1 runs forever and is exactly "
        "the CPU-stall regression this test exists to catch"
    )


def test_shimmer_self_stops_when_it_runs_out_the_clock(qapp, qtbot):
    """A card that never hears back (no image_loaded, no image_failed —
    exactly what IMG-3's hole looked like) still ends with a stopped
    animation and restored opacity, because the animation's own finite loop
    count ran out."""
    widget, cache = _make_card(qapp, qtbot)
    widget.request_image()

    assert widget._shimmer.state() == QAbstractAnimation.State.Running

    # Simulate the animation reaching the end of its finite loop count —
    # never triggered by the image cache at all.
    widget._shimmer.setCurrentTime(widget._shimmer.totalDuration())

    assert widget._shimmer.state() == QAbstractAnimation.State.Stopped, (
        "the shimmer must stop on its own once its finite loop count is exhausted"
    )
    effect = widget._poster_lbl.graphicsEffect()
    assert effect is not None
    assert effect.opacity() == pytest.approx(1.0), (
        "opacity must be restored to 1.0 once the shimmer self-stops"
    )
    assert not widget._icon_lbl.isHidden(), (
        "no image ever arrived — the placeholder icon must still be visible"
    )


def test_shimmer_finished_is_wired_to_stop_shimmer(qapp, qtbot):
    """The finished signal — not a per-card QTimer — is what resets opacity
    when the loop count runs out. Hundreds of cards exist; a QTimer per card
    would add an extra object for every one of them."""
    widget, cache = _make_card(qapp, qtbot)
    widget.request_image()

    effect = widget._poster_lbl.graphicsEffect()
    effect.setOpacity(0.5)  # mid-shimmer value, to prove finished() resets it

    widget._shimmer.finished.emit()

    assert widget._shimmer.state() == QAbstractAnimation.State.Stopped
    assert effect.opacity() == pytest.approx(1.0)
