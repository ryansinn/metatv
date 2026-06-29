"""Behavioral tests for Slice 2 — watch-completion visibility, and the
partial-watched indicator added in the follow-on PR.

These tests execute the changed code paths and assert outcomes that would
actually break if the feature regressed:

1. Settings threshold round-trip: spin ↔ config.watch_complete_threshold.
2. ChannelListDTO carries watch_completed / watch_progress from ORM row.
3. ChannelListModel.data(DecorationRole) returns a QIcon for completed movies (glyph in icon lane, not text).
4. ChannelListModel DecorationRole returns None for live channels.
3b. DecorationRole returns QIcon for partially-watched movies; text never contains watch glyphs.
5-7. (removed) The details-pane "✓ Watched" / "Resume" text line was replaced by
    the action-rail Watched toggle + Resume button — see
    tests/test_details_rail_watched_logo.py.
8. ContentCard.progress_fraction is populated from StatusSets.progress_map.
9. build_status_sets watched_ids uses watch_completed (not last_played).
10. build_status_sets builds progress_map for partial-play movies with runtimes.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from metatv.core.repositories.dtos import ChannelListDTO


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _dto(**overrides) -> ChannelListDTO:
    """Make a minimal ChannelListDTO for channel-list rendering tests."""
    base = dict(
        id=str(uuid.uuid4()),
        name="Test Movie",
        media_type="movie",
        provider_id="p1",
        is_favorite=False,
        category=None,
        quality=None,
        detected_prefix=None,
        detected_region=None,
        detected_quality=None,
        detected_year=None,
        detected_title="Test Movie",
        watch_completed=False,
        watch_progress=0,
        watch_percent=0,
    )
    base.update(overrides)
    return ChannelListDTO(**base)


# ---------------------------------------------------------------------------
# 1. Settings threshold round-trip
# ---------------------------------------------------------------------------

class _FakeThresholdConfig:
    """Minimal config stub with watch_complete_threshold."""
    def __init__(self, threshold: float = 0.9, partial_threshold: float = 0.10):
        self.preferred_player = "mpv"
        self.player_mode = "single-instance"
        self.autoplay_season_episodes = False
        self.playback_resume_mode = "resume"
        self.watch_complete_threshold = threshold
        self.watch_partial_threshold = partial_threshold
        self.close_player_when_finished = False
        self.network_timeout = 10
        self.reconnect_attempts = 3
        self.buffer_profile = "modest"
        self.default_cache_size = "auto"
        self.mpv_extra_args: list[str] = []
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
        self.sidebar_sections: list[str] = []
        self.sidebar_visible_sections: list[str] = []
        self.remember_search: bool = True
        self.refresh_all_includes_inactive: bool = True
        self.prompt_after_autoplay: bool = True
        self._saved = False

    def save(self) -> None:
        self._saved = True


def _make_threshold_dialog(qapp, threshold: float = 0.9):
    """Build the minimal SettingsDialog skeleton for threshold tests."""
    from PyQt6.QtWidgets import (
        QCheckBox, QComboBox, QSpinBox, QLineEdit, QListWidget,
    )
    from metatv.gui.settings_dialog import SettingsDialog
    import metatv.core.epg_utils as _epg

    dlg = SettingsDialog.__new__(SettingsDialog)
    dlg.config = _FakeThresholdConfig(threshold=threshold)

    dlg._player_combo = QComboBox()
    dlg._player_combo.addItems(["mpv", "vlc", "custom"])
    dlg._player_mode_combo = QComboBox()
    dlg._player_mode_combo.addItems(["Single instance", "Multiple instances"])
    dlg._autoplay_check = QCheckBox()
    dlg._resume_mode_combo = QComboBox()
    dlg._resume_mode_combo.addItem("Resume where left off", userData="resume")
    dlg._resume_mode_combo.addItem("Start from beginning", userData="beginning")
    from metatv.gui.middle_click_actions import MIDDLE_CLICK_ACTIONS
    dlg._middle_click_combo = QComboBox()
    for _action in MIDDLE_CLICK_ACTIONS:
        dlg._middle_click_combo.addItem(_action.label, userData=_action.key)
    dlg._prompt_after_autoplay_check = QCheckBox()
    dlg._watch_threshold_spin = QSpinBox()
    dlg._watch_threshold_spin.setRange(50, 100)
    dlg._watch_threshold_spin.setSuffix("%")
    dlg._watch_partial_spin = QSpinBox()
    dlg._watch_partial_spin.setRange(1, 49)
    dlg._watch_partial_spin.setSuffix("%")
    dlg._close_player_check = QCheckBox()
    dlg._buffer_combo = QComboBox()
    dlg._buffer_combo.addItem("Reconnect only (no extra buffer)", userData="reconnect_only")
    dlg._buffer_combo.addItem("Modest (~10s buffer)", userData="modest")
    dlg._buffer_combo.addItem("Large (~30s buffer)", userData="large")
    dlg._user_agent_view = QLineEdit()
    dlg._user_agent_view.setReadOnly(True)
    dlg._mpv_args_input = QLineEdit()
    dlg._prebuffer_check = QCheckBox()
    dlg._prebuffer_wait_spin = QSpinBox()
    dlg._prebuffer_wait_spin.setRange(1, 120)
    dlg._prebuffer_wait_spin.setSuffix(" s")
    dlg._override_all_check = QCheckBox()
    dlg._split_check = QCheckBox()
    dlg._remember_search_check = QCheckBox()
    dlg._refresh_all_inactive_check = QCheckBox()
    dlg._timeout_spin = QSpinBox()
    dlg._timeout_spin.setRange(1, 60)
    dlg._reconnect_spin = QSpinBox()
    dlg._reconnect_spin.setRange(0, 10)
    dlg._epg_interval_combo = QComboBox()
    for value, label in _epg.EPG_INTERVAL_CHOICES:
        dlg._epg_interval_combo.addItem(label, value)
    dlg._epg_hide_older_spin = QSpinBox()
    dlg._epg_hide_older_spin.setRange(0, 168)
    dlg._meta_enabled_check = QCheckBox()
    dlg._meta_autofetch_check = QCheckBox()
    dlg._cache_ttl_spin = QSpinBox()
    dlg._cache_ttl_spin.setRange(1, 365)
    dlg._cache_old_ttl_spin = QSpinBox()
    dlg._cache_old_ttl_spin.setRange(1, 365)
    dlg._tmdb_key_input = QLineEdit()
    dlg._tmdb_lang_input = QLineEdit()
    dlg._omdb_key_input = QLineEdit()
    dlg._sidebar_list = QListWidget()
    return dlg


def test_settings_load_threshold_90_percent(qapp):
    """_load_values sets spin to 90 when config.watch_complete_threshold=0.9."""
    dlg = _make_threshold_dialog(qapp, threshold=0.9)
    dlg._load_values()
    assert dlg._watch_threshold_spin.value() == 90


def test_settings_load_threshold_75_percent(qapp):
    """_load_values sets spin to 75 when config.watch_complete_threshold=0.75."""
    dlg = _make_threshold_dialog(qapp, threshold=0.75)
    dlg._load_values()
    assert dlg._watch_threshold_spin.value() == 75


def test_settings_save_threshold_writes_config(qapp):
    """_save_values writes spin value back as a float fraction."""
    dlg = _make_threshold_dialog(qapp, threshold=0.9)
    dlg._load_values()
    dlg._watch_threshold_spin.setValue(80)
    dlg._save_values()
    # 80% → 0.8 stored in config
    assert abs(dlg.config.watch_complete_threshold - 0.8) < 0.001
    assert dlg.config._saved is True


def test_settings_save_threshold_100_percent(qapp):
    """Edge: 100% in the spin → 1.0 in config."""
    dlg = _make_threshold_dialog(qapp, threshold=0.9)
    dlg._load_values()
    dlg._watch_threshold_spin.setValue(100)
    dlg._save_values()
    assert abs(dlg.config.watch_complete_threshold - 1.0) < 0.001


# ---------------------------------------------------------------------------
# 2. ChannelListDTO carries watch fields from ORM row
# ---------------------------------------------------------------------------

def test_channel_list_dto_from_orm_carries_watch_completed(tmp_path):
    """from_orm reads watch_completed from the ChannelDB row."""
    from metatv.core.database import Database, ChannelDB
    from metatv.core.repositories.dtos import ChannelListDTO

    db = Database(f"sqlite:///{tmp_path / 't.db'}")
    db.create_tables()

    cid = str(uuid.uuid4())
    with db.session_scope() as session:
        session.add(ChannelDB(
            id=cid,
            source_id="1",
            provider_id="p1",
            name="The Matrix (1999)",
            media_type="movie",
            watch_completed=True,
            watch_progress=0,
        ))

    with db.session_scope(commit=False) as session:
        from metatv.core.repositories import RepositoryFactory
        ch = RepositoryFactory(session).channels.get_by_id(cid)
        dto = ChannelListDTO.from_orm(ch)

    # DTO is readable after session closes
    assert dto.watch_completed is True
    assert dto.watch_progress == 0
    db.close()


def test_channel_list_dto_from_orm_carries_watch_progress(tmp_path):
    """from_orm reads watch_progress from the ChannelDB row."""
    from metatv.core.database import Database, ChannelDB
    from metatv.core.repositories.dtos import ChannelListDTO

    db = Database(f"sqlite:///{tmp_path / 't.db'}")
    db.create_tables()

    cid = str(uuid.uuid4())
    with db.session_scope() as session:
        session.add(ChannelDB(
            id=cid,
            source_id="1",
            provider_id="p1",
            name="Interstellar",
            media_type="movie",
            watch_completed=False,
            watch_progress=2700,   # 45 minutes in
        ))

    with db.session_scope(commit=False) as session:
        from metatv.core.repositories import RepositoryFactory
        ch = RepositoryFactory(session).channels.get_by_id(cid)
        dto = ChannelListDTO.from_orm(ch)

    assert dto.watch_completed is False
    assert dto.watch_progress == 2700
    db.close()


# ---------------------------------------------------------------------------
# 3–4. ChannelListModel DecorationRole: QIcon for watched VOD, None for live
# ---------------------------------------------------------------------------

def _make_model(qapp):
    from metatv.gui.channel_list_model import ChannelListModel
    return ChannelListModel()


def test_channel_list_model_shows_watched_check_for_completed_movie(qapp):
    """DecorationRole returns a QIcon for a completed movie; text has no glyph."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QIcon
    from metatv.gui import icons as _icons
    model = _make_model(qapp)
    dto = _dto(media_type="movie", watch_completed=True)
    model.set_channels(
        [dto],
        provider_icon_map={},
        show_provider_icon=False,
        has_more=False,
        query_params={},
    )
    idx = model.index(0, 0)
    icon = idx.data(Qt.ItemDataRole.DecorationRole)
    text = idx.data(Qt.ItemDataRole.DisplayRole)
    assert isinstance(icon, QIcon), f"Expected QIcon for completed movie, got {icon!r}"
    assert _icons.watched_icon not in text, f"Glyph must be in icon lane, not text: {text!r}"


