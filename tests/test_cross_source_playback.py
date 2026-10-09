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

6. Filtered variants collapse: after load() with mixed active + filtered variants,
   filtered chips live in the collapsed FILTERED VARIANTS container (hidden by default);
   toggling the header shows them. Label sits above chips in a vertical stack.

All DB tests use file-backed SQLite (tmp_path) per CLAUDE.md rule.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

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
    from tests.conftest import wire_playback_health_stub, wire_status_method
    obj = _StreamingMixin.__new__(_StreamingMixin)
    wire_playback_health_stub(obj)   # PLAY-15: every launch path arms the watch
    obj.loading_channels = set()
    obj.db = MagicMock()
    obj.executor = MagicMock()
    obj.player_manager = MagicMock()
    obj.player_manager.play.return_value = True
    obj.player_manager.resolve_key.return_value = "__shared__"
    obj.notification_manager = MagicMock()
    obj.notification_manager.show.return_value = "notif-xyz"
    obj.status_bar = MagicMock()
    wire_status_method(obj)   # STATUS-1: _on_stream_ready etc. call self.status(...)
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

    # Invoke the callback — plays the original URL, and carries the CHANNEL ID.
    #
    # This assertion used to expect channel_id="" while the data dict above
    # carried "ch-1", which is precisely the defect: Play Anyway dropped the
    # channel's identity, so the play could not be recorded and the stream the
    # user chose never reached History (owner, 2026-09-01).
    play_anyway_cb()
    obj.player_manager.play.assert_called_once_with(
        "http://trex.example.com/live/user/pass/1234.ts",
        "FOX SPORTS 1",
        provider_id="trex-provider",
        provider_max_connections=1,
        force_new_window=False,
        start_seconds=0,
        open_ended_buffer=False,
        deep_buffer=False,
        channel_id="ch-1",
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


def test_on_stream_ready_calls_retry_manager_for_advisory():
    """Advisory errors (401/403/511) DO call stream_retry_manager.add_failure.

    Roadmap S3 (#227, the graduated play-failure ledger) deliberately revisits
    the prior advisory exclusion: a stream that always fails pre-flight with an
    advisory code (e.g. a dead XMAS-style channel returning HTTP 511 forever)
    must still enter the ledger and graduate to "dead", or it never would.
    """
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
    retry_mgr.add_failure.assert_called_once()


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


def test_on_stream_ready_prestart_fixture_names_start_time(monkeypatch):
    """A pre-flight failure for a fixture that hasn't started yet says WHEN —
    the same wording playback_start_watch.prestart_detail gives the never-
    started report (SPORT-6), not the generic "may be busy" guess.
    """
    from datetime import datetime, timedelta

    from metatv.core import epg_utils

    now = datetime(2026, 9, 2, 18, 0, 0)
    monkeypatch.setattr(epg_utils, "now_utc", lambda: now)
    start = now + timedelta(hours=2)

    obj = _make_mixin()
    data = {
        "ok": False,
        "channel_id": "ch-fixture",
        "channel_name": "Mariners x Red Sox",
        "original_url": "http://example.com/mlb.ts",
        "final_url": "",
        "stream_err": "Connection timeout",
        "notif_id": "loading-fx",
        "provider_id": "p1",
        "force_new_window": False,
        "start_seconds": 0,
        "open_ended_buffer": False,
        "siblings": [],
        "event_start_time": start,
    }
    obj._on_stream_ready(data)

    msg = obj.notification_manager.show.call_args.kwargs["message"]
    assert "hasn't started" in msg
    assert f"{epg_utils.to_local(start):%H:%M}" in msg
    assert "geo-blocked" not in msg


def test_on_stream_ready_success_dict_drops_dead_advisory_key():
    """DEBT-6: the success-path payload no longer packs the never-read
    ``advisory`` key, and ``_on_stream_ready`` no longer reads one either."""
    import inspect

    from metatv.gui import main_window_streaming as mod

    src = inspect.getsource(mod._StreamingMixin._bg_validate_and_play)
    assert '"advisory"' not in src
    ready_src = inspect.getsource(mod._StreamingMixin._on_stream_ready)
    assert '"advisory"' not in ready_src
    assert "is_advisory" not in ready_src


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
    config.details_pane_open_copy_buckets = []
    section = _VersionSection(config)
    return section


def _active_row_chips(section):
    """The "Available in" row's chips for the section's CURRENT render."""
    grid_widget = section._body_layout.itemAt(0).widget()
    flow = grid_widget.layout().itemAtPosition(0, 1).widget()
    lay = flow.layout()
    return [lay.itemAt(i).widget() for i in range(lay.count())]


def _bucket_row_chips(section, word):
    """The chips in an OPEN bucket's own labelled row ("Filtered"/"Offline")."""
    grid = section._body_layout.itemAt(0).widget().layout()
    for row in range(1, grid.rowCount()):
        key_item = grid.itemAtPosition(row, 0)
        if key_item and key_item.widget() is not None and key_item.widget().text().lower() == word:
            flow = grid.itemAtPosition(row, 1).widget()
            lay = flow.layout()
            return [lay.itemAt(i).widget() for i in range(lay.count())]
    return []


def test_chip_label_includes_provider_icon(qapp):
    """Chip label shows source icon from provider_map before the region/prefix.

    DETAILS-3c: the icon shows only when more than one source is ENABLED
    (``_show_source_icons``, set by ``load()`` from ``provider_map``'s
    "enabled" flag) — a single-source provider_map with no "enabled" key
    defaults True, so two distinct providers here still trips it.
    """
    from metatv.gui.details_versions import ChannelVersion, _VersionSection
    from tests.conftest import destroy_widget

    config = MagicMock()
    config.preferred_version_icon = "🎯"
    config.queue_icon = "📋"
    config.favorite_icon = "★"
    config.history_icon = "🕒"
    config.category_name_overrides = {}
    section = _VersionSection(config)

    provider_map = {
        "p-prosat": {"icon": "🅿", "name": "ProSat"},
        "p-other": {"icon": "🇴", "name": "Other"},
    }
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
    other = ChannelVersion(
        channel_id="ch-other", name="FOX SPORTS 1 HD (alt)", in_queue=False,
        detected_prefix="EN", provider_id="p-other",
    )

    try:
        section.load([v, other], provider_map=provider_map)
        label = section._chip_label(v)

        assert "🅿" in label, f"Expected source icon in chip label, got: {label!r}"
        assert "HD" in label, f"Expected quality in chip label, got: {label!r}"
    finally:
        destroy_widget(section)


def test_chip_click_emits_version_selected(qapp):
    """Left-clicking an active chip emits version_selected (show details), NOT play_version_requested."""
    from metatv.gui.details_versions import ChannelVersion
    from tests.conftest import destroy_widget

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

    try:
        section.load([v], provider_map=provider_map)

        chips = _active_row_chips(section)
        assert chips, "Expected at least one chip in the Available row"
        chips[0].click()

        assert selected_received == ["ch-play"], (
            f"Expected version_selected('ch-play'), got: {selected_received!r}"
        )
        assert play_received == [], (
            f"Left-click must NOT emit play_version_requested, got: {play_received!r}"
        )
    finally:
        destroy_widget(section)


def test_inactive_chip_click_emits_version_selected(qapp):
    """Left-clicking an inactive chip emits version_selected (show details), NOT play_version_requested."""
    from metatv.gui.details_versions import ChannelVersion
    from tests.conftest import destroy_widget

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

    try:
        section.load([v], provider_map=provider_map)

        # An enabled-but-expired source's variant ("offline") does not appear
        # among the available versions — a source the user turned off must
        # not be presented as something they can watch right now
        # (CRITICAL_RULES:188) — it sits behind a closed "+1 offline"
        # disclosure instead. It is still reachable once opened, and still
        # clickable, because right-click reactivate-and-play is the recovery
        # path.
        row0_texts = [c.text() for c in _active_row_chips(section)]
        assert row0_texts == ["+1 offline"], (
            f"an inactive variant must not appear among the available "
            f"versions, got {row0_texts!r}"
        )

        section._open_bucket("offline")
        chips = _bucket_row_chips(section, "offline")
        assert chips, "Expected the inactive variant to appear under the opened Offline row"

        chips[0].click()

        assert selected_received == ["ch-inactive"], (
            f"Inactive chip left-click must emit version_selected, got: {selected_received!r}"
        )
        assert play_received == [], (
            f"Inactive chip left-click must NOT emit play_version_requested, got: {play_received!r}"
        )
    finally:
        destroy_widget(section)


def test_chip_right_click_wires_to_context_menu(qapp):
    """Right-clicking a chip invokes _show_version_chip_menu (which offers Play via play_version_requested)."""
    from metatv.gui.details_versions import ChannelVersion
    from PyQt6.QtCore import QPoint, Qt
    from tests.conftest import destroy_widget

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

    try:
        section.load([v], provider_map=provider_map)

        chips = _active_row_chips(section)
        assert chips, "Expected at least one chip in the Available row"
        chip = chips[0]

        # Verify the chip is wired for custom context menus
        assert chip.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu, (
            "Chip must use CustomContextMenu so right-click reaches _show_version_chip_menu"
        )

        # Simulate the customContextMenuRequested signal; verify menu helper is called
        with patch.object(section, "_show_version_chip_menu") as mock_menu:
            chip.customContextMenuRequested.emit(QPoint(0, 0))

        mock_menu.assert_called_once(), "Right-click must route to _show_version_chip_menu"
    finally:
        destroy_widget(section)


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
    from tests.conftest import wire_playback_health_stub

    db = _make_db(tmp_path)
    pid = "prov-inactive"
    with db.session_scope() as session:
        _insert_provider(session, pid, "Disabled Source", is_active=False)

    host = _StreamingMixin.__new__(_StreamingMixin)
    wire_playback_health_stub(host)   # PLAY-15: _play_and_record arms the watch
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


# ---------------------------------------------------------------------------
# Filtered variants collapsible section — superseded by DETAILS-3c
# ---------------------------------------------------------------------------
#
# This block used to drive the nested "FILTERED VARIANTS" CollapsibleHeader
# sub-section (hidden-by-default chip row, its own chevron, its own
# collapsed flag). DETAILS-3c removed that mechanism entirely: a filtered
# copy now sits behind a dashed "+N filtered" chip that ENDS the "Available
# in" row, and opening it adds a "Filtered" labelled grid row below (closed
# again via the "Filtered" key itself) — persisted per-bucket in
# ``config.details_pane_open_copy_buckets`` rather than reset on every
# load(), which is the opposite of what this block tested.
# Equivalent (and additional) coverage now lives in
# tests/test_details_copies_row.py: the closed "+N filtered" chip, opening
# it, folding it back via the "Filtered" key, and — the deliberately
# inverted case — that a reload does NOT reset an open bucket back to closed.
