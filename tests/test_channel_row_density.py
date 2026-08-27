"""Behavioral tests for the channel-list row density feature (wave6/comfy-row
+ wave6/comfy-plus).

Covers:
1. ``ChannelListModel`` exposes structured per-field roles for a channel row
   (TITLE_ROLE, YEAR_ROLE, ..., PLOT_ROLE) and leaves them unset (None) on a
   header row.
2. ``ChannelRowDelegate.sizeHint`` differs between densities and is stable
   (deterministic) for repeated calls at the same density; a grouped header
   row's height is unaffected by density (still single-line). Comfy+ is taller
   than comfy for a row WITH plot text and IDENTICAL to comfy for a row
   WITHOUT plot (the middle line collapses — no blank-gap 3-line row).
3. The pure rect-math helpers that back the paint layout: ``right_aligned_rects``
   (compact's right-hand group sits flush against the row's right edge),
   ``stacked_line_rects`` (comfy allocates two distinct, non-overlapping lines),
   and ``stacked_line_rects_n`` (comfy+'s generalized 2-or-3-line layout).
   Comfy+'s plot line elides long text via the delegate's ``_paint_plot_line``.
4. The density setting (including the new "comfy_plus" value) round-trips
   through ``Config`` (real pydantic Config on an isolated tmp home — see
   ``_isolate_user_config`` in conftest.py) and through the settings-dialog
   load/save helpers.
5. Applying a new density (the ``MainWindow`` seam wired to
   ``SettingsDialog.settings_applied``) updates the delegate's density and
   triggers a model ``layoutChanged`` so the view relayouts row heights.
6. ``ChannelListDTO.plot`` reaches the DTO via ``ChannelRepository.get_all()``'s
   outerjoin against ``MetadataDB`` — a real ``Database`` on ``tmp_path`` (not
   ``:memory:``), one channel with metadata + one without, and proof the
   number of metadata-referencing SQL statements does NOT scale with the
   number of channel rows (the N+1 the outerjoin exists to avoid).

Every test executes the changed path and asserts an outcome that would break
if the density logic regressed — no shape/substring-only coverage.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QComboBox, QStyleOptionViewItem

from metatv.core.config import Config
from metatv.core.repositories.dtos import ChannelListDTO
from metatv.gui import theme as _theme
from metatv.gui.channel_list_delegate import (
    DENSITY_COMFY,
    DENSITY_COMFY_PLUS,
    DENSITY_COMPACT,
    ChannelRowDelegate,
    right_aligned_rects,
    stacked_line_rects,
    stacked_line_rects_n,
)
from metatv.gui.channel_list_model import (
    CATEGORY_ROLE,
    LANGUAGE_ROLE,
    PLOT_ROLE,
    QUALITY_TOKEN_ROLE,
    RATING_ROLE,
    ROW_KIND_ROLE,
    TITLE_ROLE,
    YEAR_ROLE,
    ChannelListModel,
)
from metatv.gui.main_window import MainWindow
from metatv.gui.settings_dialog import _load_channel_density, _save_channel_density
from metatv.gui.settings_dialog_tabs import _CHANNEL_DENSITY_CHOICES


@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_dto(**overrides) -> ChannelListDTO:
    base = {
        "id": str(uuid.uuid4()),
        "name": "Channel",
        "media_type": "movie",
        "provider_id": "prov1",
        "is_favorite": True,
        "category": "Action",
        "quality": None,
        "detected_prefix": None,
        "detected_region": "US",
        "detected_quality": "HD",
        "detected_year": "2021",
        "detected_title": "A Great Movie",
        "user_rating": 1,
        "plot": "A gripping tale of intrigue.",
    }
    base.update(overrides)
    return ChannelListDTO(**base)


def _flat_model(dtos) -> ChannelListModel:
    model = ChannelListModel()
    model.set_channels(
        dtos,
        provider_icon_map={},
        show_provider_icon=False,
        has_more=False,
        query_params={},
        favorite_icon="★",
        unfavorite_icon="☆",
        get_media_type_icon=lambda mt: {"movie": "🎬", "series": "📺", "live": "📡"}.get(mt, "?"),
    )
    return model


def _option(width: int = 320, height: int = 0) -> QStyleOptionViewItem:
    opt = QStyleOptionViewItem()
    opt.rect = QRect(0, 0, width, height)
    return opt


# ---------------------------------------------------------------------------
# 1. Structured roles on the model
# ---------------------------------------------------------------------------

def test_structured_roles_populated_for_channel_row(qapp):
    model = _flat_model([_make_dto()])
    idx = model.index(0)
    assert idx.data(TITLE_ROLE) == "A Great Movie"
    assert idx.data(YEAR_ROLE) == "2021"
    assert idx.data(QUALITY_TOKEN_ROLE) == "HD"
    assert idx.data(LANGUAGE_ROLE) == "US"
    assert idx.data(RATING_ROLE) == 1
    assert idx.data(CATEGORY_ROLE) == "Action"
    assert idx.data(PLOT_ROLE) == "A gripping tale of intrigue."


def test_structured_roles_plot_empty_string_when_dto_has_none(qapp):
    model = _flat_model([_make_dto(plot="")])
    idx = model.index(0)
    assert idx.data(PLOT_ROLE) == ""


def test_structured_roles_empty_on_header_row(qapp):
    model = ChannelListModel()
    model.set_grouped(True)
    model.set_channels(
        [_make_dto(media_type="movie")],
        provider_icon_map={}, show_provider_icon=False, has_more=False, query_params={},
    )
    header_idx = model.index(0)
    assert header_idx.data(ROW_KIND_ROLE) == "header"
    # Header rows never set these — data() falls through to None.
    assert header_idx.data(TITLE_ROLE) is None
    assert header_idx.data(YEAR_ROLE) is None
    assert header_idx.data(PLOT_ROLE) is None


# ---------------------------------------------------------------------------
# 2. sizeHint: differs by density, stable per density, headers unaffected
# ---------------------------------------------------------------------------

def test_sizehint_comfy_taller_than_compact_and_stable(qapp):
    model = _flat_model([_make_dto()])
    idx = model.index(0)
    delegate = ChannelRowDelegate()
    opt = _option()

    delegate.set_density(DENSITY_COMPACT)
    compact_h1 = delegate.sizeHint(opt, idx).height()
    compact_h2 = delegate.sizeHint(opt, idx).height()
    assert compact_h1 == compact_h2  # stable/deterministic per density

    delegate.set_density(DENSITY_COMFY)
    comfy_h1 = delegate.sizeHint(opt, idx).height()
    comfy_h2 = delegate.sizeHint(opt, idx).height()
    assert comfy_h1 == comfy_h2

    assert comfy_h1 > compact_h1  # two lines strictly taller than one


def test_sizehint_header_row_ignores_density(qapp):
    model = ChannelListModel()
    model.set_grouped(True)
    model.set_channels(
        [_make_dto(media_type="movie")],
        provider_icon_map={}, show_provider_icon=False, has_more=False, query_params={},
    )
    header_idx = model.index(0)
    delegate = ChannelRowDelegate()
    opt = _option()

    delegate.set_density(DENSITY_COMPACT)
    compact_header_h = delegate.sizeHint(opt, header_idx).height()
    delegate.set_density(DENSITY_COMFY)
    comfy_header_h = delegate.sizeHint(opt, header_idx).height()

    # Header rows keep their current (single-line) look regardless of density.
    assert compact_header_h == comfy_header_h


def test_set_density_falls_back_to_comfy_on_unknown_value(qapp):
    delegate = ChannelRowDelegate()
    delegate.set_density("bogus")
    assert delegate.density == DENSITY_COMFY


def test_sizehint_comfy_plus_taller_than_comfy_when_row_has_plot(qapp):
    model = _flat_model([_make_dto(plot="A gripping tale of intrigue.")])
    idx = model.index(0)
    delegate = ChannelRowDelegate()
    opt = _option()

    delegate.set_density(DENSITY_COMFY)
    comfy_h = delegate.sizeHint(opt, idx).height()

    delegate.set_density(DENSITY_COMFY_PLUS)
    comfy_plus_h = delegate.sizeHint(opt, idx).height()

    # A row WITH plot text grows a third line — strictly taller than comfy.
    assert comfy_plus_h > comfy_h


def test_sizehint_comfy_plus_equals_comfy_when_row_has_no_plot(qapp):
    model = _flat_model([_make_dto(plot="")])
    idx = model.index(0)
    delegate = ChannelRowDelegate()
    opt = _option()

    delegate.set_density(DENSITY_COMFY)
    comfy_h = delegate.sizeHint(opt, idx).height()

    delegate.set_density(DENSITY_COMFY_PLUS)
    comfy_plus_h = delegate.sizeHint(opt, idx).height()

    # No plot → comfy_plus collapses to comfy's two-line height exactly (not a
    # 3-line row with a blank gap).
    assert comfy_plus_h == comfy_h


# ---------------------------------------------------------------------------
# 3. Pure rect-math helpers (no painter/pixels)
# ---------------------------------------------------------------------------

def test_right_aligned_rects_flush_right():
    container = QRect(0, 0, 200, 24)
    rects = right_aligned_rects(container, [30, 40, 20], spacing=4)
    assert len(rects) == 3
    # The LAST cell's right edge sits flush on the container's right edge.
    assert rects[-1].right() == container.right()
    # Cells are laid out left-to-right, non-overlapping, in order.
    assert rects[0].left() < rects[1].left() < rects[2].left()
    for w_expected, r in zip([30, 40, 20], rects):
        assert r.width() == w_expected
    assert rects[0].left() >= container.left()


def test_right_aligned_rects_empty_widths_returns_empty():
    assert right_aligned_rects(QRect(0, 0, 100, 20), [], spacing=4) == []


def test_stacked_line_rects_two_distinct_nonoverlapping_lines():
    container = QRect(0, 0, 200, 40)
    line1, line2 = stacked_line_rects(container, line_height=12, gap=2)
    assert line1.height() == 12
    assert line2.height() == 12
    assert line1.top() < line2.top()
    # No vertical overlap between the two lines.
    assert line1.bottom() < line2.top()
    # Both lines stay inside the container.
    assert line1.top() >= container.top()
    assert line2.bottom() <= container.bottom()


def test_stacked_line_rects_n_three_distinct_nonoverlapping_lines():
    """Comfy+'s generalized layout: 3 lines (title, plot, badges)."""
    container = QRect(0, 0, 200, 60)
    lines = stacked_line_rects_n(container, line_height=12, gap=2, count=3)
    assert len(lines) == 3
    for r in lines:
        assert r.height() == 12
    # Strictly increasing tops, no vertical overlap between consecutive lines.
    assert lines[0].bottom() < lines[1].top() < lines[1].bottom() < lines[2].top()
    assert lines[0].top() >= container.top()
    assert lines[2].bottom() <= container.bottom()


