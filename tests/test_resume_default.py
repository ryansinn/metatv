"""Behavioral tests for the playback resume-default setting + per-play override actions.

Covered behaviors
-----------------
Settings (SettingsDialog):
1. Load: config.playback_resume_mode="resume" selects the right combo item.
2. Load: config.playback_resume_mode="beginning" selects the right combo item.
3. Load: unknown mode falls back to "resume".
4. Save: combo → config.playback_resume_mode written.

play_media start_seconds resolution:
5. mode="resume", in-progress movie  → start_seconds == watch_progress.
6. mode="beginning", in-progress movie → start_seconds == 0.
7. mode="resume", live channel  → start_seconds == 0.
8. mode="resume", watch_completed=True + watch_progress=0 → start_seconds == 0 (clean finish).
9. mode="resume", watch_progress==0 → start_seconds == 0.
10. start_override=0 forces start_seconds==0 even with mode="resume" and progress>0.
11. start_override=progress forces start_seconds==progress even with mode="beginning".

Context-menu actions:
12. play_from_beginning applies when item is a resumable movie (progress>0, not completed).
13. play_from_beginning does NOT apply for live.
14. play_from_beginning does NOT apply when watch_completed=True.
15. play_from_beginning does NOT apply when watch_progress==0.
16. resume_from applies only when mode=="beginning" AND item is a resumable movie.
17. resume_from does NOT apply when mode=="resume" (the default already resumes).
18. resume_from label shows M:SS formatted position.
19. play_from_beginning handler calls play_channel_from_beginning_by_id.
20. resume_from handler calls play_channel_resume_by_id.
21. _fmt_seconds formats correctly (e.g. 300→"5:00", 75→"1:15").

SURFACE_LAYOUTS:
22. play_from_beginning and resume_from are in "channel" layout.
23. play_from_beginning and resume_from are in "history" layout.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _make_channel_dto(
    media_type: str,
    watch_progress: int = 0,
    watch_completed: bool = False,
) -> object:
    from metatv.core.repositories.dtos import PlayableChannelDTO
    return PlayableChannelDTO(
        id="ch1",
        source_id="src1",
        provider_id="p1",
        name="Test Movie",
        stream_url="http://example.com/stream.mp4",
        media_type=media_type,
        is_favorite=False,
        is_hidden=False,
        is_adult=False,
        logo_url=None,
        detected_prefix=None,
        detected_quality=None,
        detected_region=None,
        detected_title=None,
        detected_year=None,
        raw_data=None,
        metadata_id=None,
        watch_progress=watch_progress,
        watch_completed=watch_completed,
    )


def _make_streaming_host(resume_mode: str = "resume"):
    from metatv.gui.main_window_streaming import _StreamingMixin
    host = _StreamingMixin.__new__(_StreamingMixin)
    host.loading_channels = set()
    host.status_bar = MagicMock()
    host.notification_manager = MagicMock()
    host.notification_manager.show.return_value = "notif-1"
    host.player_manager = MagicMock()
    host.player_manager.is_available.return_value = True
    host.executor = MagicMock()
    host.config = MagicMock()
    host.config.playback_resume_mode = resume_mode
    return host


def _submitted_start_seconds(host) -> int:
    """Extract start_seconds from the most recent executor.submit call on a streaming host."""
    call_args = host.executor.submit.call_args
    _, *pos_args = call_args[0]
    # Arg order after fn: channel_id, name, stream_url, provider_id, notif_id,
    #                     force_new_window, start_seconds, open_ended_buffer
    return pos_args[6]


# ---------------------------------------------------------------------------
# 1–4. Settings dialog load/save
# ---------------------------------------------------------------------------

class _FakeSettingsConfig:
    """Minimal config stub for SettingsDialog playback-tab tests."""

    def __init__(self, playback_resume_mode: str = "resume"):
        self.preferred_player = "mpv"
        self.player_mode = "single-instance"
        self.autoplay_season_episodes = False
        self.playback_resume_mode = playback_resume_mode
        self.watch_complete_threshold = 0.9
        self.watch_partial_threshold = 0.10
        self.close_player_when_finished = False
        self.network_timeout = 10
        self.reconnect_attempts = 3
        self.buffer_profile = "modest"
        self.default_cache_size = "auto"
        self.mpv_extra_args: list = []
        self.prebuffer_before_play = False
        self.prebuffer_wait_secs = 10
        self.mpv_args_override_all = False
        self.split_streams_by_source = False
        self.epg_default_refresh_interval = "3d"
        self.metadata_enabled = True
        self.metadata_auto_fetch = False
        self.metadata_cache_ttl_days = 30
        self.metadata_old_content_ttl_days = 90
        self.metadata_tmdb_api_key = ""
        self.metadata_tmdb_language = "en-US"
        self.metadata_omdb_api_key = ""
        self.sidebar_sections: list = []
        self.sidebar_visible_sections: list = []
        self.remember_search = True
        self.refresh_all_includes_inactive = True
        self.prompt_after_autoplay = True
        self.save_calls = 0

    def save(self) -> None:
        self.save_calls += 1


def _bare_dialog(qapp):
    """Build a bare SettingsDialog skeleton for load/save testing."""
    from PyQt6.QtWidgets import QComboBox, QCheckBox, QSpinBox, QLineEdit, QListWidget
    from metatv.gui.settings_dialog import SettingsDialog
    import metatv.core.epg_utils as _epg

    dlg = SettingsDialog.__new__(SettingsDialog)

    dlg._player_combo = QComboBox()
    dlg._player_combo.addItems(["mpv", "vlc", "custom"])
    dlg._player_mode_combo = QComboBox()
    dlg._player_mode_combo.addItems(["Single instance", "Multiple instances"])
    dlg._autoplay_check = QCheckBox()

    dlg._resume_mode_combo = QComboBox()
    dlg._resume_mode_combo.addItem("Resume where left off", userData="resume")
    dlg._resume_mode_combo.addItem("Start from beginning", userData="beginning")

    dlg._prompt_after_autoplay_check = QCheckBox()
    dlg._watch_threshold_spin = QSpinBox()
    dlg._watch_threshold_spin.setRange(50, 100)
    dlg._watch_partial_spin = QSpinBox()
    dlg._watch_partial_spin.setRange(1, 49)
    dlg._close_player_check = QCheckBox()
    dlg._buffer_combo = QComboBox()
    dlg._buffer_combo.addItem("Reconnect only", userData="reconnect_only")
    dlg._buffer_combo.addItem("Modest (~10s buffer)", userData="modest")
    dlg._buffer_combo.addItem("Large (~30s buffer)", userData="large")
    dlg._user_agent_view = QLineEdit()
    dlg._user_agent_view.setReadOnly(True)
    dlg._timeout_spin = QSpinBox()
    dlg._timeout_spin.setRange(1, 60)
    dlg._reconnect_spin = QSpinBox()
    dlg._reconnect_spin.setRange(0, 10)
    dlg._mpv_args_input = QLineEdit()
    dlg._prebuffer_check = QCheckBox()
    dlg._prebuffer_wait_spin = QSpinBox()
    dlg._prebuffer_wait_spin.setRange(1, 120)
    dlg._override_all_check = QCheckBox()
    dlg._split_check = QCheckBox()
    dlg._remember_search_check = QCheckBox()
    dlg._refresh_all_inactive_check = QCheckBox()
    dlg._epg_interval_combo = QComboBox()
    for value, label in _epg.EPG_INTERVAL_CHOICES:
        dlg._epg_interval_combo.addItem(label, value)
    dlg._meta_enabled_check = QCheckBox()
    dlg._meta_autofetch_check = QCheckBox()
    dlg._cache_ttl_spin = QSpinBox()
    dlg._cache_ttl_spin.setRange(1, 365)
    dlg._cache_old_ttl_spin = QSpinBox()
    dlg._tmdb_key_input = QLineEdit()
    dlg._tmdb_lang_input = QLineEdit()
    dlg._omdb_key_input = QLineEdit()
    dlg._sidebar_list = QListWidget()

    return dlg


def test_settings_load_resume_mode_selects_resume(qapp):
    """config.playback_resume_mode='resume' → combo shows 'Resume where left off'."""
    dlg = _bare_dialog(qapp)
    dlg.config = _FakeSettingsConfig(playback_resume_mode="resume")
    dlg._load_values()
    assert dlg._resume_mode_combo.currentData() == "resume"


def test_settings_load_resume_mode_selects_beginning(qapp):
    """config.playback_resume_mode='beginning' → combo shows 'Start from beginning'."""
    dlg = _bare_dialog(qapp)
    dlg.config = _FakeSettingsConfig(playback_resume_mode="beginning")
    dlg._load_values()
    assert dlg._resume_mode_combo.currentData() == "beginning"


def test_settings_load_unknown_resume_mode_falls_back_to_resume(qapp):
    """An unknown playback_resume_mode value falls back to 'resume' item."""
    dlg = _bare_dialog(qapp)
    dlg.config = _FakeSettingsConfig(playback_resume_mode="unknown_value")
    dlg._load_values()
    assert dlg._resume_mode_combo.currentData() == "resume"


def test_settings_save_resume_mode_written(qapp):
    """Changing the combo to 'beginning' and saving writes playback_resume_mode='beginning'."""
    dlg = _bare_dialog(qapp)
    cfg = _FakeSettingsConfig(playback_resume_mode="resume")
    dlg.config = cfg
    dlg._load_values()

    idx = dlg._resume_mode_combo.findData("beginning")
    dlg._resume_mode_combo.setCurrentIndex(idx)
    dlg._save_values()

    assert cfg.playback_resume_mode == "beginning"
    assert cfg.save_calls == 1


def test_settings_save_resume_mode_to_resume(qapp):
    """Changing the combo to 'resume' and saving writes playback_resume_mode='resume'."""
    dlg = _bare_dialog(qapp)
    cfg = _FakeSettingsConfig(playback_resume_mode="beginning")
    dlg.config = cfg
    dlg._load_values()

    idx = dlg._resume_mode_combo.findData("resume")
    dlg._resume_mode_combo.setCurrentIndex(idx)
    dlg._save_values()

    assert cfg.playback_resume_mode == "resume"


# ---------------------------------------------------------------------------
# 5–11. play_media start_seconds resolution
# ---------------------------------------------------------------------------

def test_play_media_resume_mode_resumes_in_progress_movie():
    """mode='resume' + in-progress movie → start_seconds == watch_progress."""
    host = _make_streaming_host(resume_mode="resume")
    channel = _make_channel_dto("movie", watch_progress=300, watch_completed=False)
    host.play_media(channel)
    assert _submitted_start_seconds(host) == 300


def test_play_media_beginning_mode_starts_at_zero_even_with_progress():
    """mode='beginning' + in-progress movie → start_seconds == 0."""
    host = _make_streaming_host(resume_mode="beginning")
    channel = _make_channel_dto("movie", watch_progress=300, watch_completed=False)
    host.play_media(channel)
    assert _submitted_start_seconds(host) == 0


def test_play_media_resume_mode_live_always_zero():
    """mode='resume' + live channel → start_seconds == 0 (live cannot be resumed)."""
    host = _make_streaming_host(resume_mode="resume")
    channel = _make_channel_dto("live", watch_progress=100, watch_completed=False)
    host.play_media(channel)
    assert _submitted_start_seconds(host) == 0


def test_play_media_resume_mode_completed_and_no_progress_is_zero():
    """mode='resume' + watch_completed=True + watch_progress=0 -> start_seconds == 0.

    A cleanly-finished title has progress=0 by the write-side invariant, so the
    resume condition (watch_progress > 0) is not met. For legacy rows that somehow
    have progress > 0 AND watch_completed=True, the guard now heals them and resumes
    (see test_resume_after_rewatch.py::test_resume_guard_heals_legacy_stuck_row).
    """
    host = _make_streaming_host(resume_mode="resume")
    channel = _make_channel_dto("movie", watch_progress=0, watch_completed=True)
    host.play_media(channel)
    assert _submitted_start_seconds(host) == 0


def test_play_media_resume_mode_no_progress_is_zero():
    """mode='resume' + watch_progress==0 → start_seconds == 0."""
    host = _make_streaming_host(resume_mode="resume")
    channel = _make_channel_dto("movie", watch_progress=0, watch_completed=False)
    host.play_media(channel)
    assert _submitted_start_seconds(host) == 0


def test_play_media_start_override_zero_forces_beginning_despite_resume_mode():
    """start_override=0 forces start_seconds==0 even when mode='resume' and progress>0."""
    host = _make_streaming_host(resume_mode="resume")
    channel = _make_channel_dto("movie", watch_progress=500, watch_completed=False)
    host.play_media(channel, start_override=0)
    assert _submitted_start_seconds(host) == 0


def test_play_media_start_override_nonzero_forces_resume_despite_beginning_mode():
    """start_override=500 forces start_seconds==500 even when mode='beginning'."""
    host = _make_streaming_host(resume_mode="beginning")
    channel = _make_channel_dto("movie", watch_progress=500, watch_completed=False)
    host.play_media(channel, start_override=500)
    assert _submitted_start_seconds(host) == 500


# ---------------------------------------------------------------------------
# 12–18. Context-menu action applies predicates + label
# ---------------------------------------------------------------------------

def _make_ctx(**kwargs):
    from metatv.gui.channel_menu import ChannelMenuContext
    defaults = dict(
        channel_ids=["ch1"],
        surface="channel",
        media_type="movie",
        is_favorite=False,
        in_queue=False,
        rating=0,
        is_hidden=False,
        is_watched=False,
        is_vod_watched=False,
        is_series_monitored=False,
        has_unavailable=False,
        channel_name="Test Movie",
        user_category=None,
        entry_id="",
        channel_found=True,
        watch_progress=300,
        watch_completed=False,
        playback_resume_mode="resume",
    )
    defaults.update(kwargs)
    return ChannelMenuContext(**defaults)


def test_play_from_beginning_applies_for_resumable_movie():
    """play_from_beginning applies when: single, found, not hidden, movie, progress>0, not completed."""
    from metatv.gui.channel_menu import ACTIONS
    ctx = _make_ctx(media_type="movie", watch_progress=300, watch_completed=False)
    assert ACTIONS["play_from_beginning"].applies(ctx) is True


def test_play_from_beginning_not_applies_for_live():
    """play_from_beginning does NOT apply for live channels."""
    from metatv.gui.channel_menu import ACTIONS
    ctx = _make_ctx(media_type="live", watch_progress=0, watch_completed=False)
    assert ACTIONS["play_from_beginning"].applies(ctx) is False


def test_play_from_beginning_not_applies_when_completed():
    """play_from_beginning does NOT apply when watch_completed=True."""
    from metatv.gui.channel_menu import ACTIONS
    ctx = _make_ctx(media_type="movie", watch_progress=0, watch_completed=True)
    assert ACTIONS["play_from_beginning"].applies(ctx) is False


def test_play_from_beginning_not_applies_when_no_progress():
    """play_from_beginning does NOT apply when watch_progress==0."""
    from metatv.gui.channel_menu import ACTIONS
    ctx = _make_ctx(media_type="movie", watch_progress=0, watch_completed=False)
    assert ACTIONS["play_from_beginning"].applies(ctx) is False


def test_resume_from_applies_when_mode_beginning_and_resumable():
    """resume_from applies when mode='beginning' AND item is a resumable movie."""
    from metatv.gui.channel_menu import ACTIONS
    ctx = _make_ctx(media_type="movie", watch_progress=300, watch_completed=False,
                    playback_resume_mode="beginning")
    assert ACTIONS["resume_from"].applies(ctx) is True


def test_resume_from_not_applies_when_mode_resume():
    """resume_from does NOT apply when mode='resume' (default already resumes)."""
    from metatv.gui.channel_menu import ACTIONS
    ctx = _make_ctx(media_type="movie", watch_progress=300, watch_completed=False,
                    playback_resume_mode="resume")
    assert ACTIONS["resume_from"].applies(ctx) is False


def test_resume_from_not_applies_when_no_progress():
    """resume_from does NOT apply when watch_progress==0 even with mode='beginning'."""
    from metatv.gui.channel_menu import ACTIONS
    ctx = _make_ctx(media_type="movie", watch_progress=0, watch_completed=False,
                    playback_resume_mode="beginning")
    assert ACTIONS["resume_from"].applies(ctx) is False


def test_resume_from_label_shows_formatted_time():
    """resume_from label includes the M:SS formatted watch_progress."""
    from metatv.gui.channel_menu import ACTIONS
    ctx = _make_ctx(watch_progress=315, playback_resume_mode="beginning")
    label = ACTIONS["resume_from"].label(ctx)
    assert "5:15" in label, f"Expected '5:15' in label, got: {label!r}"


# ---------------------------------------------------------------------------
# 19–20. Context-menu handler wiring
# ---------------------------------------------------------------------------

class _FakeConfig:
    epg_watchlist_channels: list = []
    epg_watchlist_patterns: list = []
    playback_resume_mode: str = "resume"

    def save(self):
        pass


def _make_main_window_host():
    from metatv.gui.main_window import MainWindow
    host = MainWindow.__new__(MainWindow)
    host.config = _FakeConfig()
    host.sidebar_sections = {}
    host.stream_retry_manager = MagicMock()
    host.stream_retry_manager.clear_all = MagicMock()

    host.play_channel_by_id = MagicMock()
    host.play_channel_new_window_by_id = MagicMock()
    host.play_channel_open_ended_buffer_by_id = MagicMock()
    host.play_channel_from_beginning_by_id = MagicMock()
    host.play_channel_resume_by_id = MagicMock()
    host.play_from_history_id = MagicMock()
    host.play_favorite_id = MagicMock()
    host.play_queue_item_id = MagicMock()
    host._toggle_favorite_by_id = MagicMock()
    host._add_to_queue = MagicMock()
    host._remove_from_queue = MagicMock()
    host._toggle_rating = MagicMock()
    host._watch_channel_from_list = MagicMock()
    host._unwatch_channel_from_list = MagicMock()
    host._unmonitor_series = MagicMock()
    host._monitor_series = MagicMock()
    host._mark_channel_watched = MagicMock()
    host._mark_channel_unwatched = MagicMock()
    host._prompt_track_from_list = MagicMock()
    host._unhide_channel = MagicMock()
    host._hide_channel_from_recommendations = MagicMock()
    host._hide_channel_from_history = MagicMock()
    host._hide_channel_from_alerts = MagicMock()
    host.remove_from_history = MagicMock()
    host._not_interested = MagicMock()
    host._open_category_picker = MagicMock()
    host._quick_assign_category = MagicMock()
    host._trigger_play_all_channels = MagicMock()
    return host


def test_play_from_beginning_handler_calls_correct_method():
    """_build_handlers: 'play_from_beginning' calls play_channel_from_beginning_by_id(cid)."""
    from metatv.gui.main_window import MainWindow
    from metatv.gui.channel_menu import ChannelMenuContext

    host = _make_main_window_host()
    ctx = ChannelMenuContext(
        channel_ids=["ch1"],
        surface="channel",
        media_type="movie",
        channel_found=True,
        watch_progress=300,
        watch_completed=False,
        playback_resume_mode="resume",
    )
    handlers = MainWindow._build_handlers(host, ctx)
    assert "play_from_beginning" in handlers
    handlers["play_from_beginning"]()
    host.play_channel_from_beginning_by_id.assert_called_once_with("ch1")


def test_resume_from_handler_calls_correct_method():
    """_build_handlers: 'resume_from' calls play_channel_resume_by_id(cid)."""
    from metatv.gui.main_window import MainWindow
    from metatv.gui.channel_menu import ChannelMenuContext

    host = _make_main_window_host()
    ctx = ChannelMenuContext(
        channel_ids=["ch1"],
        surface="channel",
        media_type="movie",
        channel_found=True,
        watch_progress=300,
        watch_completed=False,
        playback_resume_mode="beginning",
    )
    handlers = MainWindow._build_handlers(host, ctx)
    assert "resume_from" in handlers
    handlers["resume_from"]()
    host.play_channel_resume_by_id.assert_called_once_with("ch1")


# ---------------------------------------------------------------------------
# 21. _fmt_seconds correctness
# ---------------------------------------------------------------------------

def test_fmt_seconds_whole_minutes():
    """300 seconds → '5:00'."""
    from metatv.gui.channel_menu import _fmt_seconds
    assert _fmt_seconds(300) == "5:00"


def test_fmt_seconds_with_remainder():
    """75 seconds → '1:15'."""
    from metatv.gui.channel_menu import _fmt_seconds
    assert _fmt_seconds(75) == "1:15"


def test_fmt_seconds_zero():
    """0 seconds → '0:00'."""
    from metatv.gui.channel_menu import _fmt_seconds
    assert _fmt_seconds(0) == "0:00"


def test_fmt_seconds_sub_minute():
    """45 seconds → '0:45'."""
    from metatv.gui.channel_menu import _fmt_seconds
    assert _fmt_seconds(45) == "0:45"


# ---------------------------------------------------------------------------
# 22–23. SURFACE_LAYOUTS registration
# ---------------------------------------------------------------------------

def test_play_from_beginning_in_channel_layout():
    """play_from_beginning must appear in the 'channel' surface layout."""
    from metatv.gui.channel_menu import SURFACE_LAYOUTS
    assert "play_from_beginning" in SURFACE_LAYOUTS["channel"]


def test_resume_from_in_channel_layout():
    """resume_from must appear in the 'channel' surface layout."""
    from metatv.gui.channel_menu import SURFACE_LAYOUTS
    assert "resume_from" in SURFACE_LAYOUTS["channel"]


def test_play_from_beginning_in_history_layout():
    """play_from_beginning must appear in the 'history' surface layout."""
    from metatv.gui.channel_menu import SURFACE_LAYOUTS
    assert "play_from_beginning" in SURFACE_LAYOUTS["history"]


def test_resume_from_in_favorites_layout():
    """resume_from must appear in the 'favorites' surface layout."""
    from metatv.gui.channel_menu import SURFACE_LAYOUTS
    assert "resume_from" in SURFACE_LAYOUTS["favorites"]


# ---------------------------------------------------------------------------
# 24. Menu render: play_from_beginning shows in the built menu when applicable
# ---------------------------------------------------------------------------

def test_play_from_beginning_visible_in_menu_for_resumable_movie(qapp):
    """A resumable movie channel menu includes the 'Play from Beginning' item."""
    from metatv.gui.channel_menu import build_channel_menu, ChannelMenuContext

    ctx = ChannelMenuContext(
        channel_ids=["ch1"],
        surface="channel",
        media_type="movie",
        channel_found=True,
        watch_progress=300,
        watch_completed=False,
        playback_resume_mode="resume",
        is_hidden=False,
    )
    handlers = {
        "play": lambda: None,
        "play_new_window": lambda: None,
        "play_open_ended_buffer": lambda: None,
        "play_from_beginning": lambda: None,
        "favorite": lambda: None,
        "queue": lambda: None,
        "mark_watched": lambda: None,
        "watch": lambda: None,
        "track": lambda: None,
        "hide": lambda: None,
        "category": lambda: None,
    }
    menu = build_channel_menu(ctx, handlers, parent=None)
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert any("Beginning" in t for t in texts), \
        f"'Play from Beginning' should appear for resumable movie; got: {texts}"


def test_resume_from_visible_in_menu_when_mode_is_beginning(qapp):
    """When mode='beginning' and progress>0, 'Resume from M:SS' appears in the menu."""
    from metatv.gui.channel_menu import build_channel_menu, ChannelMenuContext

    ctx = ChannelMenuContext(
        channel_ids=["ch1"],
        surface="channel",
        media_type="movie",
        channel_found=True,
        watch_progress=180,
        watch_completed=False,
        playback_resume_mode="beginning",
        is_hidden=False,
    )
    handlers = {
        "play": lambda: None,
        "play_new_window": lambda: None,
        "play_from_beginning": lambda: None,
        "resume_from": lambda: None,
        "favorite": lambda: None,
        "queue": lambda: None,
        "mark_watched": lambda: None,
        "watch": lambda: None,
        "track": lambda: None,
        "hide": lambda: None,
        "category": lambda: None,
    }
    menu = build_channel_menu(ctx, handlers, parent=None)
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert any("Resume from" in t for t in texts), \
        f"'Resume from M:SS' should appear when mode='beginning'; got: {texts}"
    assert any("3:00" in t for t in texts), \
        f"Label should include '3:00' (180s); got: {texts}"


# ---------------------------------------------------------------------------
# 25–26. Double-click = resume-by-default
# ---------------------------------------------------------------------------

def test_double_click_routes_to_resume_aware_play_by_id(qapp):
    """Double-clicking a channel row routes to play_channel_by_id (the resume-aware
    default path) — NOT play_from_beginning.  play_channel_by_id honors the default
    playback_resume_mode, so a partially-watched title resumes (see below)."""
    from PyQt6.QtCore import Qt
    from metatv.gui.main_window_channels import _ChannelListMixin

    host = _ChannelListMixin.__new__(_ChannelListMixin)
    host.play_channel_by_id = MagicMock()

    index = MagicMock()
    index.data.return_value = "ch-double"

    _ChannelListMixin._on_channel_double_clicked(host, index)

    index.data.assert_called_once_with(Qt.ItemDataRole.UserRole)
    host.play_channel_by_id.assert_called_once_with("ch-double")


def test_double_click_resumes_partially_watched_movie(qapp):
    """End-to-end: double-click → play_channel_by_id → play_media resumes a
    partially-watched movie at the saved position under the default resume mode."""
    import contextlib
    from unittest.mock import patch
    from metatv.gui.main_window_favorites import _FavoritesMixin

    host = _make_streaming_host(resume_mode="resume")
    # Bind the real play_channel_by_id (resume-aware default play path).
    host.play_channel_by_id = _FavoritesMixin.play_channel_by_id.__get__(host)

    @contextlib.contextmanager
    def _scope(*a, **k):
        yield MagicMock()

    host.db = MagicMock()
    host.db.session_scope.side_effect = _scope

    dto = _make_channel_dto("movie", watch_progress=300, watch_completed=False)
    with patch("metatv.gui.main_window_favorites.RepositoryFactory") as RF:
        RF.return_value.channels.get_playable_dto.return_value = dto
        host.play_channel_by_id("ch1")

    assert _submitted_start_seconds(host) == 300, (
        "double-click default play must resume a partially-watched movie at its saved position"
    )
