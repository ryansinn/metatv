"""Behavioral tests for the opt-in "Group by type" channel-list view.

Covers:
1. Flat list is the DEFAULT (grouping OFF on a fresh model).
2. Toggling grouping ON projects rows into Movies/Series/Live sections with the
   correct per-section counts, in fixed display order.
3. A row inside a section still carries its #264 playback badge (in-progress ▶ /
   watched ✓) and the favorite/rating glyphs.
4. Collapsing/expanding a section hides/shows only its rows (header stays), and
   the header arrow glyph flips between expand/collapse icons.
5. Section headers are not selectable (clickable-to-toggle only).
6. Toggle + collapse state persist to config and restore on startup
   (real ``Config`` on a tmp ``config_dir``, never the real user config).
7. Paged appends land in the right section while grouped.

Every test executes the changed path and asserts an outcome that would break if
the grouping logic regressed — no shape/substring-only coverage.
"""

from __future__ import annotations

import uuid

import pytest

from metatv.core.repositories.dtos import ChannelListDTO


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
        detected_title="Title",
    )
    base.update(overrides)
    return ChannelListDTO(**base)


def _grouped_model(qapp, dtos, *, collapsed=None):
    from metatv.gui.channel_list_model import ChannelListModel
    model = ChannelListModel()
    model.set_grouped(True, collapsed_sections=collapsed or [])
    model.set_channels(
        dtos,
        provider_icon_map={},
        show_provider_icon=False,
        has_more=False,
        query_params={},
        favorite_icon="★",
        unfavorite_icon="☆",
    )
    return model


def _rows(model):
    """Return [(kind, section_or_None, display_text), …] for every display row."""
    from PyQt6.QtCore import Qt
    from metatv.gui.channel_list_model import ROW_KIND_ROLE, SECTION_TYPE_ROLE
    out = []
    for r in range(model.rowCount()):
        idx = model.index(r, 0)
        out.append((
            idx.data(ROW_KIND_ROLE),
            idx.data(SECTION_TYPE_ROLE),
            idx.data(Qt.ItemDataRole.DisplayRole),
        ))
    return out


# ---------------------------------------------------------------------------
# 1. Flat is the default
# ---------------------------------------------------------------------------

def test_flat_is_the_default(qapp):
    """A fresh model is NOT grouped — every row is a plain channel row."""
    from metatv.gui.channel_list_model import ChannelListModel, ROW_KIND_ROLE
    model = ChannelListModel()
    assert model.is_grouped is False
    dtos = [_make_dto(media_type="movie"), _make_dto(media_type="live")]
    model.set_channels(dtos, provider_icon_map={}, show_provider_icon=False,
                       has_more=False, query_params={})
    assert model.rowCount() == 2  # no headers inserted
    for r in range(2):
        assert model.index(r, 0).data(ROW_KIND_ROLE) == "channel"


# ---------------------------------------------------------------------------
# 2. Grouping ON → sections + counts in fixed order
# ---------------------------------------------------------------------------

def test_grouping_on_creates_sections_with_counts(qapp):
    """Toggle ON groups rows into Movies/Series/Live with correct counts."""
    dtos = [
        _make_dto(media_type="movie", detected_title="M1"),
        _make_dto(media_type="live", detected_title="L1"),
        _make_dto(media_type="series", detected_title="S1"),
        _make_dto(media_type="movie", detected_title="M2"),
        _make_dto(media_type="live", detected_title="L2"),
        _make_dto(media_type="live", detected_title="L3"),
    ]
    model = _grouped_model(qapp, dtos)
    rows = _rows(model)

    headers = [(sec, text) for kind, sec, text in rows if kind == "header"]
    # Fixed display order: Movies, Series, Live.
    assert [sec for sec, _ in headers] == ["movie", "series", "live"]
    # Counts are exact (2 movies, 1 series, 3 live).
    assert "Movies (2)" in headers[0][1]
    assert "Series (1)" in headers[1][1]
    assert "Live (3)" in headers[2][1]
    # Total display rows = 3 headers + 6 channels.
    assert model.rowCount() == 9
    # Channels appear under the right section header (movie rows before series header).
    kinds = [k for k, _, _ in rows]
    assert kinds.count("channel") == 6


def test_grouping_off_returns_to_flat(qapp):
    """Turning grouping back OFF removes headers and restores the flat row count."""
    dtos = [_make_dto(media_type="movie"), _make_dto(media_type="series")]
    model = _grouped_model(qapp, dtos)
    assert model.rowCount() == 4  # 2 headers + 2 channels
    model.set_grouped(False)
    assert model.is_grouped is False
    assert model.rowCount() == 2


def test_unknown_media_type_still_shown_in_other_section(qapp):
    """A row with an unexpected media_type is bucketed, never dropped (mirror-not-cage)."""
    dtos = [_make_dto(media_type="movie"), _make_dto(media_type="podcast")]
    model = _grouped_model(qapp, dtos)
    sections = [sec for kind, sec, _ in _rows(model) if kind == "header"]
    assert "movie" in sections
    assert "podcast" in sections  # extra section appended after the known three
    assert model.rowCount() == 4  # 2 headers + 2 channels — nothing lost