def test_stacked_line_rects_n_matches_two_line_wrapper():
    """stacked_line_rects(...) is exactly stacked_line_rects_n(..., count=2)."""
    container = QRect(0, 0, 200, 40)
    line1, line2 = stacked_line_rects(container, line_height=12, gap=2)
    n_lines = stacked_line_rects_n(container, line_height=12, gap=2, count=2)
    assert [line1, line2] == n_lines


def test_stacked_line_rects_n_zero_count_returns_empty():
    assert stacked_line_rects_n(QRect(0, 0, 100, 20), line_height=12, gap=2, count=0) == []


def test_comfy_plus_plot_line_elides_long_text(qapp):
    """``_paint_plot_line`` elides text too wide for its rect, in the muted
    token — the actual delegate code path Comfy+'s middle line paints with."""
    delegate = ChannelRowDelegate()
    font = QFont()
    narrow_rect = QRect(0, 0, 60, 16)
    long_plot = (
        "A very long plot description that will never fit inside a "
        "sixty-pixel-wide rectangle no matter what font is used."
    )
    painter = MagicMock()

    with patch.object(delegate, "_draw_text") as mock_draw_text:
        delegate._paint_plot_line(painter, narrow_rect, long_plot, font)

    assert mock_draw_text.call_count == 1
    _painter, _rect, drawn_text, color, _font = mock_draw_text.call_args[0]
    assert drawn_text != long_plot
    assert len(drawn_text) < len(long_plot)
    assert "…" in drawn_text  # Qt's ElideRight ellipsis character
    assert color == _theme.COLOR_MUTED  # theme token, never a literal


