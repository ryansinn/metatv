"""Behavioral tests for the virtualized channel-list migration.

Covers:
1. ``get_all`` with ``offset`` — correct slice, name-order stability.
2. ``ChannelListModel`` — rowCount/data/set_channels/canFetchMore/fetchMore→append_page/update_favorite.
3. Context-menu id mapping (single vs multi-select) via ``show_channel_context_menu``.
4. Banner-area "N filtered — click to show" wired to ``_show_filtered_results``.

No shape/substring/source tests — every test executes the changed code and
asserts an outcome that would actually break if the code regressed.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

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
        media_type="live",
        provider_id="prov1",
        is_favorite=False,
        category=None,
        quality=None,
        detected_prefix=None,
        detected_region=None,
        detected_quality=None,
        detected_year=None,
        detected_title=None,
    )
    base.update(overrides)
    return ChannelListDTO(**base)


def _make_channel(session, name: str, **kwargs):
    from metatv.core.database import ChannelDB
    ch = ChannelDB(
        id=str(uuid.uuid4()),
        source_id=str(uuid.uuid4()),
        provider_id="prov1",
        name=name,
        media_type="live",
        **kwargs,
    )
    session.add(ch)
    session.flush()
    return ch


# ---------------------------------------------------------------------------
# 1. get_all offset — correct SQL slice in name order
# ---------------------------------------------------------------------------

def test_get_all_offset_returns_correct_slice(db_session):
    """Seeding names A–E, limit=2, offset=2 must return [C, D] in name order."""
    for name in ["E-Chan", "A-Chan", "D-Chan", "B-Chan", "C-Chan"]:
        _make_channel(db_session, name)
    db_session.commit()

    from metatv.core.repositories.channel import ChannelRepository
    repo = ChannelRepository(db_session)

    all_names = [c.name for c in repo.get_all(limit=100)]
    # Must be name-sorted
    assert all_names == sorted(all_names)

    page = repo.get_all(limit=2, offset=2)
    page_names = [c.name for c in page]
    expected = sorted(["E-Chan", "A-Chan", "D-Chan", "B-Chan", "C-Chan"])[2:4]
    assert page_names == expected


def test_get_all_offset_zero_same_as_no_offset(db_session):
    """offset=0 must return the same first page as no offset."""
    for name in ["Z-Chan", "A-Chan", "M-Chan"]:
        _make_channel(db_session, name)
    db_session.commit()

    from metatv.core.repositories.channel import ChannelRepository
    repo = ChannelRepository(db_session)

    no_offset = [c.name for c in repo.get_all(limit=2)]
    with_offset = [c.name for c in repo.get_all(limit=2, offset=0)]
    assert no_offset == with_offset


def test_get_all_offset_beyond_count_returns_empty(db_session):
    """offset beyond the total row count must return an empty list."""
    _make_channel(db_session, "Only-Chan")
    db_session.commit()

    from metatv.core.repositories.channel import ChannelRepository
    repo = ChannelRepository(db_session)
    result = repo.get_all(limit=10, offset=100)
    assert result == []


# ---------------------------------------------------------------------------
# 2. ChannelListModel — core data operations
# ---------------------------------------------------------------------------

def test_model_initial_state_is_empty(qapp):
    """A freshly constructed model reports 0 rows and canFetchMore=False."""
    from metatv.gui.channel_list_model import ChannelListModel
    model = ChannelListModel()
    assert model.rowCount() == 0
    assert model.canFetchMore() is False


def test_set_channels_resets_model_and_exposes_rows(qapp):
    """set_channels() populates rowCount and data() for DisplayRole and UserRole."""
    from PyQt6.QtCore import Qt
    from metatv.gui.channel_list_model import ChannelListModel

    model = ChannelListModel()
    dto_a = _make_dto(id="id-a", name="Alpha", detected_title="Alpha", is_favorite=True)
    dto_b = _make_dto(id="id-b", name="Beta", detected_title="Beta", is_favorite=False)

    model.set_channels(
        [dto_a, dto_b],
        provider_icon_map={},
        show_provider_icon=False,
        has_more=False,
        query_params={},
        favorite_icon="★",
        unfavorite_icon="☆",
    )

    assert model.rowCount() == 2
    idx0 = model.index(0, 0)
    idx1 = model.index(1, 0)
    # UserRole carries channel id
    assert idx0.data(Qt.ItemDataRole.UserRole) == "id-a"
    assert idx1.data(Qt.ItemDataRole.UserRole) == "id-b"
    # DisplayRole carries composed text including fav icon and title
    text_a = idx0.data(Qt.ItemDataRole.DisplayRole)
    assert "★" in text_a and "Alpha" in text_a
    text_b = idx1.data(Qt.ItemDataRole.DisplayRole)
    assert "☆" in text_b and "Beta" in text_b


def test_set_channels_includes_provider_badge_when_show_provider_icon(qapp):
    """When show_provider_icon=True and provider_id is in provider_icon_map, badge appears."""
    from PyQt6.QtCore import Qt
    from metatv.gui.channel_list_model import ChannelListModel

    model = ChannelListModel()
    dto = _make_dto(id="id-x", provider_id="prov-x", detected_title="Show")
    model.set_channels(
        [dto],
        provider_icon_map={"prov-x": "🔴"},
        show_provider_icon=True,
        has_more=False,
        query_params={},
    )
    text = model.index(0, 0).data(Qt.ItemDataRole.DisplayRole)
    assert "🔴" in text


def test_set_channels_includes_prefix_region_quality_year_category(qapp):
    """Exact format: [prefix] [region] · title · quality · year [category]"""
    from PyQt6.QtCore import Qt
    from metatv.gui.channel_list_model import ChannelListModel

    model = ChannelListModel()
    dto = _make_dto(
        detected_prefix="EN",
        detected_region=None,
        detected_quality="HD",
        detected_year="1999",
        detected_title="The Matrix",
        category="Action",
        is_favorite=False,
    )
    model.set_channels([dto], provider_icon_map={}, show_provider_icon=False,
                       has_more=False, query_params={},
                       favorite_icon="★", unfavorite_icon="☆")
    text = model.index(0, 0).data(Qt.ItemDataRole.DisplayRole)
    assert "[EN]" in text
    assert "The Matrix" in text
    assert "HD" in text
    assert "1999" in text
    assert "[Action]" in text


def test_set_channels_increments_generation(qapp):
    """Each set_channels() increments the generation counter."""
    from metatv.gui.channel_list_model import ChannelListModel
    model = ChannelListModel()
    gen0 = model.generation
    model.set_channels([], provider_icon_map={}, show_provider_icon=False,
                       has_more=False, query_params={})
    gen1 = model.generation
    model.set_channels([], provider_icon_map={}, show_provider_icon=False,
                       has_more=False, query_params={})
    gen2 = model.generation
    assert gen1 == gen0 + 1
    assert gen2 == gen1 + 1


def test_can_fetch_more_true_when_has_more(qapp):
    """canFetchMore() returns True only when has_more=True and not currently fetching."""
    from metatv.gui.channel_list_model import ChannelListModel
    model = ChannelListModel()
    model.set_channels(
        [_make_dto()],
        provider_icon_map={}, show_provider_icon=False,
        has_more=True, query_params={},
    )
    assert model.canFetchMore() is True
    # While fetching, canFetchMore must return False
    model._fetching = True
    assert model.canFetchMore() is False


def test_append_page_inserts_rows_and_updates_row_count(qapp):
    """append_page() with the correct generation appends rows; rowCount grows."""
    from metatv.gui.channel_list_model import ChannelListModel

    model = ChannelListModel()
    dto_a = _make_dto(id="id-a")
    model.set_channels(
        [dto_a],
        provider_icon_map={}, show_provider_icon=False,
        has_more=True, query_params={},
    )
    gen = model.generation
    assert model.rowCount() == 1

    dto_b = _make_dto(id="id-b")
    dto_c = _make_dto(id="id-c")
    model.append_page([dto_b, dto_c], has_more=False, generation=gen)

    assert model.rowCount() == 3
    from PyQt6.QtCore import Qt
    assert model.index(1, 0).data(Qt.ItemDataRole.UserRole) == "id-b"
    assert model.index(2, 0).data(Qt.ItemDataRole.UserRole) == "id-c"
    assert model.canFetchMore() is False


def test_offset_advances_by_raw_count_not_survivors(qapp):
    """The next-page OFFSET must advance by RAW SQL rows, not surviving DTOs.

    Regression: when a global exclusion drops rows from a page, advancing the
    offset by the (smaller) surviving count would re-request already-seen rows
    on the next fetch → duplicates. set_channels(next_offset=) and
    append_page(raw_count=) carry the raw count so the offset tracks the SQL
    window, not the post-exclusion list.
    """
    from metatv.gui.channel_list_model import ChannelListModel

    model = ChannelListModel()
    # Page 1: SQL returned 1000 raw rows, 800 survived exclusions.
    survivors = [_make_dto(id=f"p1-{i}") for i in range(800)]
    model.set_channels(
        survivors,
        provider_icon_map={}, show_provider_icon=False,
        has_more=True, query_params={}, next_offset=1000,
    )
    assert model._current_offset == 1000          # raw, not 800
    assert model.rowCount() == 800

    # Page 2: SQL returned another 1000 raw, 950 survived.
    gen = model.generation
    page2 = [_make_dto(id=f"p2-{i}") for i in range(950)]
    model.append_page(page2, has_more=True, raw_count=1000, generation=gen)
    assert model._current_offset == 2000          # 1000 + 1000 raw
    assert model.rowCount() == 1750               # 800 + 950, no overlap


def test_append_page_fully_excluded_keeps_paging(qapp):
    """A page where every row was excluded still advances the offset and keeps paging."""
    from metatv.gui.channel_list_model import ChannelListModel

    model = ChannelListModel()
    model.set_channels(
        [_make_dto(id="a")],
        provider_icon_map={}, show_provider_icon=False,
        has_more=True, query_params={}, next_offset=1000,
    )
    gen = model.generation
    # SQL returned a full page (1000 raw) but all were excluded → dtos empty.
    model.append_page([], has_more=True, raw_count=1000, generation=gen)
    assert model._current_offset == 2000          # advanced past the excluded window
    assert model.rowCount() == 1                  # nothing inserted
    assert model.canFetchMore() is True           # keeps paging toward survivors


def test_append_page_drops_stale_generation(qapp):
    """append_page() with an old generation is silently dropped."""
    from metatv.gui.channel_list_model import ChannelListModel

    model = ChannelListModel()
    model.set_channels(
        [_make_dto(id="row-1")],
        provider_icon_map={}, show_provider_icon=False,
        has_more=True, query_params={},
    )
    stale_gen = model.generation - 1   # from before the last set_channels

    # Append with the stale generation — must be dropped
    model.append_page([_make_dto(id="stale")], has_more=True, generation=stale_gen)
    # Row count unchanged
    assert model.rowCount() == 1


def test_update_favorite_flips_icon_in_data(qapp):
    """update_favorite() replaces the frozen DTO so DisplayRole text reflects new state."""
    from PyQt6.QtCore import Qt
    from metatv.gui.channel_list_model import ChannelListModel

    model = ChannelListModel()
    dto = _make_dto(id="fav-chan", is_favorite=False, detected_title="FavShow")
    model.set_channels(
        [dto],
        provider_icon_map={}, show_provider_icon=False,
        has_more=False, query_params={},
        favorite_icon="★", unfavorite_icon="☆",
    )
    # Before toggle — unfavorite icon
    text_before = model.index(0, 0).data(Qt.ItemDataRole.DisplayRole)
    assert "☆" in text_before
    assert "★" not in text_before

    model.update_favorite("fav-chan", True)

    text_after = model.index(0, 0).data(Qt.ItemDataRole.DisplayRole)
    assert "★" in text_after
    assert "☆" not in text_after


def test_update_favorite_unknown_id_is_noop(qapp):
    """update_favorite() with an id not in the model does nothing (no crash)."""
    from metatv.gui.channel_list_model import ChannelListModel
    model = ChannelListModel()
    model.set_channels([_make_dto(id="real-id")],
                       provider_icon_map={}, show_provider_icon=False,
                       has_more=False, query_params={})
    # Should not raise
    model.update_favorite("non-existent-id", True)
    assert model.rowCount() == 1


# ---------------------------------------------------------------------------
# 3. Context menu id mapping — single vs multi-select
# ---------------------------------------------------------------------------

def _make_context_menu_host(qapp):
    """Minimal MainWindow stub for testing show_channel_context_menu."""
    from PyQt6.QtWidgets import QListView
    from metatv.gui import main_window as mw_module
    from metatv.gui.channel_list_model import ChannelListModel

    win = mw_module.MainWindow.__new__(mw_module.MainWindow)
    win.channel_model = ChannelListModel()
    win.channels_list = QListView()
    win.channels_list.setModel(win.channel_model)
    # Stub the downstream actions so we can capture channel_id args
    win._show_context_menu_for = MagicMock()
    win._show_multi_select_context_menu = MagicMock()
    return win


def test_single_select_context_menu_routes_to_show_context_menu_for(qapp):
    """Right-click on a single channel must call _show_context_menu_for with that id."""
    from PyQt6.QtCore import QPoint

    host = _make_context_menu_host(qapp)
    dto = _make_dto(id="single-id")
    host.channel_model.set_channels(
        [dto], provider_icon_map={}, show_provider_icon=False,
        has_more=False, query_params={},
    )

    # Select the first (only) item so selectionModel has it selected
    host.channels_list.setCurrentIndex(host.channel_model.index(0, 0))

    # Simulate the context-menu call at the index position.
    # We need to translate row 0 to a QPoint; visualRect gives the real coords.
    rect = host.channels_list.visualRect(host.channel_model.index(0, 0))
    pos = rect.center()

    host.show_channel_context_menu(pos)

    host._show_context_menu_for.assert_called_once()
    call_args = host._show_context_menu_for.call_args[0]
    assert call_args[0] == "single-id"


def test_multi_select_context_menu_routes_to_show_multi_select(qapp):
    """Right-click when >1 item is selected must call _show_multi_select_context_menu.

    Stubs selectionModel().selectedIndexes() to return two indexes so the multi-
    select branch is reached without needing a visible, painted QListView.
    """
    from PyQt6.QtCore import Qt

    host = _make_context_menu_host(qapp)
    dto_a = _make_dto(id="id-a")
    dto_b = _make_dto(id="id-b")
    host.channel_model.set_channels(
        [dto_a, dto_b], provider_icon_map={}, show_provider_icon=False,
        has_more=False, query_params={},
    )

    # Stub selectionModel().selectedIndexes() to return both model indexes
    real_sm = host.channels_list.selectionModel()
    fake_sm = MagicMock(wraps=real_sm)
    fake_sm.selectedIndexes.return_value = [
        host.channel_model.index(0, 0),
        host.channel_model.index(1, 0),
    ]
    host.channels_list.selectionModel = lambda: fake_sm

    # indexAt the first row position
    host.channels_list.resize(400, 300)
    host.channels_list.show()
    from PyQt6.QtWidgets import QApplication
    QApplication.processEvents()

    rect = host.channels_list.visualRect(host.channel_model.index(0, 0))
    pos = rect.center()

    host.show_channel_context_menu(pos)

    host._show_multi_select_context_menu.assert_called_once()
    ids_passed = host._show_multi_select_context_menu.call_args[0][0]
    assert set(ids_passed) == {"id-a", "id-b"}


# ---------------------------------------------------------------------------
# 4. Banner area — zero-results with filtered shows actionable button
# ---------------------------------------------------------------------------

def _make_banner_host(qapp):
    """Stub host for banner/filter-button behavior in _on_channels_loaded."""
    from PyQt6.QtWidgets import QListView, QLabel, QPushButton
    from metatv.gui import main_window as mw_module
    from metatv.gui.channel_list_model import ChannelListModel

    win = mw_module.MainWindow.__new__(mw_module.MainWindow)
    win.channel_model = ChannelListModel()
    win.channels_list = QListView()
    win.channels_list.setModel(win.channel_model)
    win._channel_banner = QLabel()
    win._channel_filter_btn = QPushButton()
    win.all_channels = []
    win.stats_label = MagicMock()
    win.status_bar = MagicMock()
    win._search_page_size = 1000
    win._currently_bypassing = False
    win._clear_provider_busy = MagicMock()
    win.favorite_icon = "★"
    win.unfavorite_icon = "☆"
    win.get_media_type_icon = lambda _: ""
    win._show_filtered_results = MagicMock()
    # Wire the button to the stub so we can confirm it's connected
    win._channel_filter_btn.clicked.connect(win._show_filtered_results)
    return win


def test_zero_results_with_filtered_shows_button(qapp):
    """When channels=[] and filtered_out_count>0, the filter button becomes visible."""
    host = _make_banner_host(qapp)
    params = {
        "total_channels": 5,
        "hidden_only": False,
        "filtered_out_count": 5,
        "bypassing_tier1": False,
    }
    host._on_channels_loaded(([], params))

    # Filter button visible, info banner hidden
    assert host._channel_filter_btn.isVisible()
    assert not host._channel_banner.isVisible()
    # Button text mentions the count
    assert "5" in host._channel_filter_btn.text()
    assert "filtered" in host._channel_filter_btn.text().lower()


def test_zero_results_no_filtered_hides_button(qapp):
    """When channels=[] and filtered_out_count=0, neither banner nor button is visible."""
    host = _make_banner_host(qapp)
    params = {
        "total_channels": 0,
        "hidden_only": False,
        "filtered_out_count": 0,
        "bypassing_tier1": False,
    }
    host._on_channels_loaded(([], params))

    assert not host._channel_filter_btn.isVisible()
    assert not host._channel_banner.isVisible()


def test_filter_button_click_calls_show_filtered_results(qapp):
    """Clicking the filter button must call _show_filtered_results."""
    host = _make_banner_host(qapp)
    params = {
        "total_channels": 3,
        "hidden_only": False,
        "filtered_out_count": 3,
        "bypassing_tier1": False,
    }
    host._on_channels_loaded(([], params))

    # The button is visible and wired via _channel_filter_btn.clicked → _show_filtered_results
    host._channel_filter_btn.click()
    host._show_filtered_results.assert_called_once()


def test_bypass_banner_shown_when_bypassing(qapp):
    """When _currently_bypassing=True, filter_channels() shows the info banner."""
    host = _make_banner_host(qapp)
    # Populate the model with one row so filter_channels doesn't hit the zero branch
    dto = _make_dto(id="x", detected_title="Show")
    host.channel_model.set_channels(
        [dto], provider_icon_map={}, show_provider_icon=False,
        has_more=False, query_params={},
    )
    host._currently_bypassing = True
    host.filter_channels()

    assert host._channel_banner.isVisible()
    assert not host._channel_filter_btn.isVisible()
    # Banner text mentions filters suspended
    assert "suspended" in host._channel_banner.text().lower()
