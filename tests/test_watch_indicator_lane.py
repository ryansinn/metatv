"""Behavioral tests for the watch-indicator icon lane (#27, 3b-2).

Covers:
1. icons.watch_icon() -- returns distinct QIcon objects for muted vs solid.
2. icons.watch_icon_for_channel() -- None for no-glyph; muted for queue; solid otherwise.
3. ChannelListModel.data(DecorationRole) -- icon for watched non-live; None for live / unwatched.
4. No prepended glyph in DisplayRole text for watched channels.
5. last_played_via present on ChannelListDTO and EpisodeDTO.
6. EpisodeRepository.get_episodes_dto_by_season threads last_played_via into EpisodeDTO.
"""

from __future__ import annotations

import uuid

import pytest

from metatv.core.repositories.dtos import ChannelListDTO, EpisodeDTO


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_dto(**overrides) -> ChannelListDTO:
    base = dict(
        id=str(uuid.uuid4()),
        name="Channel",
        media_type="movie",
        provider_id="prov1",
        is_favorite=False,
        category=None,
        quality=None,
        detected_prefix=None,
        detected_region=None,
        detected_quality=None,
        detected_year=None,
        detected_title="My Film",
        watch_completed=False,
        watch_progress=0,
        watch_percent=0,
        last_played_via=None,
    )
    base.update(overrides)
    return ChannelListDTO(**base)


def _make_model(qapp, *dtos):
    from metatv.gui.channel_list_model import ChannelListModel
    model = ChannelListModel()
    model.set_channels(
        list(dtos),
        provider_icon_map={},
        show_provider_icon=False,
        has_more=False,
        query_params={},
        favorite_icon="star",
        unfavorite_icon="nostar",
        partial_threshold_pct=10,
    )
    return model


# ---------------------------------------------------------------------------
# 1. icons.watch_icon() -- solid vs muted
# ---------------------------------------------------------------------------

def test_watch_icon_solid_and_muted_are_different_objects(qapp):
    """watch_icon returns distinct QIcon instances for solid vs muted."""
    from metatv.gui import icons as _icons
    solid = _icons.watch_icon("checkmark", muted=False)
    muted = _icons.watch_icon("checkmark", muted=True)
    from PyQt6.QtGui import QIcon
    assert isinstance(solid, QIcon)
    assert isinstance(muted, QIcon)
    assert solid is not muted


def test_watch_icon_is_cached(qapp):
    """Calling watch_icon twice with the same args returns the same object."""
    from metatv.gui import icons as _icons
    a = _icons.watch_icon("circle", muted=False)
    b = _icons.watch_icon("circle", muted=False)
    assert a is b


# ---------------------------------------------------------------------------
# 2. icons.watch_icon_for_channel() -- provenance routing
# ---------------------------------------------------------------------------

def test_watch_icon_for_channel_none_when_no_glyph(qapp):
    """Empty or None glyph returns None (unwatched; icon lane stays blank)."""
    from metatv.gui import icons as _icons
    assert _icons.watch_icon_for_channel("", None) is None
    assert _icons.watch_icon_for_channel(None, None) is None


def test_watch_icon_for_channel_muted_when_queue(qapp):
    """last_played_via='queue' produces a muted icon."""
    from metatv.gui import icons as _icons
    from PyQt6.QtGui import QIcon
    icon = _icons.watch_icon_for_channel("check", "queue")
    assert isinstance(icon, QIcon)
    assert icon is _icons.watch_icon("check", muted=True)


def test_watch_icon_for_channel_solid_when_manual(qapp):
    """last_played_via='manual' produces a solid icon."""
    from metatv.gui import icons as _icons
    from PyQt6.QtGui import QIcon
    icon = _icons.watch_icon_for_channel("check", "manual")
    assert isinstance(icon, QIcon)
    assert icon is _icons.watch_icon("check", muted=False)


def test_watch_icon_for_channel_solid_when_none_provenance(qapp):
    """last_played_via=None with a glyph produces a solid icon (not queue = not muted)."""
    from metatv.gui import icons as _icons
    from PyQt6.QtGui import QIcon
    icon = _icons.watch_icon_for_channel("half", None)
    assert isinstance(icon, QIcon)
    assert icon is _icons.watch_icon("half", muted=False)


# ---------------------------------------------------------------------------
# 3. ChannelListModel.data(DecorationRole)
# ---------------------------------------------------------------------------

