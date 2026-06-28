"""Behavioral tests for the EPG Browse bug cluster (fix/epg-browse-cluster).

Covers the four tester-flagged Browse fixes — each test EXECUTES the changed
path and asserts the outcome that would regress:

1. flagged 454e01bf — filter persistence: a STALE async browse result (search
   string no longer matches the box) must be DROPPED so a slow empty-search
   full-schedule fetch can't revert Browse to ALL content. ``_on_data_loaded``.
2. flagged 8f941952 — channel names: Browse renders the clean stored
   ``detected_title`` (prefix/quality stripped at ingestion), never the raw name;
   AND Browse honours exclusion scoping (``excluded_channel_provider_ids`` on
   ``get_schedule`` / ``search_programs`` + ``_fetch_browse`` passing
   ``get_hidden_provider_ids()``).
3. flagged fd315e75 — clear button: the Browse search box uses the project
   standard ``setClearButtonEnabled(True)`` (no custom × glyph).
4. flagged c3e1aaf3 — source detail: the header status names each source with
   freshness/staleness (label + per-source tooltip), via the
   ``epg_utils.epg_is_stale`` boundary.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from metatv.core.database import ChannelDB, Database, EpgProgramDB, ProviderDB
from metatv.core.epg_utils import now_utc, to_local
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.epg import EpgRepository
from metatv.gui.epg_browse_mixin import _EpgBrowseMixin
from metatv.gui.epg_watchlist_mixin import _EpgWatchlistMixin


# ---------------------------------------------------------------------------
# Qt fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------------------
# Fake EPG programme for the render path
# ---------------------------------------------------------------------------

class _FakeProg:
    def __init__(self, channel_db_id="c1", channel_epg_id="epg1", title="Some Show"):
        _now = datetime(2026, 6, 28, 20, 0, 0)
        self.channel_db_id = channel_db_id
        self.channel_epg_id = channel_epg_id
        self.title = title
        self.start_time = _now - timedelta(minutes=30)
        self.stop_time = _now + timedelta(minutes=30)
        self.is_live = False
        self.is_new = False


# ===========================================================================
# 1. Filter persistence — stale async result guard (flagged 454e01bf)
# ===========================================================================

def _make_dispatch_host(box_text: str):
    host = _EpgWatchlistMixin.__new__(_EpgWatchlistMixin)
    host.search_input = SimpleNamespace(text=lambda: box_text)
    host._render_browse = MagicMock()
    return host


def test_stale_browse_result_is_dropped():
    """A result tagged with an empty search must NOT render while the box says 'news'
    — this is the slow full-schedule fetch that used to revert Browse to ALL content."""
    host = _make_dispatch_host(box_text="news")
    payload = {"tab": "browse", "programs": ["everything"], "search": ""}
    _EpgWatchlistMixin._on_data_loaded(host, payload)
    host._render_browse.assert_not_called()


def test_matching_browse_result_renders():
    """A result whose search matches the current box renders normally."""
    host = _make_dispatch_host(box_text="news")
    payload = {"tab": "browse", "programs": ["matches"], "search": "news"}
    _EpgWatchlistMixin._on_data_loaded(host, payload)
    host._render_browse.assert_called_once()


def test_browse_payload_without_search_key_still_renders():
    """Back-compat: a browse payload with no 'search' key is not treated as stale."""
    host = _make_dispatch_host(box_text="anything")
    payload = {"tab": "browse", "programs": [], "placeholder": True}
    _EpgWatchlistMixin._on_data_loaded(host, payload)
    host._render_browse.assert_called_once()


def test_cleared_box_drops_old_search_result():
    """After clearing the box, a previously-issued 'news' result is stale and dropped
    so the cleared (full-schedule) result wins."""
    host = _make_dispatch_host(box_text="")
    payload = {"tab": "browse", "programs": ["old news rows"], "search": "news"}
    _EpgWatchlistMixin._on_data_loaded(host, payload)
    host._render_browse.assert_not_called()


def test_reload_browse_tags_placeholder_payload_with_search():
    """The no-providers placeholder payload carries the current search so the guard
    treats it consistently."""
    host = _EpgBrowseMixin.__new__(_EpgBrowseMixin)
    host._provider_ids = []
    host._filtered_provider_ids = lambda: []
    host.search_input = SimpleNamespace(text=lambda: "  hockey ")
    host.emitted = []
    host._data_loaded = SimpleNamespace(emit=lambda p: host.emitted.append(p))
    _EpgBrowseMixin._reload_browse(host)
    assert len(host.emitted) == 1
    assert host.emitted[0]["placeholder"] is True
    assert host.emitted[0]["search"] == "hockey"


# ===========================================================================
# 2a. Channel names render clean detected_title (flagged 8f941952)
# ===========================================================================

def _make_render_host(qapp, *, name_map, title_map):
    from PyQt6.QtWidgets import QTreeWidget, QLabel
    host = _EpgBrowseMixin.__new__(_EpgBrowseMixin)
    host.config = SimpleNamespace(epg_watchlist_patterns=[])
    host._channel_name_map = dict(name_map)
    host._channel_title_map = dict(title_map)
    host.search_input = SimpleNamespace(text=lambda: "")
    host._filtered_provider_ids = lambda: ["p1"]
    host._provider_ids = ["p1"]
    host.browse_list = QTreeWidget()
    host.browse_list.setColumnCount(4)
    host.browse_list.setHeaderLabels(["Time", "Channel", "Show", "Duration"])
    host.browse_placeholder = QLabel()
    host.browse_stats = QLabel()
    host.status_message = SimpleNamespace(emit=MagicMock())
    return host


def test_render_browse_uses_clean_detected_title(qapp):
    """Channel column must show the clean detected_title, not the raw prefixed/HD name."""
    host = _make_render_host(
        qapp,
        name_map={"c1": "US| ESPN HD"},
        title_map={"c1": "ESPN"},
    )
    _EpgBrowseMixin._render_browse(host, [_FakeProg(channel_db_id="c1", title="SportsCenter")])
    item = host.browse_list.topLevelItem(0)
    assert item.text(1) == "ESPN", f"Expected clean 'ESPN', got '{item.text(1)}'"


def test_render_browse_falls_back_to_raw_name_when_no_detected_title(qapp):
    """With no detected_title, fall back to the raw channel name (not the epg id)."""
    host = _make_render_host(qapp, name_map={"c2": "Mystery Channel"}, title_map={})
    _EpgBrowseMixin._render_browse(host, [_FakeProg(channel_db_id="c2", title="Ep 1")])
    assert host.browse_list.topLevelItem(0).text(1) == "Mystery Channel"


def test_browse_mixin_does_not_import_parse_channel_name():
    """Render must never parse at runtime — the module must not import parse_channel_name."""
    import metatv.gui.epg_browse_mixin as mod
    assert not hasattr(mod, "parse_channel_name"), (
        "epg_browse_mixin must not reference parse_channel_name (read detected_* fields)"
    )


# ===========================================================================
# 2b. Exclusion scoping — repo + _fetch_browse (flagged 8f941952)
# ===========================================================================

@pytest.fixture()
def scoped_db(tmp_path):
    """p1 active+visible (c1), p2 inactive→hidden (c2). One feed (p1) supplies both
    programmes — the second cross-matches a hidden-provider channel."""
    db = Database(f"sqlite:///{tmp_path / 'epg_scope.db'}")
    db.create_tables()
    now = now_utc()
    exp = now + timedelta(days=30)
    with db.session_scope() as s:
        s.add(ProviderDB(id="p1", name="Visible", type="xtream", url="http://a",
                         username="u", password="p", is_active=True, account_exp_date=exp))
        s.add(ProviderDB(id="p2", name="Hidden", type="xtream", url="http://b",
                         username="u", password="p", is_active=False, account_exp_date=exp))
        s.add(ChannelDB(id="c1", source_id="s1", provider_id="p1", name="ESPN HD",
                        detected_title="ESPN"))
        s.add(ChannelDB(id="c2", source_id="s2", provider_id="p2", name="FOX HD",
                        detected_title="FOX"))
        for cid, title in (("c1", "Arsenal vs Chelsea"), ("c2", "Arsenal vs Spurs")):
            s.add(EpgProgramDB(
                provider_id="p1", channel_epg_id=f"{cid}.epg", channel_db_id=cid,
                channel_name=cid, title=title, description="match",
                start_time=now + timedelta(hours=2), stop_time=now + timedelta(hours=4),
            ))
    return db, now


def test_get_schedule_excludes_hidden_provider_channels(scoped_db):
    db, now = scoped_db
    session = db.get_session()
    try:
        progs = EpgRepository(session).get_schedule(
            target_date=to_local(now + timedelta(hours=2)).date(),
            provider_ids=["p1"],
            excluded_channel_provider_ids={"p2"},
        )
        cids = {p.channel_db_id for p in progs}
        assert cids == {"c1"}, f"Hidden-provider channel leaked: {cids}"
    finally:
        session.close()


def test_search_programs_excludes_hidden_provider_channels(scoped_db):
    db, _ = scoped_db
    session = db.get_session()
    try:
        progs = EpgRepository(session).search_programs(
            "Arsenal", ["p1"], excluded_channel_provider_ids={"p2"},
        )
        cids = {p.channel_db_id for p in progs}
        assert cids == {"c1"}, f"Hidden-provider channel leaked: {cids}"
    finally:
        session.close()


def test_search_programs_without_exclusion_returns_both(scoped_db):
    """Sanity: with no exclusion set, both cross-matched channels appear."""
    db, _ = scoped_db
    session = db.get_session()
    try:
        progs = EpgRepository(session).search_programs("Arsenal", ["p1"])
        assert {p.channel_db_id for p in progs} == {"c1", "c2"}
    finally:
        session.close()


def test_fetch_browse_applies_hidden_provider_scoping(scoped_db):
    """_fetch_browse must pass get_hidden_provider_ids() so p2's channel is excluded."""
    db, _ = scoped_db
    host = _EpgBrowseMixin.__new__(_EpgBrowseMixin)
    host.db = db
    host.config = SimpleNamespace(epg_filler_patterns=[], epg_browse_hide_older_than_hours=0)
    host._channel_name_map = {}
    host._channel_title_map = {}
    host.emitted = []
    host._data_loaded = SimpleNamespace(emit=lambda p: host.emitted.append(p))

    # Forward signature: (provider_ids, anchor, search, hide_filler, after, append, gen)
    _EpgBrowseMixin._fetch_browse(
        host, provider_ids=["p1"], anchor=None, search="Arsenal",
        hide_filler=False, after=None, append=False, gen=1,
    )
    assert len(host.emitted) == 1
    payload = host.emitted[0]
    assert payload["search"] == "Arsenal"
    cids = {p.channel_db_id for p in payload["programs"]}
    assert cids == {"c1"}, f"p2 (inactive) channel leaked into Browse: {cids}"
    # And the detected_title map was populated from the stored field.
    assert host._channel_title_map["c1"] == "ESPN"


