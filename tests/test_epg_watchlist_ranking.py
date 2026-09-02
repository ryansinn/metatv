"""Behavioral tests for EPG watchlist match ranking + "Show all in Search"
(Wave 3 slice 3A).

Ground truth: ``EpgRepository.get_live_for_watchlist`` has no LIMIT and no
quality-aware ordering — within a title-match group, channels arrive in raw SQL
order. The display caps in ``_make_watchlist_item`` (``_MAX_VISIBLE=3`` per
group, ``_MAX_GROUPS=4``) then trim an ARBITRARY subset rather than the best
one. ``_watchlist_rank_key`` fixes this by ranking channels within each group
before the caps apply: quality tier desc (4K > FHD > HD > SD, via
``channel_name_utils.quality_tier_rank``), then previously-watched
(``play_count > 0``) first within a tier, then a stable name tiebreak.

Also covers the new "Show all in Search" card action — clicking it emits
``EpgView.search_requested(pattern)``, the seam MainWindow connects to the
existing ``search_for_title`` (main_window_favorites.py) — jump-to-Search.
"""

from __future__ import annotations
from tests.conftest import with_programme_render_fields

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from metatv.gui.epg_view import EpgView


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _now() -> datetime:
    return datetime(2026, 6, 19, 20, 0, 0)


@with_programme_render_fields
class _FakeProg:
    """Minimal EpgProgramDB-shaped stub for ranking / render tests."""

    def __init__(self, channel_db_id: str, title: str = "SportsCenter",
                 channel_epg_id: str = "epg", start=None, stop=None):
        self.channel_db_id = channel_db_id
        self.channel_epg_id = channel_epg_id
        self.title = title
        self.start_time = start or (_now() - timedelta(minutes=10))
        self.stop_time = stop or (_now() + timedelta(minutes=50))


def _make_host(qapp):
    from tests.conftest import wire_watchlist_card_host

    """Minimal SimpleNamespace host with the maps _watchlist_rank_key /
    _make_watchlist_item read from, plus a real search_requested signal (built
    via a throwaway EpgView-less QObject since SimpleNamespace can't hold a
    pyqtSignal)."""
    from PyQt6.QtCore import QObject, pyqtSignal

    class _SignalHolder(QObject):
        search_requested = pyqtSignal(str)

    holder = _SignalHolder()

    host = SimpleNamespace()
    wire_watchlist_card_host(host)
    host.search_requested = holder.search_requested
    host._channel_name_map = {}
    host._channel_quality_map = {}
    host._channel_prefix_map = {}
    host._channel_title_map = {}
    host._channel_region_map = {}
    host._channel_year_map = {}
    host._channel_audio_map = {}
    host._channel_watch_map = {}
    host.config = SimpleNamespace(
        live_indicator_icon="🔴",
        watchlist_icon="🔔",
        close_icon="×",
        play_icon="▶",
        move_down_icon="▼",
        move_up_icon="▲",
        epg_watchlist_quiet_collapsed=False,
    )
    host._emit_channel_selected = MagicMock()
    host._play_channel = MagicMock()
    host._remove_pattern = MagicMock()
    host._watchlist_rank_key = lambda prog: EpgView._watchlist_rank_key(host, prog)
    return host, holder


def _seed_channel(host, cid: str, *, quality: str, title: str, play_count: int = 0):
    host._channel_quality_map[cid] = quality
    host._channel_title_map[cid] = title
    host._channel_name_map[cid] = title
    host._channel_watch_map[cid] = (play_count, None)


# ---------------------------------------------------------------------------
# Ranking key: 4K-watched > 4K > HD-watched > HD
# ---------------------------------------------------------------------------

def test_rank_key_orders_4k_watched_over_4k_over_hd_watched_over_hd(qapp):
    host, _ = _make_host(qapp)
    _seed_channel(host, "4k_watched", quality="4K", title="Chan A", play_count=5)
    _seed_channel(host, "4k_unwatched", quality="4K", title="Chan B", play_count=0)
    _seed_channel(host, "hd_watched", quality="HD", title="Chan C", play_count=2)
    _seed_channel(host, "hd_unwatched", quality="HD", title="Chan D", play_count=0)

    progs = [
        _FakeProg("hd_unwatched"),
        _FakeProg("4k_unwatched"),
        _FakeProg("hd_watched"),
        _FakeProg("4k_watched"),
    ]  # deliberately scrambled — mirrors "raw SQL order"

    ranked = sorted(progs, key=host._watchlist_rank_key)
    ranked_ids = [p.channel_db_id for p in ranked]

    assert ranked_ids == ["4k_watched", "4k_unwatched", "hd_watched", "hd_unwatched"], (
        f"expected 4K-watched > 4K > HD-watched > HD, got {ranked_ids}"
    )


