"""Behavioral tests for B10-5: ChannelListDTO on the central channel-list path.

These pin the actual change — the channel list no longer carries ORM/session
state across the worker→main-thread boundary:

1. ``ChannelListDTO.from_orm`` reads every needed column inside a session and the
   resulting frozen dataclass is fully readable AFTER the session closes (the
   DetachedInstanceError-safety the whole change buys).
2. ``_on_channels_loaded`` renders ``all_channels`` entries straight from DTOs —
   display text reflects the DTO fields (favorite icon, detected_title, prefix,
   year, category).
3. The favorites-toggle cache update replaces the frozen DTO with a NEW one
   carrying the flipped flag (a mutation would raise on a frozen dataclass).
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from metatv.core.repositories.dtos import ChannelListDTO


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _make_dto(**overrides) -> ChannelListDTO:
    base = dict(
        id=str(uuid.uuid4()),
        name="Raw Name",
        media_type="movie",
        provider_id="prov1",
        is_favorite=False,
        category="",
        quality="unknown",
        detected_prefix=None,
        detected_region=None,
        detected_quality=None,
        detected_year=None,
        detected_title=None,
    )
    base.update(overrides)
    return ChannelListDTO(**base)


# ---------------------------------------------------------------------------
# 1. ChannelListDTO.from_orm survives session close (file-backed DB)
# ---------------------------------------------------------------------------

def test_from_orm_survives_session_close(tmp_path):
    """Build the DTO inside a session, close it, then read every field.

    Uses a file-backed DB (not :memory:) so the closed-session detach is real —
    the DTO must hold plain values, not a live ORM reference.
    """
    from metatv.core.database import Database, ChannelDB
    from metatv.core.repositories import RepositoryFactory

    db = Database(f"sqlite:///{tmp_path / 't.db'}")
    db.create_tables()

    cid = str(uuid.uuid4())
    with db.session_scope() as session:
        session.add(ChannelDB(
            id=cid,
            source_id="9",
            provider_id="prov1",
            name="EN - The Matrix (1999)",
            media_type="movie",
            category="Action",
            quality="HD",
            is_favorite=True,
            detected_prefix="EN",
            detected_region="US",
            detected_quality="HD",
            detected_year="1999",
            detected_title="The Matrix",
        ))

    # Build the DTO inside one scope...
    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        ch = repos.channels.get_by_id(cid)
        dto = ChannelListDTO.from_orm(ch)

    # ...and read everything AFTER it closed — no DetachedInstanceError.
    assert dto.id == cid
    assert dto.name == "EN - The Matrix (1999)"
    assert dto.media_type == "movie"
    assert dto.provider_id == "prov1"
    assert dto.is_favorite is True
    assert dto.category == "Action"
    assert dto.quality == "HD"
    assert dto.detected_prefix == "EN"
    assert dto.detected_region == "US"
    assert dto.detected_quality == "HD"
    assert dto.detected_year == "1999"
    assert dto.detected_title == "The Matrix"

    db.close()


def test_channel_list_dto_is_frozen():
    """A frozen dataclass must reject attribute assignment (Step 3 relies on this)."""
    import dataclasses
    dto = _make_dto()
    with pytest.raises(dataclasses.FrozenInstanceError):
        dto.is_favorite = True  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 2. _on_channels_loaded renders all_channels from DTOs (main-thread half)
# ---------------------------------------------------------------------------

def _make_render_host(qapp):
    """Real MainWindow via __new__ with the minimal widgets the render loop touches."""
    from PyQt6.QtWidgets import QListWidget
    from metatv.gui import main_window as mw_module

    win = mw_module.MainWindow.__new__(mw_module.MainWindow)
    win.all_channels = []
    win.channels_list = QListWidget()
    win.stats_label = MagicMock()
    win.status_bar = MagicMock()
    win.max_display_limit = 1000
    win._search_page_size = 5000
    win._currently_bypassing = False
    win._clear_provider_busy = MagicMock()

    # Icon presentation constants the render loop reads.
    win.favorite_icon = "★"
    win.unfavorite_icon = "☆"
    win.live_icon = "L"
    win.movie_icon = "M"
    win.series_icon = "S"
    win.unknown_icon = "?"
    return win


def test_on_channels_loaded_builds_all_channels_from_dtos(qapp):
    host = _make_render_host(qapp)
    dto = _make_dto(
        media_type="movie",
        is_favorite=True,
        detected_prefix="EN",
        detected_region="US",
        detected_quality="HD",
        detected_year="1999",
        detected_title="The Matrix",
        category="Action",
    )
    params = {
        "total_channels": 1,
        "has_adult": False,
        "show_provider_icon": False,
        "provider_icon_map": {},
        "given_provider_id": None,
        "hidden_only": False,
        "filtered_out_count": 0,
        "bypassing_tier1": False,
    }

    host._on_channels_loaded((  # seam delivers a single (dtos, params) tuple
        [dto], params,
    ))

    # all_channels populated with (display_text, dto) — the DTO itself, not an ORM obj.
    assert len(host.all_channels) == 1
    display_text, stored = host.all_channels[0]
    assert stored is dto
    # Display reflects DTO fields: favorite icon, detected_title (not raw name), prefix, year, category.
    assert "★" in display_text                 # favorite icon (is_favorite=True)
    assert "The Matrix" in display_text        # detected_title
    assert "Raw Name" not in display_text      # raw name suppressed in favor of detected_title
    assert "[EN]" in display_text              # detected_prefix
    assert "1999" in display_text              # detected_year
    assert "[Action]" in display_text          # category
    host._clear_provider_busy.assert_called_once()


def test_on_channels_loaded_uses_unfavorite_icon_when_not_favorite(qapp):
    host = _make_render_host(qapp)
    dto = _make_dto(is_favorite=False, detected_title="Plain Title")
    params = {"total_channels": 1, "hidden_only": False, "bypassing_tier1": False}
    host._on_channels_loaded(([dto], params))
    display_text, _ = host.all_channels[0]
    assert "☆" in display_text
    assert "★" not in display_text


def test_on_channels_loaded_empty_sets_stats(qapp):
    host = _make_render_host(qapp)
    params = {"total_channels": 0, "hidden_only": False,
              "filtered_out_count": 0, "bypassing_tier1": False}
    host._on_channels_loaded(([], params))
    assert host.all_channels == []
    host.stats_label.setText.assert_called()   # zero-result branch set a stats string


# ---------------------------------------------------------------------------
# 3. Favorites toggle replaces the frozen DTO (Step 3) — does NOT mutate
# ---------------------------------------------------------------------------

def test_favorite_toggle_replaces_frozen_dto(qapp):
    """The cache update must store a NEW DTO with is_favorite flipped, not mutate."""
    from metatv.gui import main_window as mw_module

    win = mw_module.MainWindow.__new__(mw_module.MainWindow)
    win.favorite_icon = "★"
    win.unfavorite_icon = "☆"
    win.get_media_type_icon = MagicMock(return_value="M")
    win.status_bar = MagicMock()
    win.load_favorites = MagicMock()

    cid = "chan-1"
    original = _make_dto(id=cid, name="Movie", category="Action", quality="HD",
                         is_favorite=False, media_type="movie")
    win.all_channels = [("☆M Movie [Action] (HD)", original)]

    # Stub _apply_favorite_toggle to return a (channel, status) whose is_favorite=True.
    toggled = MagicMock()
    toggled.is_favorite = True
    win._apply_favorite_toggle = MagicMock(return_value=(toggled, True))

    item = MagicMock()
    item.data.return_value = cid
    item.text.return_value = "☆M Movie [Action] (HD)"

    win.toggle_favorite(item)

    # Entry replaced with a NEW DTO carrying the flipped flag.
    _, stored = win.all_channels[0]
    assert stored is not original                 # tuple/object replaced, not mutated
    assert stored.is_favorite is True
    assert original.is_favorite is False          # original untouched (frozen)
    # Other fields preserved on the new DTO.
    assert stored.id == cid
    assert stored.name == "Movie"
    assert stored.category == "Action"
    assert stored.quality == "HD"