# ---------------------------------------------------------------------------
# 4. Config round-trip
# ---------------------------------------------------------------------------

def test_channel_list_density_defaults_to_comfy():
    cfg, _ = Config.load()
    assert cfg.channel_list_density == "comfy"


def test_channel_list_density_persists_through_save_and_reload():
    cfg, _ = Config.load()
    cfg.channel_list_density = "compact"
    cfg.save()

    reloaded, _ = Config.load()
    assert reloaded.channel_list_density == "compact"


def test_channel_list_density_persists_comfy_plus_through_save_and_reload():
    cfg, _ = Config.load()
    cfg.channel_list_density = "comfy_plus"
    cfg.save()

    reloaded, _ = Config.load()
    assert reloaded.channel_list_density == "comfy_plus"


def test_settings_dialog_density_helpers_round_trip(qapp):
    combo = QComboBox()
    combo.addItem("Comfy (two lines)", "comfy")
    combo.addItem("Compact (one line)", "compact")
    cfg = SimpleNamespace(channel_list_density="compact")

    _load_channel_density(combo, cfg)
    assert combo.currentData() == "compact"

    combo.setCurrentIndex(combo.findData("comfy"))
    _save_channel_density(combo, cfg)
    assert cfg.channel_list_density == "comfy"


def test_settings_dialog_density_helpers_round_trip_comfy_plus(qapp):
    """The real ``_CHANNEL_DENSITY_CHOICES`` tuple (single source of truth for
    the Settings → Interface combo) carries the new "comfy_plus" value and it
    round-trips through the load/save helpers exactly like the other two."""
    combo = QComboBox()
    for label, value in _CHANNEL_DENSITY_CHOICES:
        combo.addItem(label, value)
    cfg = SimpleNamespace(channel_list_density="comfy")

    combo.setCurrentIndex(combo.findData("comfy_plus"))
    _save_channel_density(combo, cfg)
    assert cfg.channel_list_density == "comfy_plus"

    combo.setCurrentIndex(0)  # perturb selection before reloading
    _load_channel_density(combo, cfg)
    assert combo.currentData() == "comfy_plus"


