"""Behavioral tests for cross-source playback resilience (#84/#93/#94).

Covered behaviors:

1. get_content_key_siblings returns the right rows (excludes self, groups by content_key,
   ranks active-before-inactive, NULL content_key → empty).

2. Play-Anyway path: _on_stream_ready with ok=False emits a "Play Anyway" action that
   calls player_manager.play with the original URL and the correct provider_id
   (player-instance-keying rule).

3. Advisory-error flag: _is_advisory_error returns True for HTTP 401/403/511, False for
   text errors and empty strings.

4. Toast deduplication: a second failure for the same channel_id dismisses the first
   failure toast before showing a new one.

5. Variant chip: the chip label includes the provider icon from provider_map + region/quality;
   left-clicking a chip emits version_selected (show details, not play); right-click wires to
   the context menu which emits play_version_requested.

All DB tests use file-backed SQLite (tmp_path) per CLAUDE.md rule.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(tmp_path: Path):
    from metatv.core.database import Database
    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.create_tables()
    return d


def _insert_provider(session, provider_id: str, name: str, is_active: bool = True):
    from metatv.core.database import ProviderDB
    p = ProviderDB(
        id=provider_id,
        name=name,
        type="xtream",
        url="http://example.com",
        is_active=is_active,
        urls=[],
    )
    session.add(p)
    session.flush()
    return p


def _insert_channel(session, provider_id: str, content_key: str | None, name: str,
                    detected_quality: str | None = None) -> str:
    from metatv.core.database import ChannelDB
    ch_id = str(uuid.uuid4())
    ch = ChannelDB(
        id=ch_id,
        source_id=str(uuid.uuid4()),
        provider_id=provider_id,
        name=name,
        content_key=content_key,
        detected_quality=detected_quality,
        stream_url=f"http://example.com/{ch_id}.ts",
        media_type="live",
    )
    session.add(ch)
    session.flush()
    return ch_id


# ---------------------------------------------------------------------------
# Part 1: get_content_key_siblings
# ---------------------------------------------------------------------------

def test_siblings_returns_others_with_same_key(tmp_path):
    """get_content_key_siblings returns sibling channels grouped by content_key."""
    db = _make_db(tmp_path)
    with db.session_scope() as session:
        _insert_provider(session, "p1", "ProSat", is_active=True)
        _insert_provider(session, "p2", "IPTV Ninja", is_active=True)
        _insert_provider(session, "p3", "TREX", is_active=True)

        target_id = _insert_channel(session, "p1", "fox sports 1|live", "FOX SPORTS 1")
        sibling_a = _insert_channel(session, "p2", "fox sports 1|live", "FOX SPORTS 1 HD")
        sibling_b = _insert_channel(session, "p3", "fox sports 1|live", "FS1")

    with db.session_scope(commit=False) as session:
        from metatv.core.repositories.channel import ChannelRepository
        repo = ChannelRepository(session)
        result = repo.get_content_key_siblings("fox sports 1|live", target_id)

    ids = {r["id"] for r in result}
    assert sibling_a in ids
    assert sibling_b in ids
    assert target_id not in ids   # self excluded


def test_siblings_excludes_self(tmp_path):
    """The exclude_channel_id is never returned."""
    db = _make_db(tmp_path)
    with db.session_scope() as session:
        _insert_provider(session, "p1", "Provider", is_active=True)
        ch_id = _insert_channel(session, "p1", "some|key", "Some Channel")

    with db.session_scope(commit=False) as session:
        from metatv.core.repositories.channel import ChannelRepository
        repo = ChannelRepository(session)
        result = repo.get_content_key_siblings("some|key", ch_id)

    assert result == []   # only the channel itself has this key


def test_siblings_null_key_returns_empty(tmp_path):
    """NULL/empty content_key → empty result (NULL-guard)."""
    db = _make_db(tmp_path)
    with db.session_scope() as session:
        _insert_provider(session, "p1", "Provider", is_active=True)
        ch_id = _insert_channel(session, "p1", None, "No Key Channel")

    with db.session_scope(commit=False) as session:
        from metatv.core.repositories.channel import ChannelRepository
        repo = ChannelRepository(session)
        assert repo.get_content_key_siblings("", ch_id) == []
        assert repo.get_content_key_siblings(None, ch_id) == []  # type: ignore[arg-type]


def test_siblings_ranks_active_before_inactive(tmp_path):
    """Active providers sort before inactive ones."""
    db = _make_db(tmp_path)
    with db.session_scope() as session:
        _insert_provider(session, "active", "Active Provider", is_active=True)
        _insert_provider(session, "inactive", "Inactive Provider", is_active=False)

        target_id = _insert_channel(session, "active", "movie|movie|2020", "The Movie")
        inactive_sib = _insert_channel(session, "inactive", "movie|movie|2020", "The Movie SD")
        active_sib = _insert_channel(session, "active", "movie|movie|2020", "The Movie HD",
                                     detected_quality="HD")

    with db.session_scope(commit=False) as session:
        from metatv.core.repositories.channel import ChannelRepository
        repo = ChannelRepository(session)
        result = repo.get_content_key_siblings("movie|movie|2020", target_id)

    # Active sibling must appear before inactive
    result_ids = [r["id"] for r in result]
    assert active_sib in result_ids
    assert inactive_sib in result_ids
    assert result_ids.index(active_sib) < result_ids.index(inactive_sib)
    # is_active flag must be set correctly
    active_row = next(r for r in result if r["id"] == active_sib)
    inactive_row = next(r for r in result if r["id"] == inactive_sib)
    assert active_row["is_active"] is True
    assert inactive_row["is_active"] is False


# ---------------------------------------------------------------------------
# Part 2: Play Anyway in _on_stream_ready
# ---------------------------------------------------------------------------

def _make_mixin():
    """Build a bare _StreamingMixin with enough mocked state for unit tests."""
    from metatv.gui.main_window_streaming import _StreamingMixin
    obj = _StreamingMixin.__new__(_StreamingMixin)
    obj.loading_channels = set()
    obj.db = MagicMock()
    obj.executor = MagicMock()
    obj.player_manager = MagicMock()
    obj.player_manager.play.return_value = True
    obj.player_manager.resolve_key.return_value = "__shared__"
    obj.notification_manager = MagicMock()
    obj.notification_manager.show.return_value = "notif-xyz"
    obj.status_bar = MagicMock()
    obj._stream_ready = MagicMock()
    obj._provider_icons = {}
    return obj


def test_on_stream_ready_play_anyway_calls_player_manager():
    """'Play Anyway' action calls player_manager.play with the ORIGINAL url + provider_id."""
    obj = _make_mixin()

    data = {
        "ok": False,
        "channel_id": "ch-1",
        "channel_name": "FOX SPORTS 1",
        "original_url": "http://trex.example.com/live/user/pass/1234.ts",
        "final_url": "",
        "stream_err": "HTTP 511",
        "notif_id": "loading-notif",
        "provider_id": "trex-provider",
        "force_new_window": False,
        "start_seconds": 0,
        "open_ended_buffer": False,
        "advisory": True,
        "siblings": [],
    }
    obj._on_stream_ready(data)

    # notification_manager.show should have been called
    obj.notification_manager.show.assert_called_once()
    call_kwargs = obj.notification_manager.show.call_args
    actions = call_kwargs.kwargs.get("actions") or (call_kwargs.args[0] if call_kwargs.args else [])
    # actions is a kwarg
    actions = obj.notification_manager.show.call_args.kwargs.get("actions", [])

    play_anyway_label, play_anyway_cb = None, None
    for label, cb in actions:
        if "Play Anyway" in label:
            play_anyway_label, play_anyway_cb = label, cb
            break

    assert play_anyway_label is not None, "Expected a 'Play Anyway' action in failure toast"

    # Invoke the callback — should call player_manager.play with original URL + provider_id
    play_anyway_cb()
    obj.player_manager.play.assert_called_once_with(
        "http://trex.example.com/live/user/pass/1234.ts",
        "FOX SPORTS 1",
        provider_id="trex-provider",
        force_new_window=False,
    )


def test_advisory_error_detection():
    """_is_advisory_error returns True for 401/403/511, False otherwise."""
    from metatv.gui.main_window_streaming import _StreamingMixin
    obj = _StreamingMixin.__new__(_StreamingMixin)

    assert obj._is_advisory_error("HTTP 401") is True
    assert obj._is_advisory_error("HTTP 403") is True
    assert obj._is_advisory_error("HTTP 511") is True
    # Non-advisory codes
    assert obj._is_advisory_error("HTTP 404") is False
    assert obj._is_advisory_error("HTTP 500") is False
    # Text errors are not advisory
    assert obj._is_advisory_error("Stream unavailable") is False
    assert obj._is_advisory_error("") is False
    assert obj._is_advisory_error(None) is False  # type: ignore[arg-type]


def test_on_stream_ready_no_retry_manager_failure_for_advisory():
    """Advisory errors do NOT call stream_retry_manager.add_failure."""
    obj = _make_mixin()
    retry_mgr = MagicMock()
    obj.stream_retry_manager = retry_mgr

    data = {
        "ok": False,
        "channel_id": "ch-2",
        "channel_name": "CNN",
        "original_url": "http://example.com/cnn.ts",
        "final_url": "",
        "stream_err": "HTTP 403",
        "notif_id": "n1",
        "provider_id": "p1",
        "force_new_window": False,
        "start_seconds": 0,
        "open_ended_buffer": False,
        "advisory": True,
        "siblings": [],
    }
    obj._on_stream_ready(data)
    retry_mgr.add_failure.assert_not_called()


def test_on_stream_ready_calls_retry_manager_for_non_advisory():
    """Non-advisory errors DO call stream_retry_manager.add_failure."""
    obj = _make_mixin()
    retry_mgr = MagicMock()
    obj.stream_retry_manager = retry_mgr

    data = {
        "ok": False,
        "channel_id": "ch-3",
        "channel_name": "ESPN",
        "original_url": "http://example.com/espn.ts",
        "final_url": "",
        "stream_err": "Stream unavailable",
        "notif_id": "n2",
        "provider_id": "p1",
        "force_new_window": False,
        "start_seconds": 0,
        "open_ended_buffer": False,
        "advisory": False,
        "siblings": [],
    }
    obj._on_stream_ready(data)
    retry_mgr.add_failure.assert_called_once()


def test_on_stream_ready_deduplicates_failure_toasts():
    """A second failure for the same channel_id dismisses the first toast."""
    obj = _make_mixin()

    # First failure
    first_notif_id = "fail-notif-1"
    obj.notification_manager.show.return_value = first_notif_id

    data1 = {
        "ok": False,
        "channel_id": "ch-dup",
        "channel_name": "TNT",
        "original_url": "http://example.com/tnt.ts",
        "final_url": "",
        "stream_err": "HTTP 511",
        "notif_id": "loading-1",
        "provider_id": "p1",
        "force_new_window": False,
        "start_seconds": 0,
        "open_ended_buffer": False,
        "advisory": True,
        "siblings": [],
    }
    obj._on_stream_ready(data1)
    assert obj._stream_fail_notifs.get("ch-dup") == first_notif_id

    # Second failure for same channel
    second_notif_id = "fail-notif-2"
    obj.notification_manager.show.return_value = second_notif_id

    data2 = dict(data1, notif_id="loading-2")
    obj._on_stream_ready(data2)

    # The first failure toast should have been dismissed
    obj.notification_manager.dismiss.assert_any_call(first_notif_id)
    # The second toast ID should be tracked
    assert obj._stream_fail_notifs.get("ch-dup") == second_notif_id


# ---------------------------------------------------------------------------
# Part 3: Variant chip — label and click behavior
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    """Headless QApplication for widget tests."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _make_version_section(qapp):
    """Build a _VersionSection with a minimal config mock."""
    from metatv.gui.details_versions import _VersionSection
    config = MagicMock()
    config.preferred_version_icon = "🎯"
    config.queue_icon = "📋"
    config.favorite_icon = "★"
    config.history_icon = "🕒"
    config.category_name_overrides = {}
    section = _VersionSection(config)
    return section