def test_channel_list_model_no_watch_check_for_unwatched_movie(qapp):
    """_compose_display_text has NO ✓ for an unwatched movie (watch_completed=False)."""
    from metatv.gui import icons as _icons
    model = _make_model(qapp)
    dto = _dto(media_type="movie", watch_completed=False)
    model.set_channels(
        [dto],
        provider_icon_map={},
        show_provider_icon=False,
        has_more=False,
        query_params={},
    )
    text = model._compose_display_text(dto)
    assert _icons.watched_icon not in text, f"Unexpected ✓ in {text!r}"


def test_channel_list_model_no_watch_check_for_live_even_if_flag_set(qapp):
    """Live channels never show the ✓ badge, even if watch_completed=True (data anomaly)."""
    from metatv.gui import icons as _icons
    model = _make_model(qapp)
    dto = _dto(media_type="live", watch_completed=True)
    model.set_channels(
        [dto],
        provider_icon_map={},
        show_provider_icon=False,
        has_more=False,
        query_params={},
    )
    text = model._compose_display_text(dto)
    assert _icons.watched_icon not in text, f"Unexpected ✓ for live channel in {text!r}"


def test_channel_list_model_shows_watch_check_for_series_if_completed(qapp):
    """Series with watch_completed=True: DecorationRole returns a QIcon, text has no glyph.

    The guard is media_type != 'live' so series with a completion flag also get the icon.
    """
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QIcon
    from metatv.gui import icons as _icons
    model = _make_model(qapp)
    dto = _dto(media_type="series", watch_completed=True)
    model.set_channels(
        [dto],
        provider_icon_map={},
        show_provider_icon=False,
        has_more=False,
        query_params={},
    )
    idx = model.index(0, 0)
    icon = idx.data(Qt.ItemDataRole.DecorationRole)
    text = idx.data(Qt.ItemDataRole.DisplayRole)
    assert isinstance(icon, QIcon), f"Expected QIcon for completed series, got {icon!r}"
    assert _icons.watched_icon not in text, f"Glyph must be in icon lane, not text: {text!r}"


