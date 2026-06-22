"""Behavioral tests for graduated watch-progress indicators (◔ ◐ ◕).

Covered behaviours:
1. DB migration list includes channels.watch_percent and episodes.watch_percent.
2. ChannelRepository.record_watch_progress stamps watch_percent on the row.
3. EpisodeRepository.record_watch_progress stamps watch_percent on the row.
4. ChannelListDTO.from_orm carries watch_percent from the ORM row.
5. EpisodeDTO (via get_episodes_dto_by_season) carries watch_percent.
6. watch_progress_glyph() → correct glyph for 5% (below threshold), 20%, 50%, 80%, 100%/completed.
7. _compose_display_text uses the graduated glyph (not the flat ◐) for VOD rows.
8. Settings dialog round-trips watch_partial_threshold.
9. Config.watch_partial_threshold defaults to 0.10 and persists through save/load.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path):
    from metatv.core.database import Database
    d = Database(f"sqlite:///{tmp_path / 'grad.db'}")
    d.create_tables()
    yield d
    d.close()


def _seed_movie(db, ch_id: str = "m1"):
    from metatv.core.database import ChannelDB
    with db.session_scope() as session:
        session.add(ChannelDB(
            id=ch_id, source_id=ch_id, provider_id="p",
            name="Movie", media_type="movie",
        ))


def _seed_episode(db, ep_id: str = "e1"):
    from metatv.core.database import EpisodeDB
    with db.session_scope() as session:
        session.add(EpisodeDB(
            id=ep_id, series_id="ser1", season_id="s1", provider_id="p1",
            episode_id="ep_orig_1", season_num=1, episode_num=1, title="E1",
        ))


# ---------------------------------------------------------------------------
# 1. Migration list includes watch_percent for both tables
# ---------------------------------------------------------------------------

def test_migration_list_has_channels_watch_percent():
    """channels.watch_percent must appear in the _migrate column list."""
    import inspect
    from metatv.core.database import Database
    src = inspect.getsource(Database._migrate)
    assert "watch_percent" in src, "watch_percent missing from _migrate"
    # More specifically — check both table entries
    assert '"channels"' in src or "'channels'" in src
    assert '"episodes"' in src or "'episodes'" in src


def test_migration_both_tables_have_watch_percent_entries():
    """Both channels and episodes entries for watch_percent appear in the migration."""
    import inspect
    from metatv.core.database import Database
    src = inspect.getsource(Database._migrate)
    lines = src.split("\n")
    ch_pct = any("channels" in ln and "watch_percent" in ln for ln in lines)
    ep_pct = any("episodes" in ln and "watch_percent" in ln for ln in lines)
    assert ch_pct, "channels.watch_percent missing from _migrate"
    assert ep_pct, "episodes.watch_percent missing from _migrate"


# ---------------------------------------------------------------------------
# 2. ChannelRepository.record_watch_progress stamps watch_percent
# ---------------------------------------------------------------------------

def test_channel_record_progress_stamps_percent(db):
    """20% watched → watch_percent=20 on the channel row."""
    _seed_movie(db)
    with db.session_scope() as session:
        from metatv.core.repositories import RepositoryFactory
        repo = RepositoryFactory(session).channels
        repo.record_watch_progress("m1", position_s=600, duration_s=3000)  # 20%
        ch = repo.get_by_id("m1")
        assert ch.watch_percent == 20, f"Expected 20, got {ch.watch_percent}"
        assert not ch.watch_completed


def test_channel_record_progress_stamps_100_when_completed(db):
    """Completing a movie sets watch_percent=100 and watch_completed=True."""
    _seed_movie(db)
    with db.session_scope() as session:
        from metatv.core.repositories import RepositoryFactory
        repo = RepositoryFactory(session).channels
        repo.record_watch_progress("m1", position_s=2900, duration_s=3000)  # 96%
        ch = repo.get_by_id("m1")
        assert ch.watch_percent == 100
        assert bool(ch.watch_completed) is True


def test_channel_record_progress_zero_when_duration_unknown(db):
    """Zero duration → watch_percent=0, never completed."""
    _seed_movie(db)
    with db.session_scope() as session:
        from metatv.core.repositories import RepositoryFactory
        repo = RepositoryFactory(session).channels
        repo.record_watch_progress("m1", position_s=500, duration_s=0)
        ch = repo.get_by_id("m1")
        assert ch.watch_percent == 0
        assert not ch.watch_completed


# ---------------------------------------------------------------------------
# 3. EpisodeRepository.record_watch_progress stamps watch_percent
# ---------------------------------------------------------------------------

def test_episode_record_progress_stamps_percent(db):
    """50% watched → watch_percent=50 on the episode row."""
    _seed_episode(db)
    with db.session_scope() as session:
        from metatv.core.repositories import RepositoryFactory
        repo = RepositoryFactory(session).episodes
        repo.record_watch_progress("e1", position_s=750, duration_s=1500)  # 50%
        ep = repo.get_by_id("e1")
        assert ep.watch_percent == 50, f"Expected 50, got {ep.watch_percent}"
        assert not ep.watch_completed


def test_episode_record_progress_stamps_100_when_completed(db):
    """Completing an episode sets watch_percent=100 and watch_completed=True."""
    _seed_episode(db)
    with db.session_scope() as session:
        from metatv.core.repositories import RepositoryFactory
        repo = RepositoryFactory(session).episodes
        repo.record_watch_progress("e1", position_s=1420, duration_s=1500)  # 94.7%
        ep = repo.get_by_id("e1")
        assert ep.watch_percent == 100
        assert bool(ep.watch_completed) is True


# ---------------------------------------------------------------------------
# 4. ChannelListDTO.from_orm carries watch_percent
# ---------------------------------------------------------------------------

def test_channel_list_dto_carries_watch_percent(db):
    """from_orm reads watch_percent from the ORM row."""
    _seed_movie(db)
    with db.session_scope() as session:
        from metatv.core.repositories import RepositoryFactory
        repo = RepositoryFactory(session).channels
        repo.record_watch_progress("m1", 600, 3000)  # 20%
        ch = repo.get_by_id("m1")
        from metatv.core.repositories.dtos import ChannelListDTO
        dto = ChannelListDTO.from_orm(ch)
        assert dto.watch_percent == 20


# ---------------------------------------------------------------------------
# 5. EpisodeDTO carries watch_percent via get_episodes_dto_by_season
# ---------------------------------------------------------------------------

def test_episode_dto_carries_watch_percent(db):
    """get_episodes_dto_by_season returns DTOs with watch_percent set."""
    _seed_episode(db)
    with db.session_scope() as session:
        from metatv.core.repositories import RepositoryFactory
        repo = RepositoryFactory(session).episodes
        repo.record_watch_progress("e1", 750, 1500)  # 50%

    with db.session_scope(commit=False) as session:
        from metatv.core.repositories import RepositoryFactory
        dtos = RepositoryFactory(session).episodes.get_episodes_dto_by_season("s1")

    ep = next(d for d in dtos if d.id == "e1")
    assert ep.watch_percent == 50


# ---------------------------------------------------------------------------
# 6. watch_progress_glyph() maps percent → correct glyph
# ---------------------------------------------------------------------------

def test_glyph_below_threshold_returns_empty():
    """5% (below default 10% threshold) → empty string (untouched)."""
    from metatv.gui.icons import watch_progress_glyph, partial_watched_q1_icon
    assert watch_progress_glyph(5, False, partial_threshold_pct=10) == "", \
        "Below threshold must return empty string"


def test_glyph_above_threshold_quarter():
    """20% (above 10% threshold, below 37%) → ◔ (quarter glyph)."""
    from metatv.gui.icons import watch_progress_glyph, partial_watched_q1_icon
    assert watch_progress_glyph(20, False, partial_threshold_pct=10) == partial_watched_q1_icon


def test_glyph_half():
    """50% → ◐ (half glyph)."""
    from metatv.gui.icons import watch_progress_glyph, partial_watched_icon
    assert watch_progress_glyph(50, False, partial_threshold_pct=10) == partial_watched_icon


def test_glyph_three_quarter():
    """80% → ◕ (three-quarter glyph)."""
    from metatv.gui.icons import watch_progress_glyph, partial_watched_q3_icon
    assert watch_progress_glyph(80, False, partial_threshold_pct=10) == partial_watched_q3_icon


def test_glyph_completed_returns_check():
    """watch_completed=True → ✓ regardless of percent."""
    from metatv.gui.icons import watch_progress_glyph, watched_icon
    assert watch_progress_glyph(50, True, partial_threshold_pct=10) == watched_icon
    assert watch_progress_glyph(0, True, partial_threshold_pct=10) == watched_icon


def test_glyph_100_percent_without_completed_flag():
    """100% but watch_completed=False → ◕ (three-quarter bucket; sticky flag not set)."""
    from metatv.gui.icons import watch_progress_glyph, partial_watched_q3_icon
    # 100 >= 63 → three-quarter bucket when not flagged
    assert watch_progress_glyph(100, False, partial_threshold_pct=10) == partial_watched_q3_icon


def test_glyph_threshold_boundary():
    """Exactly at partial_threshold_pct shows the quarter glyph."""
    from metatv.gui.icons import watch_progress_glyph, partial_watched_q1_icon
    assert watch_progress_glyph(10, False, partial_threshold_pct=10) == partial_watched_q1_icon


def test_glyph_one_below_threshold_empty():
    """One below partial_threshold_pct shows nothing."""
    from metatv.gui.icons import watch_progress_glyph
    assert watch_progress_glyph(9, False, partial_threshold_pct=10) == ""


# ---------------------------------------------------------------------------
# 7. Graduated glyph goes to DecorationRole (not display text) — icon lane migration
# ---------------------------------------------------------------------------

def _make_channel_list_dto(watch_percent: int, watch_completed: bool, watch_progress: int = 0):
    from metatv.core.repositories.dtos import ChannelListDTO
    return ChannelListDTO(
        id="c1",
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
        watch_completed=watch_completed,
        watch_progress=watch_progress,
        watch_percent=watch_percent,
    )


def _build_model(partial_threshold_pct: int = 10):
    from metatv.gui.channel_list_model import ChannelListModel
    model = ChannelListModel.__new__(ChannelListModel)
    model._channels = []
    model._has_more = False
    model._fetching = False
    model._query_params = {}
    model._current_offset = 0
    model._provider_icon_map = {}
    model._show_provider_icon = False
    from metatv.gui import icons as _icons
    model._favorite_icon = _icons.favorite_icon
    model._unfavorite_icon = _icons.unfavorite_icon
    model._get_media_type_icon = None
    model._generation = 0
    model._id_to_index = {}
    model._partial_threshold_pct = partial_threshold_pct
    return model


def test_compose_display_text_quarter_glyph():
    """20% → glyph in DecorationRole (not text); text must NOT contain the glyph."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QIcon
    from metatv.gui import icons as _icons
    from metatv.gui.channel_list_model import ChannelListModel
    qapp = __import__('PyQt6.QtWidgets', fromlist=['QApplication']).QApplication
    app = qapp.instance() or qapp([])

    model = ChannelListModel()
    dto = _make_channel_list_dto(watch_percent=20, watch_completed=False)
    model.set_channels([dto], provider_icon_map={}, show_provider_icon=False,
                       has_more=False, query_params={}, partial_threshold_pct=10)
    idx = model.index(0, 0)
    text = idx.data(Qt.ItemDataRole.DisplayRole)
    icon = idx.data(Qt.ItemDataRole.DecorationRole)
    # Glyph must NOT appear in text (it lives in the icon lane now)
    assert _icons.partial_watched_q1_icon not in text, (
        f"Glyph must be in icon lane, not text; got: {text!r}"
    )
    # DecorationRole must return a QIcon for this partially-watched row
    assert isinstance(icon, QIcon), f"Expected QIcon for 20% watched, got: {icon!r}"