def test_chip_label_includes_provider_icon(qapp):
    """Chip label shows source icon from provider_map before the region/prefix."""
    from metatv.gui.details_versions import ChannelVersion, _VersionSection

    config = MagicMock()
    config.preferred_version_icon = "🎯"
    config.queue_icon = "📋"
    config.favorite_icon = "★"
    config.history_icon = "🕒"
    config.category_name_overrides = {}
    section = _VersionSection(config)

    provider_map = {"p-prosat": {"icon": "🅿", "name": "ProSat"}}
    v = ChannelVersion(
        channel_id="ch-abc",
        name="FOX SPORTS 1 HD",
        in_queue=False,
        detected_prefix="EN",
        detected_quality="HD",
        detected_region="US",
        provider_id="p-prosat",
        is_inactive=False,
    )

    label = section._chip_label.__func__(section, v) if False else None
    # Reload via instance (no unbound method in Python 3)
    section._provider_map = provider_map
    label = section._chip_label(v)

    assert "🅿" in label, f"Expected source icon in chip label, got: {label!r}"
    assert "HD" in label, f"Expected quality in chip label, got: {label!r}"


def test_chip_click_emits_version_selected(qapp):
    """Left-clicking an active chip emits version_selected (show details), NOT play_version_requested."""
    from metatv.gui.details_versions import ChannelVersion

    section = _make_version_section(qapp)

    selected_received = []
    play_received = []
    section.version_selected.connect(selected_received.append)
    section.play_version_requested.connect(play_received.append)

    provider_map = {"p1": {"icon": "📡", "name": "Source 1"}}
    v = ChannelVersion(
        channel_id="ch-play",
        name="FOX SPORTS 1",
        in_queue=False,
        detected_prefix="US",
        detected_quality="HD",
        provider_id="p1",
        is_inactive=False,
    )

    section.load([v], provider_map=provider_map)

    # Locate the chip button that was added to the layout
    from metatv.gui.details_versions import _FlowLayout
    layout = section._chips_layout
    chips = [layout.itemAt(i).widget() for i in range(layout.count()) if layout.itemAt(i).widget()]
    assert chips, "Expected at least one chip in the layout"
    chips[0].click()

    assert selected_received == ["ch-play"], (
        f"Expected version_selected('ch-play'), got: {selected_received!r}"
    )
    assert play_received == [], (
        f"Left-click must NOT emit play_version_requested, got: {play_received!r}"
    )


