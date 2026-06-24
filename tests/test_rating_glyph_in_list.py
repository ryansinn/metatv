"""Behavioral tests for rating glyphs in the channel list (task #42 — display only).

Covers:
1. ChannelListDTO carries user_rating (field exists, from_orm threads it through).
2. RatingRepository.get_all_map() returns the correct channel_id → rating dict.
3. ChannelListModel.data(DisplayRole) appends 👍 for liked rows, 👎 for disliked,
   and nothing for unrated rows.
4. ChannelListModel.data(ToolTipRole) returns the rating tooltip for rated rows and
   None for unrated rows.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from metatv.core.repositories.dtos import ChannelListDTO


# ---------------------------------------------------------------------------
# Fixtures / helpers
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
        user_rating=0,
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
        favorite_icon="★",
        unfavorite_icon="☆",
        partial_threshold_pct=10,
    )
    return model


# ---------------------------------------------------------------------------
# 1. ChannelListDTO carries user_rating
# ---------------------------------------------------------------------------

def test_channel_list_dto_has_user_rating_field():
    """ChannelListDTO must accept and expose user_rating."""
    dto_liked = _make_dto(user_rating=1)
    assert dto_liked.user_rating == 1

    dto_disliked = _make_dto(user_rating=-1)
    assert dto_disliked.user_rating == -1

    dto_unrated = _make_dto(user_rating=0)
    assert dto_unrated.user_rating == 0


def test_channel_list_dto_user_rating_defaults_to_zero():
    """user_rating must default to 0 when not supplied (backward compat)."""
    # Construct without user_rating keyword — it must not be required.
    dto = ChannelListDTO(
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
    )
    assert dto.user_rating == 0


def test_channel_list_dto_from_orm_threads_user_rating(tmp_path):
    """from_orm must store the user_rating kwarg into the frozen DTO."""
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
            name="My Liked Film",
            media_type="movie",
        ))

    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        ch = repos.channels.get_by_id(cid)
        dto = ChannelListDTO.from_orm(ch, user_rating=1)

    # DTO is readable after session closes and carries the rating.
    assert dto.id == cid
    assert dto.user_rating == 1
    db.close()


def test_channel_list_dto_from_orm_defaults_user_rating_to_zero(tmp_path):
    """from_orm without user_rating kwarg must default to 0 (unrated)."""
    from metatv.core.database import Database, ChannelDB
    from metatv.core.repositories import RepositoryFactory

    db = Database(f"sqlite:///{tmp_path / 't2.db'}")
    db.create_tables()

    cid = str(uuid.uuid4())
    with db.session_scope() as session:
        session.add(ChannelDB(
            id=cid, source_id="9", provider_id="prov1", name="Unrated", media_type="movie",
        ))

    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        ch = repos.channels.get_by_id(cid)
        dto = ChannelListDTO.from_orm(ch)  # no user_rating kwarg

    assert dto.user_rating == 0
    db.close()


# ---------------------------------------------------------------------------
# 2. RatingRepository.get_all_map()
# ---------------------------------------------------------------------------

def test_rating_repo_get_all_map_returns_correct_dict(tmp_path):
    """get_all_map() must return channel_id → rating for all rated channels."""
    from metatv.core.database import Database, ChannelDB, UserRatingDB
    from metatv.core.repositories import RepositoryFactory
    from datetime import datetime

    db = Database(f"sqlite:///{tmp_path / 'r.db'}")
    db.create_tables()

    liked_id = str(uuid.uuid4())
    disliked_id = str(uuid.uuid4())
    unrated_id = str(uuid.uuid4())

    with db.session_scope() as session:
        for cid, name in [(liked_id, "Liked"), (disliked_id, "Disliked"), (unrated_id, "Unrated")]:
            session.add(ChannelDB(id=cid, source_id=cid, provider_id="p", name=name, media_type="movie"))
        session.add(UserRatingDB(channel_id=liked_id, rating=1, rated_at=datetime.utcnow()))
        session.add(UserRatingDB(channel_id=disliked_id, rating=-1, rated_at=datetime.utcnow()))

    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        ratings = repos.ratings.get_all_map()

    assert ratings[liked_id] == 1
    assert ratings[disliked_id] == -1
    assert unrated_id not in ratings
    db.close()


def test_rating_repo_get_all_map_empty_when_no_ratings(tmp_path):
    """get_all_map() on a DB with no ratings must return an empty dict."""
    from metatv.core.database import Database
    from metatv.core.repositories import RepositoryFactory

    db = Database(f"sqlite:///{tmp_path / 'empty.db'}")
    db.create_tables()

    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        ratings = repos.ratings.get_all_map()

    assert ratings == {}
    db.close()


# ---------------------------------------------------------------------------
# 3. ChannelListModel.data(DisplayRole) — rating glyph in text
# ---------------------------------------------------------------------------

def test_display_role_appends_like_glyph_for_liked_channel(qapp):
    """A liked channel (user_rating=1) must end its display text with 👍."""
    from PyQt6.QtCore import Qt
    from metatv.gui import icons as _icons

    model = _make_model(qapp, _make_dto(user_rating=1, detected_title="Great Film"))
    text = model.index(0, 0).data(Qt.ItemDataRole.DisplayRole)

    assert _icons.like_icon in text, f"Expected 👍 in display text, got: {text!r}"
    assert _icons.dislike_icon not in text
    assert "Great Film" in text


def test_display_role_appends_dislike_glyph_for_disliked_channel(qapp):
    """A disliked channel (user_rating=-1) must end its display text with 👎."""
    from PyQt6.QtCore import Qt
    from metatv.gui import icons as _icons

    model = _make_model(qapp, _make_dto(user_rating=-1, detected_title="Bad Film"))
    text = model.index(0, 0).data(Qt.ItemDataRole.DisplayRole)

    assert _icons.dislike_icon in text, f"Expected 👎 in display text, got: {text!r}"
    assert _icons.like_icon not in text
    assert "Bad Film" in text


def test_display_role_no_rating_glyph_for_unrated_channel(qapp):
    """An unrated channel (user_rating=0) must show neither 👍 nor 👎."""
    from PyQt6.QtCore import Qt
    from metatv.gui import icons as _icons

    model = _make_model(qapp, _make_dto(user_rating=0, detected_title="Unrated Film"))
    text = model.index(0, 0).data(Qt.ItemDataRole.DisplayRole)

    assert _icons.like_icon not in text, f"Unexpected 👍 in unrated row: {text!r}"
    assert _icons.dislike_icon not in text, f"Unexpected 👎 in unrated row: {text!r}"
    assert "Unrated Film" in text


def test_display_role_rating_glyph_is_trailing(qapp):
    """The rating glyph must appear after the title (not before it)."""
    from PyQt6.QtCore import Qt
    from metatv.gui import icons as _icons

    model = _make_model(qapp, _make_dto(user_rating=1, detected_title="My Movie"))
    text = model.index(0, 0).data(Qt.ItemDataRole.DisplayRole)

    title_pos = text.find("My Movie")
    glyph_pos = text.find(_icons.like_icon)
    assert title_pos != -1, "Title not in display text"
    assert glyph_pos > title_pos, (
        f"Rating glyph at {glyph_pos} must be after title at {title_pos} in {text!r}"
    )


# ---------------------------------------------------------------------------
# 4. ChannelListModel.data(ToolTipRole) — rating tooltips
# ---------------------------------------------------------------------------

def test_tooltip_role_liked_channel(qapp):
    """A liked channel must return the 👍 tooltip string."""
    from PyQt6.QtCore import Qt
    from metatv.gui import icons as _icons

    model = _make_model(qapp, _make_dto(user_rating=1))
    tip = model.index(0, 0).data(Qt.ItemDataRole.ToolTipRole)

    assert tip is not None
    assert _icons.like_icon in tip
    assert "rated" in tip.lower()


def test_tooltip_role_disliked_channel(qapp):
    """A disliked channel must return the 👎 tooltip string."""
    from PyQt6.QtCore import Qt
    from metatv.gui import icons as _icons

    model = _make_model(qapp, _make_dto(user_rating=-1))
    tip = model.index(0, 0).data(Qt.ItemDataRole.ToolTipRole)

    assert tip is not None
    assert _icons.dislike_icon in tip
    assert "rated" in tip.lower()


def test_tooltip_role_unrated_channel_returns_none(qapp):
    """An unrated channel must return None for ToolTipRole (no tooltip shown)."""
    from PyQt6.QtCore import Qt

    model = _make_model(qapp, _make_dto(user_rating=0))
    tip = model.index(0, 0).data(Qt.ItemDataRole.ToolTipRole)

    assert tip is None, f"Expected None for unrated row, got: {tip!r}"


# ---------------------------------------------------------------------------
# 5. ChannelListModel.update_rating() — in-place glyph update (task #63)
# ---------------------------------------------------------------------------

def test_update_rating_like_updates_dto_and_display(qapp):
    """update_rating(id, 1) must update the DTO user_rating and show the like glyph."""
    from PyQt6.QtCore import Qt
    from metatv.gui import icons as _icons

    dto = _make_dto(user_rating=0, detected_title="Good Film")
    model = _make_model(qapp, dto)

    model.update_rating(dto.id, 1)

    # DTO in the model must be updated.
    assert model._channels[0].user_rating == 1
    # DisplayRole must now contain the like glyph.
    text = model.index(0, 0).data(Qt.ItemDataRole.DisplayRole)
    assert _icons.like_icon in text, f"Expected 👍 in display after update_rating(1), got: {text!r}"
    assert _icons.dislike_icon not in text


def test_update_rating_clear_removes_glyph(qapp):
    """update_rating(id, 0) must clear user_rating and remove both glyphs from display."""
    from PyQt6.QtCore import Qt
    from metatv.gui import icons as _icons

    dto = _make_dto(user_rating=1, detected_title="Cleared Film")
    model = _make_model(qapp, dto)

    model.update_rating(dto.id, 0)

    assert model._channels[0].user_rating == 0
    text = model.index(0, 0).data(Qt.ItemDataRole.DisplayRole)
    assert _icons.like_icon not in text, f"Unexpected 👍 after clearing rating: {text!r}"
    assert _icons.dislike_icon not in text, f"Unexpected 👎 after clearing rating: {text!r}"


def test_update_rating_dislike_updates_dto_and_display(qapp):
    """update_rating(id, -1) must update the DTO user_rating and show the dislike glyph."""
    from PyQt6.QtCore import Qt
    from metatv.gui import icons as _icons

    dto = _make_dto(user_rating=0, detected_title="Bad Film")
    model = _make_model(qapp, dto)

    model.update_rating(dto.id, -1)

    assert model._channels[0].user_rating == -1
    text = model.index(0, 0).data(Qt.ItemDataRole.DisplayRole)
    assert _icons.dislike_icon in text, f"Expected 👎 in display after update_rating(-1), got: {text!r}"
    assert _icons.like_icon not in text


def test_update_rating_nonexistent_channel_no_exception(qapp):
    """update_rating for an id not in the model must be a silent no-op."""
    dto = _make_dto(user_rating=0)
    model = _make_model(qapp, dto)

    # Must not raise.
    model.update_rating("nonexistent-id-xyz", 1)

    # Original DTO is untouched.
    assert model._channels[0].user_rating == 0