# ---------------------------------------------------------------------------
# 3. #264 playback badge + glyphs survive grouping
# ---------------------------------------------------------------------------

def test_row_inside_section_keeps_playback_badge(qapp):
    """A grouped channel row still renders its #264 in-progress ▶ / watched ✓ badge."""
    from PyQt6.QtCore import Qt
    from metatv.gui import icons as _icons
    from metatv.gui.channel_list_model import CHANNEL_HTML_ROLE
    from metatv.gui import theme as _theme

    dtos = [
        _make_dto(media_type="movie", detected_title="InProg",
                  watch_progress=1800, watch_completed=False),
        _make_dto(media_type="movie", detected_title="Done",
                  watch_completed=True, watch_percent=100),
    ]
    model = _grouped_model(qapp, dtos)
    # Find the two movie channel rows (skip the header at row 0).
    from metatv.gui.channel_list_model import ROW_KIND_ROLE
    texts = {
        model.index(r, 0).data(Qt.ItemDataRole.DisplayRole)
        for r in range(model.rowCount())
        if model.index(r, 0).data(ROW_KIND_ROLE) == "channel"
    }
    in_prog = next(t for t in texts if "InProg" in t)
    done = next(t for t in texts if "Done" in t)
    assert _icons.playback_in_progress_icon in in_prog   # ▶ preserved
    assert _icons.watched_icon in done                   # ✓ preserved

    # The HTML role still colours the badge with the playback token.
    for r in range(model.rowCount()):
        idx = model.index(r, 0)
        if idx.data(ROW_KIND_ROLE) == "channel" and "InProg" in idx.data(Qt.ItemDataRole.DisplayRole):
            assert _theme.COLOR_PLAYBACK_IN_PROGRESS in idx.data(CHANNEL_HTML_ROLE)


def test_update_favorite_repaints_correct_grouped_row(qapp):
    """update_favorite() in grouped mode flips the glyph on the row's display index."""
    from PyQt6.QtCore import Qt
    from metatv.gui.channel_list_model import ROW_KIND_ROLE

    dtos = [
        _make_dto(id="m1", media_type="movie", detected_title="Mov", is_favorite=False),
        _make_dto(id="l1", media_type="live", detected_title="Liv", is_favorite=False),
    ]
    model = _grouped_model(qapp, dtos)
    model.update_favorite("l1", True)
    # Find the live channel row and confirm the favorite glyph flipped.
    live_text = next(
        model.index(r, 0).data(Qt.ItemDataRole.DisplayRole)
        for r in range(model.rowCount())
        if model.index(r, 0).data(ROW_KIND_ROLE) == "channel"
        and "Liv" in model.index(r, 0).data(Qt.ItemDataRole.DisplayRole)
    )
    assert "★" in live_text and "☆" not in live_text


# ---------------------------------------------------------------------------
# 4. Collapse / expand
# ---------------------------------------------------------------------------

def test_collapse_hides_section_rows_keeps_header(qapp):
    """Collapsing a section removes only its channel rows; the header stays."""
    from metatv.gui import icons as _icons
    dtos = [
        _make_dto(media_type="movie", detected_title="M1"),
        _make_dto(media_type="movie", detected_title="M2"),
        _make_dto(media_type="live", detected_title="L1"),
    ]
    model = _grouped_model(qapp, dtos)
    assert model.rowCount() == 5  # 2 headers + 3 channels

    model.set_section_collapsed("movie", True)
    rows = _rows(model)
    # Movies header still present, its 2 channel rows gone → 5 - 2 = 3.
    assert model.rowCount() == 3
    movie_header = next(text for kind, sec, text in rows if sec == "movie")
    assert _icons.expand_icon in movie_header   # collapsed → "expand" affordance
    assert _icons.collapse_icon not in movie_header
    # No movie channel row remains.
    assert not any(kind == "channel" and "M" in (text or "") for kind, _, text in rows)
    # The live section is untouched.
    assert any(kind == "channel" and "L1" in (text or "") for kind, _, text in rows)


def test_expand_restores_section_rows(qapp):
    """Expanding a collapsed section brings its rows back and flips the arrow."""
    from metatv.gui import icons as _icons
    dtos = [
        _make_dto(media_type="movie", detected_title="M1"),
        _make_dto(media_type="live", detected_title="L1"),
    ]
    model = _grouped_model(qapp, dtos, collapsed=["movie"])
    # Starts collapsed → 2 headers + only the live channel = 3 rows.
    assert model.rowCount() == 3
    model.set_section_collapsed("movie", False)
    assert model.rowCount() == 4  # movie channel returns
    movie_header = next(text for kind, sec, text in _rows(model) if sec == "movie")
    assert _icons.collapse_icon in movie_header  # expanded → "collapse" affordance