def test_rank_key_stable_name_tiebreak_within_same_tier_and_watch_state(qapp):
    host, _ = _make_host(qapp)
    _seed_channel(host, "zebra", quality="HD", title="Zebra", play_count=0)
    _seed_channel(host, "alpha", quality="HD", title="Alpha", play_count=0)

    progs = [_FakeProg("zebra"), _FakeProg("alpha")]
    ranked_ids = [p.channel_db_id for p in sorted(progs, key=host._watchlist_rank_key)]

    assert ranked_ids == ["alpha", "zebra"], "same tier + same watch state → alphabetic name tiebreak"


def test_rank_key_missing_quality_and_watch_data_does_not_crash(qapp):
    """A channel_db_id absent from every map (e.g. stale/unmatched row) must not
    raise — falls back to the default tier and unwatched."""
    host, _ = _make_host(qapp)
    _seed_channel(host, "known", quality="4K", title="Known", play_count=1)
    progs = [_FakeProg("unknown-id"), _FakeProg("known")]

    ranked_ids = [p.channel_db_id for p in sorted(progs, key=host._watchlist_rank_key)]
    assert ranked_ids == ["known", "unknown-id"]


# ---------------------------------------------------------------------------
# Ranking is applied inside _make_watchlist_item (display-cap ordering)
# ---------------------------------------------------------------------------

def test_make_watchlist_item_orders_live_channel_rows_by_rank(qapp):
    """The full render path sorts each title's channel list before the
    _MAX_VISIBLE cap — assert the layout order matches the rank order (best
    first): 4K-watched, 4K, HD-watched, HD."""
    host, _ = _make_host(qapp)
    _seed_channel(host, "4k_watched", quality="4K", title="Chan A", play_count=5)
    _seed_channel(host, "4k_unwatched", quality="4K", title="Chan B", play_count=0)
    _seed_channel(host, "hd_watched", quality="HD", title="Chan C", play_count=2)
    _seed_channel(host, "hd_unwatched", quality="HD", title="Chan D", play_count=0)

    live = [
        _FakeProg("hd_unwatched", title="SportsCenter"),
        _FakeProg("4k_unwatched", title="SportsCenter"),
        _FakeProg("hd_watched", title="SportsCenter"),
        _FakeProg("4k_watched", title="SportsCenter"),
    ]

    card = EpgView._make_watchlist_item(host, "SportsCenter", live=live, upcoming=[])

    # Walk the card's widget tree collecting QLabel texts in visual order to find
    # the bare channel names in the order they were laid out.
    from PyQt6.QtWidgets import QLabel
    names_in_order = [
        w.text() for w in card.findChildren(QLabel)
        if w.text() in {"Chan A", "Chan B", "Chan C", "Chan D"}
    ]
    assert names_in_order == ["Chan A", "Chan B", "Chan C", "Chan D"], (
        f"expected rows laid out best-first (4K-watched, 4K, HD-watched, HD), "
        f"got {names_in_order}"
    )


# ---------------------------------------------------------------------------
# "Show all in Search" — emits search_requested(pattern)
# ---------------------------------------------------------------------------

def test_show_all_in_search_button_present_on_card(qapp):
    host, _ = _make_host(qapp)
    card = EpgView._make_watchlist_item(host, "NHL", live=[], upcoming=[])

    from PyQt6.QtWidgets import QPushButton
    labels = [b.text() for b in card.findChildren(QPushButton)]
    assert "Show all in Search" in labels


def test_show_all_in_search_emits_pattern(qapp):
    """Clicking the button emits search_requested with the card's pattern."""
    host, holder = _make_host(qapp)
    card = EpgView._make_watchlist_item(host, "Jeopardy!", live=[], upcoming=[])

    received: list[str] = []
    holder.search_requested.connect(received.append)

    from PyQt6.QtWidgets import QPushButton
    search_btn = next(
        b for b in card.findChildren(QPushButton) if b.text() == "Show all in Search"
    )
    search_btn.click()

    assert received == ["Jeopardy!"]


def test_show_all_in_search_uses_own_pattern_not_a_shared_one(qapp):
    """Two different cards' buttons emit their OWN pattern (no closure-capture bug)."""
    host, holder = _make_host(qapp)
    card_a = EpgView._make_watchlist_item(host, "NHL", live=[], upcoming=[])
    card_b = EpgView._make_watchlist_item(host, "MasterChef Canada", live=[], upcoming=[])

    received: list[str] = []
    holder.search_requested.connect(received.append)

    from PyQt6.QtWidgets import QPushButton
    btn_a = next(b for b in card_a.findChildren(QPushButton) if b.text() == "Show all in Search")
    btn_b = next(b for b in card_b.findChildren(QPushButton) if b.text() == "Show all in Search")
    btn_a.click()
    btn_b.click()

    assert received == ["NHL", "MasterChef Canada"]