def test_compose_display_text_half_glyph():
    """50% → glyph in DecorationRole (not text); text must NOT contain the glyph."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QIcon
    from metatv.gui import icons as _icons
    from metatv.gui.channel_list_model import ChannelListModel
    qapp = __import__('PyQt6.QtWidgets', fromlist=['QApplication']).QApplication
    app = qapp.instance() or qapp([])

    model = ChannelListModel()
    dto = _make_channel_list_dto(watch_percent=50, watch_completed=False)
    model.set_channels([dto], provider_icon_map={}, show_provider_icon=False,
                       has_more=False, query_params={}, partial_threshold_pct=10)
    idx = model.index(0, 0)
    text = idx.data(Qt.ItemDataRole.DisplayRole)
    icon = idx.data(Qt.ItemDataRole.DecorationRole)
    assert _icons.partial_watched_icon not in text, (
        f"Glyph must be in icon lane, not text; got: {text!r}"
    )
    assert isinstance(icon, QIcon), f"Expected QIcon for 50% watched, got: {icon!r}"


def test_compose_display_text_three_quarter_glyph():
    """80% → glyph in DecorationRole (not text); text must NOT contain the glyph."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QIcon
    from metatv.gui import icons as _icons
    from metatv.gui.channel_list_model import ChannelListModel
    qapp = __import__('PyQt6.QtWidgets', fromlist=['QApplication']).QApplication
    app = qapp.instance() or qapp([])

    model = ChannelListModel()
    dto = _make_channel_list_dto(watch_percent=80, watch_completed=False)
    model.set_channels([dto], provider_icon_map={}, show_provider_icon=False,
                       has_more=False, query_params={}, partial_threshold_pct=10)
    idx = model.index(0, 0)
    text = idx.data(Qt.ItemDataRole.DisplayRole)
    icon = idx.data(Qt.ItemDataRole.DecorationRole)
    assert _icons.partial_watched_q3_icon not in text, (
        f"Glyph must be in icon lane, not text; got: {text!r}"
    )
    assert isinstance(icon, QIcon), f"Expected QIcon for 80% watched, got: {icon!r}"