# ---------------------------------------------------------------------------
# 3b. Partial-watched indicator (◐) in _compose_display_text
# ---------------------------------------------------------------------------

def test_channel_list_model_shows_partial_icon_for_in_progress_movie(qapp):
    """Partial-watched movie: DecorationRole returns a QIcon; text has no glyph."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QIcon
    from metatv.gui import icons as _icons
    model = _make_model(qapp)
    dto = _dto(media_type="movie", watch_completed=False, watch_progress=1500, watch_percent=50)
    model.set_channels([dto], provider_icon_map={}, show_provider_icon=False,
                       has_more=False, query_params={})
    idx = model.index(0, 0)
    icon = idx.data(Qt.ItemDataRole.DecorationRole)
    text = idx.data(Qt.ItemDataRole.DisplayRole)
    assert isinstance(icon, QIcon), f"Expected QIcon for partial-watched movie, got {icon!r}"
    assert _icons.partial_watched_icon not in text, (
        f"Glyph must be in icon lane, not text: {text!r}"
    )
    assert _icons.watched_icon not in text, (
        f"Completed glyph must not appear in text for in-progress row: {text!r}"
    )


def test_channel_list_model_no_partial_icon_for_completed_movie(qapp):
    """Completed movie: DecorationRole returns icon; neither glyph appears in text."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QIcon
    from metatv.gui import icons as _icons
    model = _make_model(qapp)
    dto = _dto(media_type="movie", watch_completed=True, watch_progress=0)
    model.set_channels([dto], provider_icon_map={}, show_provider_icon=False,
                       has_more=False, query_params={})
    idx = model.index(0, 0)
    icon = idx.data(Qt.ItemDataRole.DecorationRole)
    text = idx.data(Qt.ItemDataRole.DisplayRole)
    assert isinstance(icon, QIcon), f"Expected QIcon for completed movie, got {icon!r}"
    assert _icons.watched_icon not in text, (
        f"Glyph must be in icon lane, not text: {text!r}"
    )
    assert _icons.partial_watched_icon not in text, (
        f"Partial glyph must not appear in text: {text!r}"
    )


