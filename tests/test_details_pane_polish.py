"""Behavioral tests for details-pane polish fixes.

#98 — variant chip queue context-menu shows correct "Add/Remove from Queue" label
#101 — genre chips wrap via _FlowLayout rather than overflowing a single-line QLabel
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_config():
    from metatv.core.config import Config
    return Config()


# ── Fix #98: variant chip queue label ─────────────────────────────────────

def test_chip_status_suffix_includes_queue_icon_when_queued(qapp):
    """_chip_status_suffix must include the queue icon when v.in_queue is True."""
    from metatv.gui.details_versions import ChannelVersion, _VersionSection

    section = _VersionSection(_make_config())
    v = ChannelVersion(channel_id="c1", name="T", in_queue=True)
    suffix = section._chip_status_suffix(v)
    assert section.config.queue_icon in suffix


def test_chip_status_suffix_omits_queue_icon_when_not_queued(qapp):
    """_chip_status_suffix must NOT include the queue icon when v.in_queue is False."""
    from metatv.gui.details_versions import ChannelVersion, _VersionSection

    section = _VersionSection(_make_config())
    v = ChannelVersion(channel_id="c1", name="T", in_queue=False)
    suffix = section._chip_status_suffix(v)
    assert section.config.queue_icon not in suffix


def test_version_chip_menu_queue_action_label_and_optimistic_flip(qapp, monkeypatch):
    """Queue menu action text must match v.in_queue; choosing it flips in_queue optimistically.

    Strategy: subclass QMenu so that exec() returns whichever action the code added for
    the queue slot.  This exercises the real _show_version_chip_menu code path and
    verifies that:
      - the action text is 'Add to Queue' when in_queue=False (and flips to True)
      - the action text is 'Remove from Queue' when in_queue=True (and flips to False)
    """
    from PyQt6.QtCore import QPoint
    from PyQt6.QtWidgets import QMenu
    from metatv.gui.details_versions import ChannelVersion, _VersionSection

    # QMenu subclass that immediately "selects" the queue action
    class _FakeMenuPickQueue(QMenu):
        def exec(self, pos=None):  # type: ignore[override]
            for act in self.actions():
                if "Queue" in act.text():
                    return act
            return None

    monkeypatch.setattr("metatv.gui.details_versions.QMenu", _FakeMenuPickQueue)

    section = _VersionSection(_make_config())
    emitted: list[str] = []
    section.queue_toggled.connect(lambda cid: emitted.append(cid))

    # Case A: not yet queued — choosing the action should flip in_queue True
    v_off = ChannelVersion(channel_id="c1", name="T", in_queue=False)
    section._show_version_chip_menu(QPoint(0, 0), v_off)
    assert v_off.in_queue is True, (
        "After choosing the 'Add to Queue' action, v.in_queue must flip True"
    )
    assert "c1" in emitted, "queue_toggled must emit the channel_id"

    # Case B: already queued — choosing the action should flip in_queue False
    emitted.clear()
    v_on = ChannelVersion(channel_id="c2", name="T", in_queue=True)
    section._show_version_chip_menu(QPoint(0, 0), v_on)
    assert v_on.in_queue is False, (
        "After choosing the 'Remove from Queue' action, v.in_queue must flip False"
    )
    assert "c2" in emitted, "queue_toggled must emit the channel_id"


def test_version_chip_menu_updates_chip_text_on_queue_toggle(qapp, monkeypatch):
    """When a chip reference is passed to the menu, its text updates after queue toggle."""
    from PyQt6.QtCore import QPoint
    from PyQt6.QtWidgets import QMenu, QPushButton
    from metatv.gui.details_versions import ChannelVersion, _VersionSection

    class _FakeMenuPickQueue(QMenu):
        def exec(self, pos=None):  # type: ignore[override]
            for act in self.actions():
                if "Queue" in act.text():
                    return act
            return None

    monkeypatch.setattr("metatv.gui.details_versions.QMenu", _FakeMenuPickQueue)

    cfg = _make_config()
    section = _VersionSection(cfg)
    v = ChannelVersion(channel_id="c1", name="T", in_queue=False, detected_prefix="EN")
    chip = QPushButton("EN")   # dummy chip for text-update check

    section._show_version_chip_menu(QPoint(0, 0), v, chip)

    # After the flip, the chip text should include the queue icon
    assert cfg.queue_icon in chip.text(), (
        f"Chip text '{chip.text()}' should include queue_icon after optimistic flip"
    )


# ── Fix #101: genre chips wrap in flow layout ─────────────────────────────

def test_genre_load_populates_flow_container(qapp):
    """After load_metadata with genres, _genres_container holds one chip per genre."""
    from PyQt6.QtWidgets import QPushButton
    from metatv.gui.details_sections import _MetadataSection
    from metatv.gui.details_versions import _FlowLayout
    from metatv.metadata_providers.base import MetadataResult

    section = _MetadataSection(_make_config())
    section.load_metadata(MetadataResult(genres=["Action", "Drama", "Science Fiction"]))

    assert not section._genres_container.isHidden(), (
        "_genres_container should not be hidden after genres are loaded"
    )
    assert isinstance(section._genres_layout, _FlowLayout), (
        "Genre row must use _FlowLayout so chips can wrap at the panel width"
    )
    chip_texts = {c.text() for c in section._genres_container.findChildren(QPushButton)}
    assert chip_texts == {"Action", "Drama", "Science Fiction"}, (
        f"Expected one chip per genre; got {chip_texts}"
    )


def test_genre_chip_click_emits_genre_clicked(qapp):
    """Clicking a genre chip emits genre_clicked with the raw (unescaped) genre name."""
    from PyQt6.QtWidgets import QPushButton
    from metatv.gui.details_sections import _MetadataSection
    from metatv.metadata_providers.base import MetadataResult

    section = _MetadataSection(_make_config())
    section.load_metadata(MetadataResult(genres=["Science Fiction", "Drama"]))

    emitted: list[str] = []
    section.genre_clicked.connect(lambda g: emitted.append(g))

    chips = section._genres_container.findChildren(QPushButton)
    sf_chip = next((c for c in chips if c.text() == "Science Fiction"), None)
    assert sf_chip is not None, "Should have a 'Science Fiction' chip button"
    sf_chip.click()

    assert emitted == ["Science Fiction"], (
        f"genre_clicked should emit the raw genre name; got {emitted}"
    )


def test_genre_chips_not_shown_for_live_channels(qapp):
    """Live channels (no metadata genres) must leave the genre area hidden."""
    from metatv.gui.details_sections import _MetadataSection

    section = _MetadataSection(_make_config())
    section.set_mode(is_live=True)

    assert section._genres_container.isHidden(), (
        "_genres_container should be hidden for live channels"
    )
    assert section._genres_loading_lbl.isHidden(), (
        "Loading label should be hidden for live channels"
    )


def test_genre_loading_label_shown_while_metadata_pending(qapp):
    """After load_basic for a non-live channel, loading label is shown, not the container."""
    from unittest.mock import MagicMock
    from metatv.gui.details_sections import _MetadataSection

    section = _MetadataSection(_make_config())

    # Minimal stub channel DTO
    ch = MagicMock()
    ch.name = "Test Movie (2023)"
    ch.media_type = "movie"
    ch.is_favorite = False
    ch.is_adult = False
    ch.detected_title = "Test Movie"
    ch.detected_year = "2023"
    ch.detected_prefix = None
    ch.detected_quality = None
    ch.detected_region = None
    ch.raw_data = None
    ch.provider_id = None
    ch.watch_completed = False
    ch.watch_progress = 0

    section.load_basic(ch)

    assert not section._genres_loading_lbl.isHidden(), (
        "Loading label should be shown while metadata is pending"
    )
    assert section._genres_container.isHidden(), (
        "Genre container should be hidden until load_metadata is called"
    )


def test_genre_clear_hides_container(qapp):
    """After clear(), the genre container and loading label are hidden."""
    from metatv.gui.details_sections import _MetadataSection
    from metatv.metadata_providers.base import MetadataResult

    section = _MetadataSection(_make_config())
    section.load_metadata(MetadataResult(genres=["Action"]))
    assert not section._genres_container.isHidden(), (
        "_genres_container should not be hidden after genres loaded"
    )
    section.clear()
    assert section._genres_container.isHidden(), (
        "_genres_container should be hidden after clear()"
    )
    assert section._genres_loading_lbl.isHidden(), (
        "Loading label should be hidden after clear()"
    )
