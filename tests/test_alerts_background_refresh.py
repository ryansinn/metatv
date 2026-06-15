"""Behavioral tests for WatchAlertsSection background-refresh migration (B8-7).

Pins three invariants:
1. ``_load_rows`` builds the correct grouped structure off-thread (file-backed DB,
   real queries, batched channel-name lookup).
2. ``_populate_rows`` renders WATCH NOW / UPCOMING headers and rows on the main
   thread; empty data calls set_empty(True).
3. ``show_load_error`` override adds a QTreeWidgetItem (not QListWidgetItem) so a
   failed load never crashes on a QTreeWidget.

``None`` is never returned by ``_load_rows`` for a valid-empty state — the mixin
reserves ``None`` for real exceptions.  Valid-empty returns
``{"live_groups": {}, "upcoming_only": {}}``.
"""
from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from metatv.core.database import Database, ProviderDB, ChannelDB, EpgProgramDB
from metatv.core.epg_utils import now_utc


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    """Process-wide QApplication for headless Qt widget tests."""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _fake_config(**overrides):
    """A config with a minimal set of attributes WatchAlertsSection reads."""
    defaults = dict(
        epg_watchlist_patterns=[],
        watch_alerts_icon="🔔",
        collapse_icon="▼",
        expand_icon="▶",
        play_icon="▷",
        info_icon="ℹ",
        sidebar_section_states={},
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_db(tmp_path: Path) -> Database:
    """Create a file-backed SQLite Database with tables created."""
    db_path = tmp_path / "test.db"
    db = Database(f"sqlite:///{db_path}")
    db.create_tables()
    return db


def _add_provider(session, pid, *, is_active=True, epg_url="http://e/xmltv.php", exp=None):
    session.add(ProviderDB(
        id=pid, name=pid, type="xtream", url="http://e.com",
        username="u", password="p", is_active=is_active,
        epg_url=epg_url, account_exp_date=exp,
    ))
    session.flush()


def _add_channel(session, cid, name, provider_id):
    session.add(ChannelDB(
        id=cid, source_id=cid, provider_id=provider_id, name=name,
    ))
    session.flush()


def _add_programme(session, provider_id, title, channel_db_id, *,
                   minutes_ago: int = 5, duration_minutes: int = 60):
    """Seed a programme currently airing (start in past, stop in future)."""
    now = now_utc()
    session.add(EpgProgramDB(
        provider_id=provider_id,
        channel_epg_id=f"ch.{provider_id}",
        channel_db_id=channel_db_id,
        title=title,
        start_time=now - timedelta(minutes=minutes_ago),
        stop_time=now + timedelta(minutes=duration_minutes - minutes_ago),
    ))
    session.flush()


def _add_upcoming(session, provider_id, title, channel_db_id, *, minutes_ahead: int = 30):
    """Seed a programme starting in the future."""
    now = now_utc()
    session.add(EpgProgramDB(
        provider_id=provider_id,
        channel_epg_id=f"ch.{provider_id}",
        channel_db_id=channel_db_id,
        title=title,
        start_time=now + timedelta(minutes=minutes_ahead),
        stop_time=now + timedelta(minutes=minutes_ahead + 60),
    ))
    session.flush()


# ---------------------------------------------------------------------------
# 1. _load_rows — off-thread data (file-backed DB)
# ---------------------------------------------------------------------------

def test_load_rows_returns_empty_dict_when_no_patterns(tmp_path):
    """No watchlist patterns → non-None empty dict (not a failure, not None)."""
    from metatv.gui.sidebar.alerts import WatchAlertsSection

    db = _make_db(tmp_path)
    obj = WatchAlertsSection.__new__(WatchAlertsSection)
    obj.db = db
    obj.config = _fake_config(epg_watchlist_patterns=[])

    result = obj._load_rows()

    assert result is not None, "_load_rows must never return None for valid-empty"
    assert result == {"live_groups": {}, "upcoming_only": {}}
    db.close()


def test_load_rows_returns_empty_dict_when_no_active_providers(tmp_path):
    """Active-provider list is empty → non-None empty dict."""
    from metatv.gui.sidebar.alerts import WatchAlertsSection

    db = _make_db(tmp_path)
    # Add an inactive provider (no active EPG providers)
    with db.session_scope() as session:
        _add_provider(session, "inactive", is_active=False, epg_url="http://e/xmltv.php")

    obj = WatchAlertsSection.__new__(WatchAlertsSection)
    obj.db = db
    obj.config = _fake_config(epg_watchlist_patterns=["Breaking Bad"])

    result = obj._load_rows()

    assert result is not None
    assert result == {"live_groups": {}, "upcoming_only": {}}
    db.close()


def test_load_rows_live_programme_lands_in_live_groups(tmp_path):
    """A currently-airing programme matching the watchlist pattern appears in live_groups."""
    from metatv.gui.sidebar.alerts import WatchAlertsSection

    db = _make_db(tmp_path)
    with db.session_scope() as session:
        _add_provider(session, "p1", is_active=True, epg_url="http://e/xmltv.php")
        _add_channel(session, "ch1", "BBC One HD", "p1")
        _add_programme(session, "p1", "Breaking Bad", "ch1", minutes_ago=10, duration_minutes=60)

    obj = WatchAlertsSection.__new__(WatchAlertsSection)
    obj.db = db
    obj.config = _fake_config(epg_watchlist_patterns=["Breaking Bad"])

    result = obj._load_rows()

    assert result is not None
    live_groups = result["live_groups"]
    assert len(live_groups) == 1
    key = next(iter(live_groups))
    grp = live_groups[key]
    assert grp["title"] == "Breaking Bad"
    assert len(grp["live"]) == 1
    mins_left, time_str, ch_display, channel_db_id = grp["live"][0]
    assert channel_db_id == "ch1"
    # Channel display name resolved from DB (batched lookup)
    assert "BBC One" in ch_display
    # time_str indicates minutes remaining
    assert "m left" in time_str or time_str == "ending"
    db.close()


def test_load_rows_upcoming_programme_lands_in_upcoming_only(tmp_path):
    """An upcoming programme matching the watchlist pattern appears in upcoming_only."""
    from metatv.gui.sidebar.alerts import WatchAlertsSection

    db = _make_db(tmp_path)
    with db.session_scope() as session:
        _add_provider(session, "p1", is_active=True, epg_url="http://e/xmltv.php")
        _add_channel(session, "ch1", "CNN HD", "p1")
        _add_upcoming(session, "p1", "The Wire", "ch1", minutes_ahead=30)

    obj = WatchAlertsSection.__new__(WatchAlertsSection)
    obj.db = db
    obj.config = _fake_config(epg_watchlist_patterns=["The Wire"])

    result = obj._load_rows()

    assert result is not None
    upcoming_only = result["upcoming_only"]
    assert len(upcoming_only) == 1
    key = next(iter(upcoming_only))
    grp = upcoming_only[key]
    assert grp["title"] == "The Wire"
    assert len(grp["airings"]) == 1
    ts, time_str, ch_display, channel_db_id = grp["airings"][0]
    assert channel_db_id == "ch1"
    # Channel display resolved from batched lookup
    assert "CNN" in ch_display
    # ~30 minutes ahead → "in NNm" (exact minute may shift by ±1 due to test timing)
    assert time_str.startswith("in ") and time_str.endswith("m")
    db.close()


def test_load_rows_batched_lookup_resolves_channel_names(tmp_path):
    """Multiple channels across multiple patterns are all resolved in one query batch."""
    from metatv.gui.sidebar.alerts import WatchAlertsSection

    db = _make_db(tmp_path)
    with db.session_scope() as session:
        _add_provider(session, "p1", is_active=True, epg_url="http://e/xmltv.php")
        _add_channel(session, "ch1", "Channel Alpha", "p1")
        _add_channel(session, "ch2", "Channel Beta", "p1")
        _add_programme(session, "p1", "Show Alpha", "ch1")
        _add_programme(session, "p1", "Show Beta", "ch2")

    obj = WatchAlertsSection.__new__(WatchAlertsSection)
    obj.db = db
    obj.config = _fake_config(epg_watchlist_patterns=["Show Alpha", "Show Beta"])

    result = obj._load_rows()

    live_groups = result["live_groups"]
    all_ch_displays = {
        a[2]
        for grp in live_groups.values()
        for a in grp["live"]
    }
    # Both channels must be resolved (proves batching worked for multiple channels)
    assert any("Alpha" in d for d in all_ch_displays)
    assert any("Beta" in d for d in all_ch_displays)
    db.close()


def test_load_rows_excludes_inactive_provider_programme(tmp_path):
    """PR-1 scoping: programmes from inactive providers are excluded."""
    from metatv.gui.sidebar.alerts import WatchAlertsSection

    db = _make_db(tmp_path)
    with db.session_scope() as session:
        _add_provider(session, "active-p",   is_active=True,  epg_url="http://e/xmltv.php")
        _add_provider(session, "inactive-p", is_active=False, epg_url="http://e/xmltv.php")
        _add_channel(session, "ch-active",   "Good Channel", "active-p")
        _add_channel(session, "ch-inactive", "Dead Channel", "inactive-p")
        _add_programme(session, "active-p",   "Breaking Bad", "ch-active")
        _add_programme(session, "inactive-p", "Breaking Bad", "ch-inactive")

    obj = WatchAlertsSection.__new__(WatchAlertsSection)
    obj.db = db
    obj.config = _fake_config(epg_watchlist_patterns=["Breaking Bad"])

    result = obj._load_rows()

    live_groups = result["live_groups"]
    all_cids = {
        a[3]
        for grp in live_groups.values()
        for a in grp["live"]
    }
    assert "ch-active"   in all_cids, "Active provider's programme must appear"
    assert "ch-inactive" not in all_cids, "Inactive provider's programme must be excluded"
    db.close()


def test_load_rows_excludes_expired_provider_programme(tmp_path):
    """PR-1 scoping: programmes from expired providers are excluded."""
    from metatv.gui.sidebar.alerts import WatchAlertsSection

    past = datetime.now() - timedelta(days=1)
    db = _make_db(tmp_path)
    with db.session_scope() as session:
        _add_provider(session, "good-p",    is_active=True, epg_url="http://e/xmltv.php")
        _add_provider(session, "expired-p", is_active=True, epg_url="http://e/xmltv.php", exp=past)
        _add_channel(session, "ch-good",    "Active Channel", "good-p")
        _add_channel(session, "ch-expired", "Expired Channel", "expired-p")
        _add_programme(session, "good-p",    "The Wire", "ch-good")
        _add_programme(session, "expired-p", "The Wire", "ch-expired")

    obj = WatchAlertsSection.__new__(WatchAlertsSection)
    obj.db = db
    obj.config = _fake_config(epg_watchlist_patterns=["The Wire"])

    result = obj._load_rows()

    live_groups = result["live_groups"]
    all_cids = {
        a[3]
        for grp in live_groups.values()
        for a in grp["live"]
    }
    assert "ch-good"    in all_cids,    "Active provider's programme must appear"
    assert "ch-expired" not in all_cids, "Expired provider's programme must be excluded"
    db.close()


# ---------------------------------------------------------------------------
# 2. _populate_rows — main-thread rendering (headless qapp)
# ---------------------------------------------------------------------------

def _make_section(qapp):
    """Build a WatchAlertsSection via __new__ with only the fields _populate_rows needs."""
    from PyQt6.QtWidgets import QTreeWidget
    from metatv.gui.sidebar.alerts import WatchAlertsSection

    obj = WatchAlertsSection.__new__(WatchAlertsSection)
    obj.alerts_tree = QTreeWidget()
    obj.alerts_tree.setHeaderHidden(True)
    obj.alerts_tree.setColumnCount(1)
    obj.config = _fake_config()
    obj.set_empty = MagicMock()
    # Provide stub signals so _wire_row's .connect() calls don't crash
    obj.alertClicked    = MagicMock()
    obj.alertClicked.emit = MagicMock()
    obj.channel_selected = MagicMock()
    obj.channel_selected.emit = MagicMock()
    return obj


def test_populate_rows_empty_data_calls_set_empty(qapp):
    """Empty live_groups and upcoming_only → set_empty(True), no tree items added."""
    obj = _make_section(qapp)
    obj._populate_rows({"live_groups": {}, "upcoming_only": {}})

    obj.set_empty.assert_called_once_with(True)
    assert obj.alerts_tree.topLevelItemCount() == 0


def test_populate_rows_live_adds_watch_now_header(qapp):
    """A live_groups entry produces a WATCH NOW section header and a direct-item row."""
    from metatv.core.epg_utils import now_utc as _now

    obj = _make_section(qapp)
    now = _now()
    mins_left = 45
    live_groups = {
        "breaking bad": {
            "title": "Breaking Bad",
            "live": [(mins_left, f"{mins_left}m left", "BBC One", "ch1")],
            "upcoming": [],
        }
    }
    obj._populate_rows({"live_groups": live_groups, "upcoming_only": {}})

    obj.set_empty.assert_called_once_with(False)
    # Top-level items: "WATCH NOW" header + 1 direct item = 2
    assert obj.alerts_tree.topLevelItemCount() == 2
    hdr_text = obj.alerts_tree.topLevelItem(0).text(0)
    assert hdr_text == "WATCH NOW"


def test_populate_rows_upcoming_adds_upcoming_header(qapp):
    """An upcoming_only entry produces an UPCOMING section header."""
    from datetime import timezone
    from metatv.core.epg_utils import now_utc as _now

    now = _now()
    ts = (now + timedelta(minutes=30)).timestamp()
    obj = _make_section(qapp)
    upcoming_only = {
        "the wire": {
            "title": "The Wire",
            "airings": [(ts, "in 30m", "CNN HD", "ch2")],
        }
    }
    obj._populate_rows({"live_groups": {}, "upcoming_only": upcoming_only})

    obj.set_empty.assert_called_once_with(False)
    assert obj.alerts_tree.topLevelItemCount() == 2
    hdr_text = obj.alerts_tree.topLevelItem(0).text(0)
    assert hdr_text == "UPCOMING"


def test_populate_rows_multiple_airings_creates_parent_with_children(qapp):
    """Multiple live airings for the same title produce a parent row with child rows."""
    obj = _make_section(qapp)
    live_groups = {
        "sopranos": {
            "title": "The Sopranos",
            "live": [
                (10, "10m left", "Channel A", "chA"),
                (20, "20m left", "Channel B", "chB"),
            ],
            "upcoming": [],
        }
    }
    obj._populate_rows({"live_groups": live_groups, "upcoming_only": {}})

    obj.set_empty.assert_called_once_with(False)
    # WATCH NOW header + 1 parent item = 2 top-level items
    assert obj.alerts_tree.topLevelItemCount() == 2
    parent_item = obj.alerts_tree.topLevelItem(1)
    # Parent has 2 children (one per airing)
    assert parent_item.childCount() == 2
    # Children carry channel_db_id in UserRole
    from PyQt6.QtCore import Qt
    child_ids = {
        parent_item.child(i).data(0, Qt.ItemDataRole.UserRole)
        for i in range(parent_item.childCount())
    }
    assert child_ids == {"chA", "chB"}


# ---------------------------------------------------------------------------
# 3. show_load_error override — QTreeWidget crash guard
# ---------------------------------------------------------------------------

def test_show_load_error_adds_non_selectable_tree_item(qapp):
    """Overridden show_load_error must add a QTreeWidgetItem, not call addItem (QListWidget only).

    This is the exact crash the override prevents: CollapsibleSection.show_load_error
    calls list_widget.addItem(QListWidgetItem(...)), which does not exist on QTreeWidget.
    """
    from PyQt6.QtWidgets import QTreeWidget
    from PyQt6.QtCore import Qt
    from metatv.gui.sidebar.alerts import WatchAlertsSection
    from metatv.gui import icons as _icons

    tree = QTreeWidget()
    tree.setHeaderHidden(True)
    tree.setColumnCount(1)

    obj = WatchAlertsSection.__new__(WatchAlertsSection)
    obj.set_empty = MagicMock()

    obj.show_load_error(tree, "Couldn't load watch alerts")

    # Exactly one top-level item
    assert tree.topLevelItemCount() == 1
    item = tree.topLevelItem(0)
    # Item must be non-selectable
    assert item.flags() == Qt.ItemFlag.NoItemFlags
    # Text must carry the warning icon + message
    text = item.text(0)
    assert _icons.notification_warning_icon in text
    assert "Couldn't load watch alerts" in text
    # set_empty(False) keeps the section visible (error must be seen)
    obj.set_empty.assert_called_once_with(False)


def test_show_load_error_clears_tree_before_adding_item(qapp):
    """show_load_error must clear any previous tree content before rendering the error row."""
    from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem
    from metatv.gui.sidebar.alerts import WatchAlertsSection

    tree = QTreeWidget()
    tree.setHeaderHidden(True)
    tree.setColumnCount(1)
    # Pre-populate with stale content
    tree.addTopLevelItem(QTreeWidgetItem(["stale row"]))

    obj = WatchAlertsSection.__new__(WatchAlertsSection)
    obj.set_empty = MagicMock()

    obj.show_load_error(tree, "load failed")

    assert tree.topLevelItemCount() == 1
    assert "load failed" in tree.topLevelItem(0).text(0)
