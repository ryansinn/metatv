"""Tests for the "Hide Watched" filter axis (Part 1–3 of feat/watched-filter-axis).

Covers:
  1. SQL filter — get_all(exclude_watched=True) excludes watch_completed channels.
  2. count_watched_matching() returns accurate watched count.
  3. Targeted model update — update_watch_completed() in-place, no full reload.
  4. remove_channel() deletes row from model without resetting (generation stable).
"""

from __future__ import annotations

import uuid
import pytest

from tests.conftest import make_channel
from metatv.core.repositories.channel import ChannelRepository
from metatv.core.repositories.dtos import ChannelListDTO


# ── helpers ──────────────────────────────────────────────────────────────────

def _dto(channel_id: str, **kwargs) -> ChannelListDTO:
    """Build a minimal ChannelListDTO for model tests."""
    defaults = dict(
        id=channel_id,
        name=f"Channel {channel_id[:4]}",
        media_type="movie",
        is_favorite=False,
        provider_id="test",
        detected_prefix=None,
        detected_quality=None,
        detected_region=None,
        detected_title=None,
        detected_year=None,
        category=None,
        quality=None,
        watch_completed=False,
        watch_progress=0,
        watch_percent=0,
        user_rating=0,
    )
    defaults.update(kwargs)
    return ChannelListDTO(**defaults)


def _set_channels(model, dtos):
    """Populate the model with dtos in test mode (no real app state)."""
    model.set_channels(
        dtos,
        provider_icon_map={},
        show_provider_icon=False,
        has_more=False,
        query_params={},
        next_offset=len(dtos),
    )


# ── Part 1 — SQL filter axis ─────────────────────────────────────────────────

class TestExcludeWatched:
    """get_all(exclude_watched=True) excludes watch_completed=True channels."""

    def test_default_includes_watched(self, db_session, repo):
        """Default (exclude_watched=False) shows all channels including watched."""
        make_channel(db_session, "Movie A", media_type="movie", watch_completed=True)
        make_channel(db_session, "Movie B", media_type="movie", watch_completed=False)
        make_channel(db_session, "Movie C", media_type="movie")  # NULL → not watched
        db_session.commit()

        result = repo.get_all()
        names = {c.name for c in result}
        assert "Movie A" in names
        assert "Movie B" in names
        assert "Movie C" in names

    def test_exclude_watched_hides_completed(self, db_session, repo):
        """exclude_watched=True removes channels where watch_completed=True."""
        make_channel(db_session, "Watched Movie", media_type="movie", watch_completed=True)
        make_channel(db_session, "Unwatched Movie", media_type="movie", watch_completed=False)
        make_channel(db_session, "Fresh Movie", media_type="movie")
        db_session.commit()

        result = repo.get_all(exclude_watched=True)
        names = {c.name for c in result}
        assert "Watched Movie" not in names
        assert "Unwatched Movie" in names
        assert "Fresh Movie" in names

    def test_exclude_watched_treats_null_as_unwatched(self, db_session, repo):
        """NULL watch_completed (never set) is treated as unwatched — visible when filter ON."""
        ch = make_channel(db_session, "Null Watched", media_type="movie")
        # Don't set watch_completed; default is NULL / False
        db_session.commit()

        result = repo.get_all(exclude_watched=True)
        names = {c.name for c in result}
        assert "Null Watched" in names

    def test_exclude_watched_with_live_channels(self, db_session, repo):
        """Live channels with watch_completed=True are also excluded — the filter is media-type-agnostic."""
        make_channel(db_session, "Watched Live", media_type="live", watch_completed=True)
        make_channel(db_session, "Active Live", media_type="live", watch_completed=False)
        db_session.commit()

        result = repo.get_all(exclude_watched=True)
        names = {c.name for c in result}
        assert "Watched Live" not in names
        assert "Active Live" in names

    def test_exclude_watched_false_restores_all(self, db_session, repo):
        """Passing exclude_watched=False explicitly is same as default — shows all."""
        make_channel(db_session, "Watched Movie", media_type="movie", watch_completed=True)
        make_channel(db_session, "Unwatched Movie", media_type="movie")
        db_session.commit()

        result = repo.get_all(exclude_watched=False)
        assert len(result) == 2


# ── Part 2 — count_watched_matching ─────────────────────────────────────────