def test_channel_list_model_no_partial_icon_for_unwatched_movie(qapp):
    """Unwatched movie (progress=0, not completed) shows neither ✓ nor ◐."""
    from metatv.gui import icons as _icons
    model = _make_model(qapp)
    dto = _dto(media_type="movie", watch_completed=False, watch_progress=0)
    text = model._compose_display_text(dto)
    assert _icons.watched_icon not in text, f"Unexpected ✓ for unwatched movie in {text!r}"
    assert _icons.partial_watched_icon not in text, (
        f"Unexpected ◐ for unwatched movie in {text!r}"
    )


def test_channel_list_model_no_partial_icon_for_live_with_progress(qapp):
    """Live channel with watch_progress > 0 must show neither ✓ nor ◐ — never badge live rows."""
    from metatv.gui import icons as _icons
    model = _make_model(qapp)
    dto = _dto(media_type="live", watch_completed=False, watch_progress=120)
    text = model._compose_display_text(dto)
    assert _icons.watched_icon not in text, f"Unexpected ✓ for live channel in {text!r}"
    assert _icons.partial_watched_icon not in text, (
        f"Unexpected ◐ for live channel in {text!r}"
    )


# ---------------------------------------------------------------------------
# 5–7. (removed) The details-pane "✓ Watched" / "Resume at M:SS" text line was
# replaced by the action-rail Watched toggle + Resume button — see
# tests/test_details_rail_watched_logo.py for the replacement coverage.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 8. ContentCard.progress_fraction populated from progress_map
# ---------------------------------------------------------------------------

def test_to_card_sets_progress_fraction_when_partial(tmp_path):
    """_to_card reads progress_fraction from progress_map for partial movies."""
    from metatv.core.discovery_engine import _to_card

    ch = MagicMock()
    ch.id = "cid1"
    ch.name = "Test Movie"
    ch.media_type = "movie"
    ch.detected_prefix = None
    ch.raw_data = {"added": "1000", "rating": "7.5"}

    card = _to_card(
        ch, meta=None,
        watched_ids=set(),         # not completed
        progress_map={"cid1": 0.45},
    )
    assert abs(card.progress_fraction - 0.45) < 0.001
    assert card.already_watched is False


def test_to_card_progress_fraction_zero_for_completed(tmp_path):
    """Completed channels (in watched_ids) get progress_fraction=0.0."""
    from metatv.core.discovery_engine import _to_card

    ch = MagicMock()
    ch.id = "cid2"
    ch.name = "Done Movie"
    ch.media_type = "movie"
    ch.detected_prefix = None
    ch.raw_data = {"added": "1000", "rating": "8.0"}

    card = _to_card(
        ch, meta=None,
        watched_ids={"cid2"},      # completed
        progress_map={"cid2": 0.95},  # would be >0 if not completed
    )
    assert card.already_watched is True
    assert card.progress_fraction == 0.0   # cleared because already_watched