def test_decoration_role_returns_icon_for_watched_movie(qapp):
    """A watch_completed=True movie row returns a QIcon for DecorationRole."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QIcon

    model = _make_model(qapp, _make_dto(
        media_type="movie",
        watch_completed=True,
        watch_percent=100,
        last_played_via="manual",
    ))
    icon = model.index(0, 0).data(Qt.ItemDataRole.DecorationRole)
    assert isinstance(icon, QIcon), "Expected QIcon for fully-watched movie"


def test_decoration_role_returns_icon_for_partially_watched(qapp):
    """A partially-watched VOD row (above threshold) returns a QIcon."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QIcon

    model = _make_model(qapp, _make_dto(
        media_type="movie",
        watch_completed=False,
        watch_percent=50,
        last_played_via="queue",
    ))
    icon = model.index(0, 0).data(Qt.ItemDataRole.DecorationRole)
    assert isinstance(icon, QIcon)


def test_decoration_role_returns_none_for_unwatched_movie(qapp):
    """An unwatched movie (percent=0, not completed) returns None for DecorationRole."""
    from PyQt6.QtCore import Qt

    model = _make_model(qapp, _make_dto(
        media_type="movie",
        watch_completed=False,
        watch_percent=0,
        watch_progress=0,
        last_played_via=None,
    ))
    icon = model.index(0, 0).data(Qt.ItemDataRole.DecorationRole)
    assert icon is None, "Unwatched rows must have no decoration icon"


def test_decoration_role_returns_none_for_live_channel(qapp):
    """Live channels never get a watch indicator icon -- always None."""
    from PyQt6.QtCore import Qt

    model = _make_model(qapp, _make_dto(
        media_type="live",
        watch_completed=True,  # edge case
        watch_percent=100,
        last_played_via="manual",
    ))
    icon = model.index(0, 0).data(Qt.ItemDataRole.DecorationRole)
    assert icon is None, "Live channels must never show a watch indicator"


def test_decoration_role_muted_icon_for_queue_watched(qapp):
    """queue-watched row's DecorationRole icon uses the muted (gray) color.

    Verifies that the center-pixel color of the icon matches the muted theme
    token, not the solid foreground token.  Uses pixmap sampling because
    PyQt6 wraps the cached C++ QIcon in a new Python object on each access,
    so identity checks ('is') are unreliable.
    """
    from PyQt6.QtCore import Qt
    from metatv.gui import icons as _icons

    model = _make_model(qapp, _make_dto(
        media_type="movie",
        watch_completed=True,
        watch_percent=100,
        last_played_via="queue",
    ))
    icon = model.index(0, 0).data(Qt.ItemDataRole.DecorationRole)
    muted_ref = _icons.watch_icon(_icons.watched_icon, muted=True)
    solid_ref = _icons.watch_icon(_icons.watched_icon, muted=False)
    # Sample the center pixel of each pixmap and compare colors.
    def _center_pixel(qicon):
        pm = qicon.pixmap(14, 14)
        return pm.toImage().pixel(7, 7)
    assert _center_pixel(icon) == _center_pixel(muted_ref), (
        "queue-watched icon center pixel must match the muted color"
    )
    assert _center_pixel(icon) != _center_pixel(solid_ref), (
        "queue-watched icon must be visually distinct from the solid icon"
    )


def test_decoration_role_solid_icon_for_manual_watched(qapp):
    """manual-watched row's DecorationRole icon uses the solid (bright) color.

    Verifies that the center-pixel color of the icon matches the solid theme
    token, not the muted one.  Uses pixmap sampling for the same reason as the
    muted test above.
    """
    from PyQt6.QtCore import Qt
    from metatv.gui import icons as _icons

    model = _make_model(qapp, _make_dto(
        media_type="movie",
        watch_completed=True,
        watch_percent=100,
        last_played_via="manual",
    ))
    icon = model.index(0, 0).data(Qt.ItemDataRole.DecorationRole)
    muted_ref = _icons.watch_icon(_icons.watched_icon, muted=True)
    solid_ref = _icons.watch_icon(_icons.watched_icon, muted=False)
    def _center_pixel(qicon):
        pm = qicon.pixmap(14, 14)
        return pm.toImage().pixel(7, 7)
    assert _center_pixel(icon) == _center_pixel(solid_ref), (
        "manual-watched icon center pixel must match the solid color"
    )
    assert _center_pixel(icon) != _center_pixel(muted_ref), (
        "manual-watched icon must be visually distinct from the muted icon"
    )


# ---------------------------------------------------------------------------
# 4. No prepended glyph in DisplayRole text for watched channels
# ---------------------------------------------------------------------------

def test_display_text_has_no_watch_glyph_for_watched(qapp):
    """Watch glyphs must NOT appear in DisplayRole text -- they live in the icon lane."""
    from PyQt6.QtCore import Qt
    from metatv.gui import icons as _icons

    model = _make_model(qapp, _make_dto(
        media_type="movie",
        watch_completed=True,
        watch_percent=100,
        detected_title="My Film",
        last_played_via="manual",
    ))
    text = model.index(0, 0).data(Qt.ItemDataRole.DisplayRole)
    for glyph in (
        _icons.watched_icon,
        _icons.partial_watched_icon,
        _icons.partial_watched_q1_icon,
        _icons.partial_watched_q3_icon,
    ):
        assert glyph not in text, (
            f"Glyph {glyph!r} found in DisplayRole text {text!r}; "
            "it should be in the icon lane, not the text"
        )
    assert "My Film" in text