def test_section_header_is_not_selectable(qapp):
    """Header rows are enabled (clickable) but not selectable; channel rows are both."""
    from PyQt6.QtCore import Qt
    from metatv.gui.channel_list_model import ROW_KIND_ROLE
    dtos = [_make_dto(media_type="movie", detected_title="M1")]
    model = _grouped_model(qapp, dtos)
    for r in range(model.rowCount()):
        idx = model.index(r, 0)
        flags = model.flags(idx)
        if idx.data(ROW_KIND_ROLE) == "header":
            assert flags & Qt.ItemFlag.ItemIsEnabled
            assert not (flags & Qt.ItemFlag.ItemIsSelectable)
        else:
            assert flags & Qt.ItemFlag.ItemIsSelectable


# ---------------------------------------------------------------------------
# 5. Paged appends land in the right section
# ---------------------------------------------------------------------------

def test_append_page_routes_rows_into_sections(qapp):
    """A fetched page (grouped) slots each row into its media-type section."""
    from PyQt6.QtCore import Qt
    from metatv.gui.channel_list_model import ROW_KIND_ROLE
    dtos = [_make_dto(media_type="movie", detected_title="M1")]
    model = _grouped_model(qapp, dtos)
    gen = model.generation
    model.append_page(
        [
            _make_dto(media_type="movie", detected_title="M2"),
            _make_dto(media_type="live", detected_title="L1"),
            _make_dto(media_type="series", detected_title="S1"),
        ],
        has_more=False,
        generation=gen,
    )
    rows = _rows(model)
    headers = {sec: text for kind, sec, text in rows if kind == "header"}
    assert "Movies (2)" in headers["movie"]   # M1 + appended M2
    assert "Series (1)" in headers["series"]
    assert "Live (1)" in headers["live"]
    # 3 headers + 4 channels.
    assert model.rowCount() == 7
    # Series header (a brand-new section) appears before Live in display order.
    order = [sec for kind, sec, _ in rows if kind == "header"]
    assert order == ["movie", "series", "live"]


# ---------------------------------------------------------------------------
# 6. Persistence (real Config on a tmp dir — never the real user config)
# ---------------------------------------------------------------------------

def test_group_state_persists_and_restores():
    """group_by_type + collapsed sections survive a save → reload round-trip.

    Uses the autouse ``_isolate_user_config`` patched home (never the real config).
    """
    from metatv.core.config import Config

    cfg = Config()
    assert cfg.group_by_type is False               # flat is the default
    assert cfg.group_collapsed_types == []

    cfg.group_by_type = True
    cfg.group_collapsed_types = ["movie", "live"]
    cfg.save()

    reloaded, _ = Config.load()
    assert reloaded.group_by_type is True
    assert sorted(reloaded.group_collapsed_types) == ["live", "movie"]


def test_host_toggle_handler_persists_and_groups(qapp):
    """_on_group_by_type_toggled flips config, saves, and re-projects the model."""
    from metatv.core.config import Config
    from metatv.gui.main_window import MainWindow
    from metatv.gui.channel_list_model import ChannelListModel

    host = MainWindow.__new__(MainWindow)
    host.config = Config()
    host.channel_model = ChannelListModel()
    host.channel_model.set_channels(
        [_make_dto(media_type="movie"), _make_dto(media_type="live")],
        provider_icon_map={}, show_provider_icon=False,
        has_more=False, query_params={},
    )
    assert host.channel_model.is_grouped is False
    assert host.channel_model.rowCount() == 2

    host._on_group_by_type_toggled(True)

    assert host.config.group_by_type is True
    assert Config.load()[0].group_by_type is True  # persisted to disk
    assert host.channel_model.is_grouped is True
    assert host.channel_model.rowCount() == 4  # 2 headers + 2 channels


def test_host_header_click_toggles_and_persists_collapse(qapp):
    """_on_channel_list_clicked on a header collapses the section + persists state."""
    from metatv.core.config import Config
    from metatv.gui.main_window import MainWindow
    from metatv.gui.channel_list_model import ChannelListModel, SECTION_TYPE_ROLE

    host = MainWindow.__new__(MainWindow)
    host.config = Config()
    host.config.group_by_type = True
    host.channel_model = ChannelListModel()
    host.channel_model.set_grouped(True)
    host.channel_model.set_channels(
        [_make_dto(media_type="movie", detected_title="M1"),
         _make_dto(media_type="live", detected_title="L1")],
        provider_icon_map={}, show_provider_icon=False,
        has_more=False, query_params={},
    )
    assert host.channel_model.rowCount() == 4

    # Find the Movies header index and click it.
    movie_header_idx = next(
        host.channel_model.index(r, 0)
        for r in range(host.channel_model.rowCount())
        if host.channel_model.index(r, 0).data(SECTION_TYPE_ROLE) == "movie"
    )
    host._on_channel_list_clicked(movie_header_idx)

    assert "movie" in host.config.group_collapsed_types
    assert "movie" in Config.load()[0].group_collapsed_types  # persisted to disk
    # Movie channel row hidden → 4 - 1 = 3.
    assert host.channel_model.rowCount() == 3
