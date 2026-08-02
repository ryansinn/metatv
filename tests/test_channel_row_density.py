"""Behavioral tests for the channel-list row density feature (wave6/comfy-row).

Covers:
1. ``ChannelListModel`` exposes structured per-field roles for a channel row
   (TITLE_ROLE, YEAR_ROLE, ...) and leaves them unset (None) on a header row.
2. ``ChannelRowDelegate.sizeHint`` differs between densities and is stable
   (deterministic) for repeated calls at the same density; a grouped header
   row's height is unaffected by density (still single-line).
3. The pure rect-math helpers that back the paint layout: ``right_aligned_rects``
   (compact's right-hand group sits flush against the row's right edge) and
   ``stacked_line_rects`` (comfy allocates two distinct, non-overlapping lines).
4. The density setting round-trips through ``Config`` (real pydantic Config on
   an isolated tmp home — see ``_isolate_user_config`` in conftest.py) and
   through the settings-dialog load/save helpers.
5. Applying a new density (the ``MainWindow`` seam wired to
   ``SettingsDialog.settings_applied``) updates the delegate's density and
   triggers a model ``layoutChanged`` so the view relayouts row heights.

Every test executes the changed path and asserts an outcome that would break
if the density logic regressed — no shape/substring-only coverage.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QComboBox, QStyleOptionViewItem

from metatv.core.config import Config
from metatv.core.repositories.dtos import ChannelListDTO
from metatv.gui.channel_list_delegate import (
    DENSITY_COMFY,
    DENSITY_COMPACT,
    ChannelRowDelegate,
    right_aligned_rects,
    stacked_line_rects,
)
from metatv.gui.channel_list_model import (
    CATEGORY_ROLE,
    LANGUAGE_ROLE,
    QUALITY_TOKEN_ROLE,
    RATING_ROLE,
    ROW_KIND_ROLE,
    TITLE_ROLE,
    YEAR_ROLE,
    ChannelListModel,
)
from metatv.gui.main_window import MainWindow
from metatv.gui.settings_dialog import _load_channel_density, _save_channel_density


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
        is_favorite=True,
        category="Action",
        quality=None,
        detected_prefix=None,
        detected_region="US",
        detected_quality="HD",
        detected_year="2021",
        detected_title="A Great Movie",
        user_rating=1,
    )
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

    seen = []
    model.layoutChanged.connect(lambda: seen.append(True))

    _APPLY_DENSITY(fake_self)

    assert delegate.density == DENSITY_COMFY
    assert seen == [True]