# ===========================================================================
# 3. Clear button standard (flagged fd315e75)
# ===========================================================================

def _make_browse_tab_host(qapp, config=None):
    from PyQt6.QtWidgets import QWidget, QStackedWidget
    from metatv.gui.epg_view import EpgView

    cfg = config or SimpleNamespace(
        epg_hide_filler=False,
        epg_filter_state={},
        save=MagicMock(),
    )
    host = QWidget.__new__(QWidget)
    QWidget.__init__(host, None)
    host.config = cfg
    host.stack = QStackedWidget(host)
    host._build_browse_tab = lambda: EpgView._build_browse_tab(host)
    # Real anchor-combo populate runs during build (uses browse_anchors()).
    host._refresh_browse_anchors = lambda: EpgView._refresh_browse_anchors(host)
    # Stubs for the signal targets connected during build
    host._on_search_changed = lambda *_: None
    host._reload_browse = lambda *_: None
    host._load_more_browse = lambda *_: None
    host._on_browse_scroll = lambda *_: None
    host._browse_double_click = lambda *_: None
    host._browse_selection_changed = lambda *_: None
    host._on_browse_context_menu = lambda *_: None
    host._save_epg_sort = lambda *a: None
    host._build_browse_tab()
    return host


def test_browse_search_has_standard_clear_button(qapp):
    """Browse search QLineEdit must use the project-standard setClearButtonEnabled(True)."""
    host = _make_browse_tab_host(qapp)
    assert host.search_input.isClearButtonEnabled(), (
        "Browse search box must enable the standard clear (×) button"
    )