def test_inactive_chip_click_emits_version_selected(qapp):
    """Left-clicking an inactive chip emits version_selected (show details), NOT play_version_requested."""
    from metatv.gui.details_versions import ChannelVersion

    section = _make_version_section(qapp)

    selected_received = []
    play_received = []
    section.version_selected.connect(selected_received.append)
    section.play_version_requested.connect(play_received.append)

    provider_map = {"p-off": {"icon": "⛔", "name": "Inactive Source"}}
    v = ChannelVersion(
        channel_id="ch-inactive",
        name="FOX SPORTS 1 (inactive)",
        in_queue=False,
        detected_prefix="US",
        provider_id="p-off",
        is_inactive=True,
    )

    section.load([v], provider_map=provider_map)

    from metatv.gui.details_versions import _FlowLayout
    layout = section._chips_layout
    chips = [layout.itemAt(i).widget() for i in range(layout.count()) if layout.itemAt(i).widget()]
    assert chips, "Expected a chip even for inactive variant"

    chips[0].click()

    assert selected_received == ["ch-inactive"], (
        f"Inactive chip left-click must emit version_selected, got: {selected_received!r}"
    )
    assert play_received == [], (
        f"Inactive chip left-click must NOT emit play_version_requested, got: {play_received!r}"
    )


