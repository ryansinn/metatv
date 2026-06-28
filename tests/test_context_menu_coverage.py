"""Behavioral tests for the context-menu coverage fixes.

Covers three reported gaps:

1. Recipe "Now Plating" result cards must route a right-click through the same
   unified channel-menu seam Discover uses (flag 32663cdd).  We assert that a
   ``_ContentCard`` inside a ``_NowPlatingStrip`` re-emits ``cardContextMenu``
   (channel_id, gx, gy) on a context-menu event, and that the surface the recipe
   seam targets ("recommended") actually builds a populated menu.

2. The details-pane "Also available as" version chip menu must label its queue
   action by queue state — "Remove from Queue" when the variant is queued,
   "Add to Queue" otherwise (flag 02bb5b62).  We drive the real
   ``_VersionSection._show_version_chip_menu`` with ``QMenu.exec`` stubbed so the
   menu is built but not shown, then inspect the action labels.

3. Watch Queue items expose a Mark-as-Watched action — see the queue-surface
   tests in ``tests/test_channel_menu.py``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from PyQt6.QtCore import QObject, QPoint, pyqtSignal
from PyQt6.QtGui import QContextMenuEvent, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu

from metatv.core.discovery_engine import ContentCard
from metatv.gui.channel_menu import ChannelMenuContext, build_channel_menu
from metatv.gui.details_versions import ChannelVersion, _VersionSection
from metatv.gui.recipe_view import _NowPlatingStrip


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeImageCache(QObject):
    """Minimal ImageCache stand-in: exposes the two signals, does no I/O."""

    image_loaded = pyqtSignal(str, QPixmap)
    image_failed = pyqtSignal(str, str)

    def get_image_async(self, url: str, provider_urls=None) -> None:  # noqa: ANN001
        pass


def _card_config() -> MagicMock:
    """Config mock with the attributes a _ContentCard reads at construction."""
    config = MagicMock()
    config.movie_icon = "🎬"
    config.series_icon = "📺"
    config.rating_star_icon = "⭐"
    config.like_icon = "👍"
    config.favorite_icon = "❤️"
    config.queue_icon = "🕒"
    config.watched_icon = "✓"
    config.discover_zoom = 1.0
    return config


def _version_config() -> MagicMock:
    """Config mock with the attributes a _VersionSection chip menu reads."""
    config = MagicMock()
    config.preferred_version_icon = "★"
    config.queue_icon = "🕒"
    config.favorite_icon = "❤️"
    config.history_icon = "🕘"
    config.category_name_overrides = {}
    return config


# ---------------------------------------------------------------------------
# 1. Recipe "Now Plating" cards route right-click to the seam (flag 32663cdd)
# ---------------------------------------------------------------------------

def test_now_plating_card_emits_context_menu_through_seam(qapp):
    """A Now-Plating result card must re-emit cardContextMenu(channel_id, gx, gy)."""
    strip = _NowPlatingStrip(_FakeImageCache(), _card_config())
    card = ContentCard(
        channel_id="ch-rec-1",
        title="Recipe Match",
        media_type="movie",
        thumbnail_url=None,
        rating=None,
        year=2021,
        genre="Drama",
    )
    strip.load_results([card], total_count=1)

    captured: list[tuple] = []
    strip.cardContextMenu.connect(lambda cid, gx, gy: captured.append((cid, gx, gy)))

    assert strip._card_widgets, "load_results should create a result card widget"
    widget = strip._card_widgets[0]
    event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse, QPoint(5, 5), QPoint(150, 250)
    )
    widget.contextMenuEvent(event)

    assert captured == [("ch-rec-1", 150, 250)], (
        "Right-clicking a Now-Plating card must reach the unified menu seam"
    )


def test_recipe_seam_surface_builds_populated_menu(qapp):
    """The 'recommended' surface the recipe seam targets builds a real menu."""
    ctx = ChannelMenuContext(
        channel_ids=["ch-rec-1"],
        surface="recommended",
        media_type="movie",
        channel_found=True,
    )
    menu = build_channel_menu(
        ctx,
        {"play": lambda: None, "favorite": lambda: None, "queue": lambda: None},
        parent=None,
    )
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert any("Play" in t for t in texts), f"Expected a Play action, got: {texts}"


# ---------------------------------------------------------------------------
# 2. Version-chip queue label is queue-state-aware (flag 02bb5b62)
# ---------------------------------------------------------------------------

def _capture_version_chip_menu_labels(monkeypatch, section, version) -> list[str]:
    """Build (but don't show) the version-chip menu and return its action labels."""
    recorded: dict[str, list[str]] = {}

    def _fake_exec(self, *args, **kwargs):  # noqa: ANN001
        recorded["texts"] = [act.text() for act in self.actions()]
        return None  # no action chosen → no signal emitted, no optimistic flip

    monkeypatch.setattr(QMenu, "exec", _fake_exec)
    section._show_version_chip_menu(QPoint(0, 0), version)
    return recorded.get("texts", [])


def test_version_chip_menu_says_remove_when_queued(qapp, monkeypatch):
    """When the variant is already queued, the chip menu offers 'Remove from Queue'."""
    section = _VersionSection(_version_config())
    v = ChannelVersion(
        channel_id="v1", name="Movie X", in_queue=True, detected_prefix="US"
    )
    texts = _capture_version_chip_menu_labels(monkeypatch, section, v)
    assert any("Remove from Queue" in t for t in texts), (
        f"Queued variant should show 'Remove from Queue', got: {texts}"
    )
    assert not any(t.strip() == "Add to Queue" for t in texts), (
        f"Queued variant must NOT show 'Add to Queue', got: {texts}"
    )


def test_version_chip_menu_says_add_when_not_queued(qapp, monkeypatch):
    """When the variant is not queued, the chip menu offers 'Add to Queue'."""
    section = _VersionSection(_version_config())
    v = ChannelVersion(
        channel_id="v2", name="Movie Y", in_queue=False, detected_prefix="US"
    )
    texts = _capture_version_chip_menu_labels(monkeypatch, section, v)
    assert any("Add to Queue" in t for t in texts), (
        f"Unqueued variant should show 'Add to Queue', got: {texts}"
    )
    assert not any("Remove from Queue" in t for t in texts), (
        f"Unqueued variant must NOT show 'Remove from Queue', got: {texts}"
    )