# ===========================================================================
# 4. Source detail in header (flagged c3e1aaf3)
# ===========================================================================

@pytest.fixture()
def sources_db(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'epg_sources.db'}")
    db.create_tables()
    now = now_utc()
    with db.session_scope() as s:
        s.add(ProviderDB(id="p1", name="Acme TV", type="xtream", url="http://a",
                         username="u", password="p", is_active=True,
                         epg_data_end=now - timedelta(days=1)))   # stale
        s.add(ProviderDB(id="p2", name="Beta TV", type="xtream", url="http://b",
                         username="u", password="p", is_active=True,
                         epg_data_end=now + timedelta(days=2)))   # fresh
    return db


def _make_status_host(db, provider_ids):
    from PyQt6.QtWidgets import QLabel
    from metatv.gui.epg_view import EpgView
    host = SimpleNamespace()
    host.db = db
    host._provider_ids = list(provider_ids)
    host.status_label = QLabel("")
    host.epg_manager = SimpleNamespace(get_status_text=lambda pid: "Updated 1h ago")
    host._epg_source_info = lambda: EpgView._epg_source_info(host)
    host._update_status_label = lambda: EpgView._update_status_label(host)
    return host


def test_status_label_multi_source_shows_stale_count(qapp, sources_db):
    host = _make_status_host(sources_db, ["p1", "p2"])
    host._update_status_label()
    assert host.status_label.text() == "2 sources · 1 stale"


def test_status_tooltip_names_each_source_and_flags_stale(qapp, sources_db):
    host = _make_status_host(sources_db, ["p1", "p2"])
    host._update_status_label()
    tip = host.status_label.toolTip()
    assert "Acme TV" in tip and "Beta TV" in tip
    assert tip.count("(stale)") == 1, f"Exactly one source should be stale: {tip!r}"
    # The stale flag must sit on Acme (the past-dated guide).
    acme_line = next(ln for ln in tip.splitlines() if ln.startswith("Acme TV"))
    assert "(stale)" in acme_line


def test_status_label_single_source_includes_name(qapp, sources_db):
    host = _make_status_host(sources_db, ["p1"])
    host._update_status_label()
    assert host.status_label.text().startswith("Acme TV ·")


def test_status_label_no_sources(qapp, sources_db):
    host = _make_status_host(sources_db, [])
    host._update_status_label()
    assert host.status_label.text() == "No EPG sources"
    assert host.status_label.toolTip() == ""