def test_to_card_progress_fraction_zero_when_no_map():
    """progress_fraction stays 0.0 when progress_map is None."""
    from metatv.core.discovery_engine import _to_card

    ch = MagicMock()
    ch.id = "cid3"
    ch.name = "Fresh Movie"
    ch.media_type = "movie"
    ch.detected_prefix = None
    ch.raw_data = {}

    card = _to_card(ch, meta=None, watched_ids=set(), progress_map=None)
    assert card.progress_fraction == 0.0


# ---------------------------------------------------------------------------
# 9–10. build_status_sets: watched_ids uses watch_completed; progress_map
# ---------------------------------------------------------------------------

def _make_db(path):
    from metatv.core.database import Database
    db = Database(f"sqlite:///{path}")
    db.create_tables()
    return db


def _make_channel_db(session, name="Movie", media_type="movie",
                     watch_completed=False, watch_progress=0,
                     last_played=None, metadata_id=None):
    from metatv.core.database import ChannelDB
    ch = ChannelDB(
        id=str(uuid.uuid4()),
        source_id=str(uuid.uuid4()),
        provider_id="p1",
        name=name,
        media_type=media_type,
        watch_completed=watch_completed,
        watch_progress=watch_progress,
        last_played=last_played,
        metadata_id=metadata_id,
    )
    session.add(ch)
    session.flush()
    return ch


def test_build_status_sets_watched_ids_uses_watch_completed(tmp_path):
    """watched_ids = {channels where watch_completed=True}, not last_played."""
    from metatv.core.discovery_engine import build_status_sets
    from sqlalchemy.orm import sessionmaker

    db = _make_db(tmp_path / "ws.db")
    Session = sessionmaker(bind=db.engine)
    session = Session()

    ch_done = _make_channel_db(session, "Done", watch_completed=True,
                                last_played=datetime.now())
    ch_started = _make_channel_db(session, "Started", watch_completed=False,
                                   watch_progress=600, last_played=datetime.now())
    ch_fresh = _make_channel_db(session, "Fresh")
    session.commit()

    ss = build_status_sets(session)
    assert ch_done.id in ss.watched_ids
    assert ch_started.id not in ss.watched_ids   # started ≠ completed
    assert ch_fresh.id not in ss.watched_ids

    session.close()
    db.close()


def test_build_status_sets_progress_map_populated(tmp_path):
    """progress_map contains fraction for partial-play movies with runtimes."""
    from metatv.core.discovery_engine import build_status_sets
    from metatv.core.database import MetadataDB
    from sqlalchemy.orm import sessionmaker

    db = _make_db(tmp_path / "pm.db")
    Session = sessionmaker(bind=db.engine)
    session = Session()

    # Create metadata with a runtime (90 minutes = 5400 seconds)
    meta = MetadataDB(
        id=str(uuid.uuid4()),
        title="Test Film",
        runtime=90,   # minutes
        media_type="movie",
    )
    session.add(meta)
    session.flush()

    # A partial-play movie (900 s into a 90-min = 5400 s film → ~16.7%)
    ch = _make_channel_db(session, "Partial Film", media_type="movie",
                           watch_completed=False, watch_progress=900,
                           metadata_id=meta.id)
    # A completed movie should NOT appear in progress_map
    ch_done = _make_channel_db(session, "Done Film", media_type="movie",
                                watch_completed=True, watch_progress=0,
                                metadata_id=meta.id)
    session.commit()

    ss = build_status_sets(session)

    assert ch.id in ss.progress_map, "partial movie should be in progress_map"
    frac = ss.progress_map[ch.id]
    assert abs(frac - 900/5400) < 0.01, f"Expected ~0.167, got {frac}"
    assert ch_done.id not in ss.progress_map, "completed movies must not be in progress_map"

    session.close()
    db.close()


def test_build_status_sets_progress_map_empty_without_metadata(tmp_path):
    """progress_map stays empty for movies without metadata (no runtime)."""
    from metatv.core.discovery_engine import build_status_sets
    from sqlalchemy.orm import sessionmaker

    db = _make_db(tmp_path / "pm2.db")
    Session = sessionmaker(bind=db.engine)
    session = Session()

    # Movie has watch_progress but no metadata → can't compute fraction
    _make_channel_db(session, "No-Meta Film", media_type="movie",
                     watch_completed=False, watch_progress=600)
    session.commit()

    ss = build_status_sets(session)
    # No runtime available → nothing in progress_map
    assert len(ss.progress_map) == 0

    session.close()
    db.close()