def test_compose_display_text_completed_check():
    """Completed → checkmark icon in DecorationRole (not embedded in text)."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QIcon
    from metatv.gui import icons as _icons
    from metatv.gui.channel_list_model import ChannelListModel
    qapp = __import__('PyQt6.QtWidgets', fromlist=['QApplication']).QApplication
    app = qapp.instance() or qapp([])

    model = ChannelListModel()
    dto = _make_channel_list_dto(watch_percent=100, watch_completed=True)
    model.set_channels([dto], provider_icon_map={}, show_provider_icon=False,
                       has_more=False, query_params={}, partial_threshold_pct=10)
    idx = model.index(0, 0)
    text = idx.data(Qt.ItemDataRole.DisplayRole)
    icon = idx.data(Qt.ItemDataRole.DecorationRole)
    assert _icons.watched_icon not in text, (
        f"Check-mark must be in icon lane, not text; got: {text!r}"
    )
    assert isinstance(icon, QIcon), f"Expected QIcon for completed row, got: {icon!r}"


def test_compose_display_text_untouched_no_glyph():
    """5% (below 10% threshold) → none of the progress glyphs appear."""
    from metatv.gui import icons as _icons
    model = _build_model(partial_threshold_pct=10)
    dto = _make_channel_list_dto(watch_percent=5, watch_completed=False)
    text = model._compose_display_text(dto)
    assert _icons.partial_watched_q1_icon not in text
    assert _icons.partial_watched_icon not in text
    assert _icons.partial_watched_q3_icon not in text
    assert _icons.watched_icon not in text


def test_compose_display_text_live_channel_no_glyph():
    """Live channels never show any progress glyph."""
    from metatv.core.repositories.dtos import ChannelListDTO
    from metatv.gui import icons as _icons
    model = _build_model(partial_threshold_pct=10)
    dto = ChannelListDTO(
        id="l1", name="Live Channel", media_type="live",
        provider_id="p1", is_favorite=False, category=None, quality=None,
        detected_prefix=None, detected_region=None, detected_quality=None,
        detected_year=None, detected_title=None,
        watch_completed=True, watch_progress=100, watch_percent=80,
    )
    text = model._compose_display_text(dto)
    assert _icons.watched_icon not in text
    assert _icons.partial_watched_q1_icon not in text
    assert _icons.partial_watched_icon not in text
    assert _icons.partial_watched_q3_icon not in text


# ---------------------------------------------------------------------------
# 8. Settings dialog round-trips watch_partial_threshold
# ---------------------------------------------------------------------------

def test_settings_dialog_saves_partial_threshold(tmp_path):
    """Changing the partial-watched spinner persists watch_partial_threshold to config."""
    from metatv.core.config import Config
    config = Config(
        config_dir=tmp_path / "cfg",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )
    config.config_dir.mkdir(parents=True, exist_ok=True)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.cache_dir.mkdir(parents=True, exist_ok=True)

    from metatv.gui.settings_dialog import SettingsDialog
    dialog = SettingsDialog.__new__(SettingsDialog)
    dialog.config = config

    # Build a minimal mock for the spinner
    mock_spin = MagicMock()
    mock_spin.value.return_value = 15   # user set 15%

    # Patch the attributes that _save_values reads
    dialog._player_combo = MagicMock()
    dialog._player_combo.currentText.return_value = "mpv"
    dialog._player_mode_combo = MagicMock()
    dialog._player_mode_combo.currentIndex.return_value = 0
    dialog._autoplay_check = MagicMock()
    dialog._autoplay_check.isChecked.return_value = True
    dialog._watch_threshold_spin = MagicMock()
    dialog._watch_threshold_spin.value.return_value = 90
    dialog._watch_partial_spin = mock_spin
    dialog._close_player_check = MagicMock()
    dialog._close_player_check.isChecked.return_value = True
    dialog._timeout_spin = MagicMock()
    dialog._timeout_spin.value.return_value = 30
    dialog._reconnect_spin = MagicMock()
    dialog._reconnect_spin.value.return_value = 3
    dialog._buffer_combo = MagicMock()
    dialog._buffer_combo.currentData.return_value = "modest"
    dialog._mpv_args_input = MagicMock()
    dialog._mpv_args_input.text.return_value = ""
    dialog._prebuffer_check = MagicMock()
    dialog._prebuffer_check.isChecked.return_value = False
    dialog._prebuffer_wait_spin = MagicMock()
    dialog._prebuffer_wait_spin.value.return_value = 10
    dialog._override_all_check = MagicMock()
    dialog._override_all_check.isChecked.return_value = False
    dialog._split_check = MagicMock()
    dialog._split_check.isChecked.return_value = False
    dialog._epg_interval_combo = MagicMock()
    dialog._epg_interval_combo.currentData.return_value = "3d"
    dialog._meta_enabled_check = MagicMock()
    dialog._meta_enabled_check.isChecked.return_value = True
    dialog._meta_autofetch_check = MagicMock()
    dialog._meta_autofetch_check.isChecked.return_value = True
    dialog._cache_ttl_spin = MagicMock()
    dialog._cache_ttl_spin.value.return_value = 30
    dialog._cache_old_ttl_spin = MagicMock()
    dialog._cache_old_ttl_spin.value.return_value = 90
    dialog._tmdb_key_input = MagicMock()
    dialog._tmdb_key_input.text.return_value = ""
    dialog._tmdb_lang_input = MagicMock()
    dialog._tmdb_lang_input.text.return_value = "en-US"
    dialog._omdb_key_input = MagicMock()
    dialog._omdb_key_input.text.return_value = ""
    dialog._sidebar_list = MagicMock()
    dialog._sidebar_list.count.return_value = 0

    dialog._save_values()

    assert abs(config.watch_partial_threshold - 0.15) < 1e-9, (
        f"Expected 0.15, got {config.watch_partial_threshold}"
    )


# ---------------------------------------------------------------------------
# 9. Config.watch_partial_threshold defaults and persists
# ---------------------------------------------------------------------------

def test_config_watch_partial_threshold_default():
    """watch_partial_threshold defaults to 0.10."""
    from metatv.core.config import Config
    c = Config()
    assert hasattr(c, "watch_partial_threshold")
    assert abs(c.watch_partial_threshold - 0.10) < 1e-9


def test_config_watch_partial_threshold_round_trips(tmp_path):
    """watch_partial_threshold survives a save/load cycle."""
    from metatv.core.config import Config
    cfg_dir = tmp_path / "cfg"
    data_dir = tmp_path / "data"
    cache_dir = tmp_path / "cache"
    for d in (cfg_dir, data_dir, cache_dir):
        d.mkdir(parents=True, exist_ok=True)

    c = Config(config_dir=cfg_dir, data_dir=data_dir, cache_dir=cache_dir)
    c.watch_partial_threshold = 0.20
    c.save()

    import yaml
    with open(cfg_dir / "config.yaml") as f:
        data = yaml.safe_load(f)
    loaded = Config(**data)
    assert abs(loaded.watch_partial_threshold - 0.20) < 1e-9


# ---------------------------------------------------------------------------
# 10. What's New entry id=22 exists and is loadable
# ---------------------------------------------------------------------------

def test_whats_new_entry_22_exists():
    """Entry 22 (graduated watch progress) is in the changelog with the right id."""
    from metatv.whats_new import WHATS_NEW
    ids = {e.id for e in WHATS_NEW}
    assert 22 in ids, f"Entry 22 not found in WHATS_NEW; found ids: {sorted(ids)}"
    entry = next(e for e in WHATS_NEW if e.id == 22)
    assert "◔" in entry.title or "graduated" in entry.title.lower(), (
        f"Entry 22 title does not describe graduated watch progress: {entry.title!r}"
    )