def test_display_text_has_no_watch_glyph_for_partial(qapp):
    """Partial-watch glyphs must NOT appear in DisplayRole text."""
    from PyQt6.QtCore import Qt
    from metatv.gui import icons as _icons

    model = _make_model(qapp, _make_dto(
        media_type="movie",
        watch_completed=False,
        watch_percent=55,
        detected_title="Ongoing Film",
        last_played_via="manual",
    ))
    text = model.index(0, 0).data(Qt.ItemDataRole.DisplayRole)
    assert _icons.partial_watched_icon not in text
    assert "Ongoing Film" in text


# ---------------------------------------------------------------------------
# 5. last_played_via present on DTOs
# ---------------------------------------------------------------------------

def test_channel_list_dto_has_last_played_via():
    """ChannelListDTO must accept and expose last_played_via."""
    dto = _make_dto(last_played_via="manual")
    assert dto.last_played_via == "manual"

    dto2 = _make_dto(last_played_via="queue")
    assert dto2.last_played_via == "queue"

    dto3 = _make_dto(last_played_via=None)
    assert dto3.last_played_via is None


def test_episode_dto_has_last_played_via():
    """EpisodeDTO must accept and expose last_played_via."""
    ep = EpisodeDTO(
        id="ep-1",
        episode_num=1,
        season_num=1,
        title="Pilot",
        series_name="My Show",
        stream_url="http://example.com/stream",
        duration="00:45:00",
        is_watched=True,
        rating=None,
        series_id="s1",
        provider_id="prov1",
        season_id="sea1",
        watch_progress=0,
        watch_completed=True,
        watch_percent=100,
        last_played_via="manual",
    )
    assert ep.last_played_via == "manual"


# ---------------------------------------------------------------------------
# 6. Repository: last_played_via threaded into DTOs
# ---------------------------------------------------------------------------

def test_episode_repo_dto_carries_last_played_via(tmp_path):
    """get_episodes_dto_by_season must populate last_played_via from EpisodeDB."""
    from metatv.core.database import Database, SeasonDB, EpisodeDB, ChannelDB
    from metatv.core.repositories import RepositoryFactory

    db = Database(f"sqlite:///{tmp_path / 't.db'}")
    db.create_tables()

    series_cid = str(uuid.uuid4())
    season_id = str(uuid.uuid4())
    ep1_id = str(uuid.uuid4())
    ep2_id = str(uuid.uuid4())

    with db.session_scope() as session:
        session.add(ChannelDB(
            id=series_cid,
            source_id="s1",
            provider_id="prov1",
            name="My Show",
            media_type="series",
        ))
        session.add(SeasonDB(
            id=season_id,
            series_id="s1",
            provider_id="prov1",
            season_number=1,
            episode_count=2,
        ))
        session.add(EpisodeDB(
            id=ep1_id,
            series_id="s1",
            provider_id="prov1",
            season_id=season_id,
            episode_id="ep-src-1",
            episode_num=1,
            season_num=1,
            title="Pilot",
            last_played_via="manual",
            watch_completed=True,
            watch_percent=100,
        ))
        session.add(EpisodeDB(
            id=ep2_id,
            series_id="s1",
            provider_id="prov1",
            season_id=season_id,
            episode_id="ep-src-2",
            episode_num=2,
            season_num=1,
            title="Episode 2",
            last_played_via="queue",
            watch_completed=False,
            watch_percent=45,
        ))

    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        dtos = repos.episodes.get_episodes_dto_by_season(season_id=season_id)

    assert len(dtos) == 2
    by_id = {d.id: d for d in dtos}
    assert by_id[ep1_id].last_played_via == "manual"
    assert by_id[ep2_id].last_played_via == "queue"

    db.close()


def test_channel_list_dto_from_orm_carries_last_played_via(tmp_path):
    """ChannelListDTO.from_orm must read last_played_via from ChannelDB."""
    from metatv.core.database import Database, ChannelDB
    from metatv.core.repositories import RepositoryFactory

    db = Database(f"sqlite:///{tmp_path / 't2.db'}")
    db.create_tables()

    cid = str(uuid.uuid4())
    with db.session_scope() as session:
        session.add(ChannelDB(
            id=cid,
            source_id="9",
            provider_id="prov1",
            name="My Movie",
            media_type="movie",
            last_played_via="manual",
            watch_completed=True,
            watch_percent=100,
        ))

    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        ch = repos.channels.get_by_id(cid)
        dto = ChannelListDTO.from_orm(ch)

    assert dto.last_played_via == "manual"
    db.close()