class TestCountWatchedMatching:
    """count_watched_matching() returns the count of watched items that match filters."""

    def test_zero_when_no_watched(self, db_session, repo):
        make_channel(db_session, "A", media_type="movie")
        make_channel(db_session, "B", media_type="movie")
        db_session.commit()

        count = repo.count_watched_matching()
        assert count == 0

    def test_counts_watched_channels(self, db_session, repo):
        make_channel(db_session, "W1", media_type="movie", watch_completed=True)
        make_channel(db_session, "W2", media_type="series", watch_completed=True)
        make_channel(db_session, "U1", media_type="movie", watch_completed=False)
        db_session.commit()

        count = repo.count_watched_matching()
        assert count == 2

    def test_respects_media_type_filter(self, db_session, repo):
        make_channel(db_session, "W Movie", media_type="movie", watch_completed=True)
        make_channel(db_session, "W Series", media_type="series", watch_completed=True)
        db_session.commit()

        count = repo.count_watched_matching(media_types=["movie"])
        assert count == 1

    def test_respects_provider_filter(self, db_session, repo):
        make_channel(db_session, "P1W", media_type="movie", watch_completed=True, provider_id="pA")
        make_channel(db_session, "P2W", media_type="movie", watch_completed=True, provider_id="pB")
        db_session.commit()

        count = repo.count_watched_matching(provider_id="pA")
        assert count == 1

    def test_respects_search_query(self, db_session, repo):
        make_channel(db_session, "Action Hero", media_type="movie", watch_completed=True)
        make_channel(db_session, "Comedy Night", media_type="movie", watch_completed=True)
        db_session.commit()

        count = repo.count_watched_matching(search_query="Action")
        assert count == 1

    def test_count_reflects_filter_changes(self, db_session, repo):
        """count_watched_matching with excluded providers skips those channels."""
        make_channel(db_session, "Excluded", media_type="movie", watch_completed=True, provider_id="old")
        make_channel(db_session, "Visible", media_type="movie", watch_completed=True, provider_id="active")
        db_session.commit()

        count = repo.count_watched_matching(excluded_provider_ids=["old"])
        assert count == 1


# ── Part 3 — ChannelListModel targeted updates ───────────────────────────────

class TestModelTargetedUpdate:
    """update_watch_completed() and remove_channel() update rows without full reload."""

    @pytest.fixture
    def model(self):
        """Minimal ChannelListModel — no QApplication needed for data-layer ops."""
        from unittest.mock import patch
        # Patch Qt signals/slots so we can instantiate without a QApplication
        with patch("metatv.gui.channel_list_model.QAbstractListModel.__init__", return_value=None), \
             patch("metatv.gui.channel_list_model.QAbstractListModel.beginResetModel", return_value=None), \
             patch("metatv.gui.channel_list_model.QAbstractListModel.endResetModel", return_value=None), \
             patch("metatv.gui.channel_list_model.QAbstractListModel.beginRemoveRows", return_value=None), \
             patch("metatv.gui.channel_list_model.QAbstractListModel.endRemoveRows", return_value=None), \
             patch("metatv.gui.channel_list_model.QAbstractListModel.dataChanged"), \
             patch("metatv.gui.channel_list_model.QAbstractListModel.createIndex", return_value=None):
            from metatv.gui.channel_list_model import ChannelListModel
            m = ChannelListModel.__new__(ChannelListModel)
            m._channels = []
            m._has_more = False
            m._fetching = False
            m._query_params = {}
            m._current_offset = 0
            m._provider_icon_map = {}
            m._show_provider_icon = False
            m._favorite_icon = "★"
            m._unfavorite_icon = "☆"
            m._get_media_type_icon = None
            m._partial_threshold_pct = 10
            m._generation = 0
            m._id_to_index = {}
            # Group-by-type state (mirrors ChannelListModel.__init__); flat by default.
            m._grouped = False
            m._collapsed_sections = set()
            m._buckets = {}
            m._bucket_pos = {}
            yield m

    def test_update_watch_completed_sets_dto_fields(self, model):
        """update_watch_completed patches the DTO in-place without resetting the model."""
        cid = str(uuid.uuid4())
        model._channels = [_dto(cid, watch_completed=False, watch_percent=0)]
        model._rebuild_index()
        initial_gen = model._generation

        # Apply targeted update
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(model, "dataChanged", _NoOpSignal(), raising=False)
            mp.setattr(model, "createIndex", lambda *_: None, raising=False)
            model.update_watch_completed(cid, watch_completed=True, watch_percent=100, watch_progress=0)

        assert model._channels[0].watch_completed is True
        assert model._channels[0].watch_percent == 100
        # Generation must NOT increment (no full reset)
        assert model._generation == initial_gen

    def test_update_watch_completed_unknown_id_is_noop(self, model):
        """update_watch_completed with an unknown channel_id does nothing."""
        model._channels = [_dto("known_id")]
        model._rebuild_index()
        gen_before = model._generation

        model.update_watch_completed("unknown_id", watch_completed=True)
        assert model._generation == gen_before
        assert model._channels[0].watch_completed is False

    def test_remove_channel_deletes_row(self, model):
        """remove_channel removes the row and rebuilds the index."""
        cid1 = str(uuid.uuid4())
        cid2 = str(uuid.uuid4())
        model._channels = [_dto(cid1), _dto(cid2)]
        model._rebuild_index()
        initial_gen = model._generation

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(model, "beginRemoveRows", lambda *_: None, raising=False)
            mp.setattr(model, "endRemoveRows", lambda: None, raising=False)
            model.remove_channel(cid1)

        assert len(model._channels) == 1
        assert model._channels[0].id == cid2
        # row-remove does NOT reset model (generation unchanged)
        assert model._generation == initial_gen
        # Index rebuilt: cid1 gone, cid2 at 0
        assert cid1 not in model._id_to_index
        assert model._id_to_index[cid2] == 0

    def test_remove_channel_unknown_id_is_noop(self, model):
        """remove_channel with an unknown id does nothing."""
        cid = str(uuid.uuid4())
        model._channels = [_dto(cid)]
        model._rebuild_index()

        model.remove_channel("ghost_id")
        assert len(model._channels) == 1


class _NoOpSignal:
    """Stand-in for Qt signals in tests that don't run a QApplication."""
    def emit(self, *args, **kwargs):
        pass