def test_chip_right_click_wires_to_context_menu(qapp):
    """Right-clicking a chip invokes _show_version_chip_menu (which offers Play via play_version_requested)."""
    from metatv.gui.details_versions import ChannelVersion
    from PyQt6.QtCore import QPoint

    section = _make_version_section(qapp)

    provider_map = {"p1": {"icon": "📡", "name": "Source 1"}}
    v = ChannelVersion(
        channel_id="ch-rightclick",
        name="ESPN HD",
        in_queue=False,
        detected_prefix="US",
        detected_quality="HD",
        provider_id="p1",
        is_inactive=False,
    )

    section.load([v], provider_map=provider_map)

    from metatv.gui.details_versions import _FlowLayout
    layout = section._chips_layout
    chips = [layout.itemAt(i).widget() for i in range(layout.count()) if layout.itemAt(i).widget()]
    assert chips, "Expected at least one chip in the layout"
    chip = chips[0]

    # Verify the chip is wired for custom context menus
    from PyQt6.QtCore import Qt
    assert chip.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu, (
        "Chip must use CustomContextMenu so right-click reaches _show_version_chip_menu"
    )

    # Simulate the customContextMenuRequested signal; verify menu helper is called
    with patch.object(section, "_show_version_chip_menu") as mock_menu:
        chip.customContextMenuRequested.emit(QPoint(0, 0))

    mock_menu.assert_called_once(), "Right-click must route to _show_version_chip_menu"


# ---------------------------------------------------------------------------
# Reactivate & play — a provider mutation must route through the canonical refresh
# ---------------------------------------------------------------------------

def test_reactivate_and_play_sibling_refreshes_dependent_views(tmp_path):
    """Reactivating an inactive source must call _refresh_provider_dependent_views.

    Toggling a provider active is a provider mutation; per the canonical-refresh
    rule the sidebar Sources / channel list / Discover must be refreshed so the
    now-active source's content appears. Without it the stream plays but those
    views stay stale until the next refresh trigger.
    """
    from metatv.gui.main_window_streaming import _StreamingMixin
    from metatv.core.repositories import RepositoryFactory

    db = _make_db(tmp_path)
    pid = "prov-inactive"
    with db.session_scope() as session:
        _insert_provider(session, pid, "Disabled Source", is_active=False)

    host = _StreamingMixin.__new__(_StreamingMixin)
    host.db = db
    host.player_manager = MagicMock()
    host._refresh_provider_dependent_views = MagicMock()

    host._reactivate_and_play_sibling(pid, "http://stream/176821.ts", "Fox East")

    # 1. Provider is now active in the DB.
    with db.session_scope() as session:
        prov = RepositoryFactory(session).providers.get_by_id(pid)
        assert prov.is_active is True, "provider must be reactivated"

    # 2. The canonical refresh fired (the gap this guards).
    host._refresh_provider_dependent_views.assert_called_once()

    # 3. The stream was played with the source's provider_id (split-keying rule).
    host.player_manager.play.assert_called_once()
    _, kwargs = host.player_manager.play.call_args
    assert kwargs.get("provider_id") == pid

    db.close()