def test_settings_dialog_density_load_unknown_falls_back_to_comfy(qapp):
    combo = QComboBox()
    combo.addItem("Comfy (two lines)", "comfy")
    combo.addItem("Compact (one line)", "compact")
    cfg = SimpleNamespace(channel_list_density="not-a-real-density")

    _load_channel_density(combo, cfg)
    assert combo.currentData() == "comfy"


# ---------------------------------------------------------------------------
# 5. Applying a density change triggers a repaint (layoutChanged)
# ---------------------------------------------------------------------------

_APPLY_DENSITY = MainWindow._apply_channel_list_density


def test_apply_channel_list_density_updates_delegate_and_emits_layout_changed(qapp):
    model = _flat_model([_make_dto()])
    delegate = ChannelRowDelegate()
    delegate.set_density(DENSITY_COMPACT)  # stale — config below says comfy
    fake_self = SimpleNamespace(
        config=SimpleNamespace(channel_list_density="comfy"),
        _channel_row_delegate=delegate,
        channel_model=model,
    )
    # The density seam also re-syncs the Style menu's ticks (see conftest).
    from tests.conftest import wire_style_menu_actions
    wire_style_menu_actions(fake_self)

    seen = []
    model.layoutChanged.connect(lambda: seen.append(True))

    _APPLY_DENSITY(fake_self)

    assert delegate.density == DENSITY_COMFY
    assert seen == [True]


# ---------------------------------------------------------------------------
# 6. Plot reaches the DTO via an outerjoin — no N+1 (Comfy+)
# ---------------------------------------------------------------------------

def test_plot_reaches_dto_via_join_without_scaling_query_count(tmp_path):
    """``ChannelRepository.get_all()`` outerjoins ``MetadataDB`` for the plot
    column in the SAME paginated query — never a per-row lookup.

    A channel WITH a metadata row gets its plot text; a channel WITHOUT one
    gets "". Proves the join by running ``get_all()`` against a small corpus
    and again after adding many more plotless channels: the number of SQL
    statements that reference the metadata table must stay the SAME (still
    exactly one join query) — NOT grow with the row count, which is exactly
    the N+1 this outerjoin exists to avoid.
    """
    from sqlalchemy import event

    from metatv.core.database import ChannelDB, Database, MetadataDB
    from metatv.core.repositories.channel import ChannelRepository
    from metatv.core.repositories.dtos import ChannelListDTO

    db = Database(f"sqlite:///{tmp_path / 'comfy_plus_join.db'}")
    db.create_tables()
    try:
        with db.session_scope() as session:
            session.add(MetadataDB(id="meta1", title="Movie One", plot="A gripping tale."))
            session.add(ChannelDB(
                id="c1", source_id="s1", provider_id="prov1", name="Chan1",
                media_type="movie", metadata_id="meta1",
            ))
            session.add(ChannelDB(
                id="c2", source_id="s2", provider_id="prov1", name="Chan2",
                media_type="movie", metadata_id=None,
            ))

        engine = db.engine
        counter = {"n": 0}

        def _count(conn, cursor, statement, *a):
            if "metadata" in statement.lower():
                counter["n"] += 1

        event.listen(engine, "before_cursor_execute", _count)
        try:
            with db.session_scope() as session:
                repo = ChannelRepository(session)
                rows = repo.get_all(limit=100)
                # ChannelListDTO.from_orm reads the join result back — the
                # actual boundary-crossing path the channel list uses.
                dtos_by_id = {
                    r.id: ChannelListDTO.from_orm(r) for r in rows
                }
        finally:
            event.remove(engine, "before_cursor_execute", _count)

        small_query_count = counter["n"]
        assert dtos_by_id["c1"].plot == "A gripping tale."
        assert dtos_by_id["c2"].plot == ""  # no metadata row → empty string

        # Add many more (plotless) channels and re-run — the join is baked
        # into ONE statement, so the count must NOT scale with row count.
        with db.session_scope() as session:
            for i in range(25):
                session.add(ChannelDB(
                    id=f"bulk{i}", source_id=f"bsrc{i}", provider_id="prov1",
                    name=f"Bulk Channel {i:02d}", media_type="movie",
                ))

        counter["n"] = 0
        event.listen(engine, "before_cursor_execute", _count)
        try:
            with db.session_scope() as session:
                repo = ChannelRepository(session)
                repo.get_all(limit=100)
        finally:
            event.remove(engine, "before_cursor_execute", _count)

        assert counter["n"] == small_query_count == 1
    finally:
        db.close()
