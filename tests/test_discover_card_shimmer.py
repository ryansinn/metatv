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
    """Minimal stand-in for ImageCache: exposes the two signals, no I/O."""

    image_loaded = pyqtSignal(str, QPixmap)
    image_failed = pyqtSignal(str, str)

    def get_image_async(self, url: str, provider_urls=None) -> None:  # noqa: ANN001
        # Do nothing — tests drive the signals manually.
        pass


def _make_card(
    qapp,  # noqa: ANN001 — ensures QApplication is live
    thumbnail_url: str = "http://example.com/poster.jpg",
) -> tuple[_ContentCard, _FakeImageCache]:
    """Build a _ContentCard widget backed by a FakeImageCache."""
    cache = _FakeImageCache()

    config = MagicMock()
    config.movie_icon = "🎬"
    config.series_icon = "📺"
    config.rating_star_icon = "⭐"
    config.like_icon = "👍"
    config.favorite_icon = "❤️"
    config.queue_icon = "🕒"
    config.watched_icon = "✓"

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
    return widget, cache


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_shimmer_starts_on_request_image(qapp):
    """request_image() starts the shimmer animation."""
    widget, cache = _make_card(qapp)
    assert widget._shimmer is not None, "shimmer should be created for a card with thumbnail_url"

    widget.request_image()

    assert widget._shimmer.state() == QAbstractAnimation.State.Running, (
        "shimmer must be Running after request_image()"
    )


def test_shimmer_stops_on_image_failed(qapp):
    """image_failed signal stops the shimmer — this is the CPU regression."""
    widget, cache = _make_card(qapp)
    widget.request_image()

    assert widget._shimmer.state() == QAbstractAnimation.State.Running

    # Simulate a failed load (e.g. 404)
    cache.image_failed.emit(widget._card.thumbnail_url, "404 Not Found")

    assert widget._shimmer.state() == QAbstractAnimation.State.Stopped, (
        "shimmer must stop when image_failed fires — this was the CPU pegging bug"
    )


def test_shimmer_opacity_reset_on_failure(qapp):
    """After image_failed, poster opacity is restored to 1.0 (no semi-transparent ghost)."""
    widget, cache = _make_card(qapp)
    widget.request_image()

    cache.image_failed.emit(widget._card.thumbnail_url, "connection refused")

    effect = widget._poster_lbl.graphicsEffect()
    assert effect is not None
    assert effect.opacity() == pytest.approx(1.0), (
        "opacity must reset to 1.0 after failure so the card doesn't stay dimmed"
    )


def test_icon_not_hidden_after_failure(qapp):
    """The placeholder icon must not be hidden when the poster fails to load.

    Uses isHidden() rather than isVisible() because Qt reports isVisible()=False
    for widgets whose top-level parent has never been shown (headless test).
    isHidden() reflects whether hide() was explicitly called, which is all we
    need to assert here.
    """
    widget, cache = _make_card(qapp)
    widget.request_image()

    cache.image_failed.emit(widget._card.thumbnail_url, "timeout")

    assert not widget._icon_lbl.isHidden(), (
        "_icon_lbl must not be hidden — it is the fallback display when no poster loaded"
    )


def test_non_matching_url_ignored_by_failed_handler(qapp):
    """image_failed for a different URL must not stop this card's shimmer."""
    widget, cache = _make_card(qapp)
    widget.request_image()

    assert widget._shimmer.state() == QAbstractAnimation.State.Running

    # Different URL — should be ignored by this card
    cache.image_failed.emit("http://example.com/other_poster.jpg", "404")

    assert widget._shimmer.state() == QAbstractAnimation.State.Running, (
        "shimmer must keep running when the failed URL belongs to a different card"
    )


def test_shimmer_stops_on_image_loaded(qapp):
    """Success path: image_loaded still stops the shimmer (not broken by the fix)."""
    widget, cache = _make_card(qapp)
    widget.request_image()

    assert widget._shimmer.state() == QAbstractAnimation.State.Running

    # Create a minimal valid pixmap on the main thread (Qt requirement)
    pixmap = QPixmap(120, 175)
    pixmap.fill()

    cache.image_loaded.emit(widget._card.thumbnail_url, pixmap)

    assert widget._shimmer.state() == QAbstractAnimation.State.Stopped, (
        "shimmer must stop on successful image load"
    )


def test_icon_hidden_after_success(qapp):
    """Placeholder icon is hidden when the real poster image loads successfully."""
    widget, cache = _make_card(qapp)
    widget.request_image()

    pixmap = QPixmap(120, 175)
    pixmap.fill()

    cache.image_loaded.emit(widget._card.thumbnail_url, pixmap)

    assert widget._icon_lbl.isHidden(), (
        "_icon_lbl must be hidden once a real poster is displayed"
    )


def test_request_image_idempotent(qapp):
    """Calling request_image() twice does not double-connect or double-start."""
    widget, cache = _make_card(qapp)

    widget.request_image()
    widget.request_image()  # second call must be a no-op

    # If connections were doubled, disconnecting once inside the handler would
    # leave a dangling connection, causing a second (mis-matched) handler call.
    # Verify: after one failure emit, shimmer is stopped — not stuck running
    # because of an extra connected slot.
    cache.image_failed.emit(widget._card.thumbnail_url, "404")
    assert widget._shimmer.state() == QAbstractAnimation.State.Stopped


def test_no_shimmer_for_card_without_thumbnail(qapp):
    """Cards with no thumbnail_url must not have a shimmer at all."""
    widget, cache = _make_card(qapp, thumbnail_url=None)

    assert widget._shimmer is None, (
        "shimmer must be None when there is no thumbnail_url to load"
    )

    # request_image() must be safe to call (no-op on a card without a URL)
    widget.request_image()  # must not raise
