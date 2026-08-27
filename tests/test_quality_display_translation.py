"""Behavioral tests for the quality-token DISPLAY translation (HEVC / RAW).

``HEVC`` and ``RAW`` are codec / bitrate descriptors a provider stamps on a channel
name — neither is a viewer-facing picture-quality tier, and a viewer has no way to
rank them against 4K/HD/SD.  The fix adds one display map in the lookup-table home
(``metatv/core/channel_name_utils.py``) and routes every render site through it:

* ``RAW``  renders as "Uncompressed" (the stored token stays ``RAW``).
* ``HEVC`` keeps its short form but gains a tooltip saying it is a codec.
* Everything else (4K, FHD, HD, SD…) renders unchanged.

The DB value is NEVER renamed — these tests pin that identity (filter keys, stored
``detected_quality``) survives the translation, which is the thing that would break
if someone "fixed" this by rewriting the token at ingestion.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------------------
# The core lookup (single source of truth)
# ---------------------------------------------------------------------------

def test_raw_translates_to_uncompressed():
    from metatv.core.channel_name_utils import quality_display
    assert quality_display("RAW") == "Uncompressed"
    assert quality_display("raw") == "Uncompressed"   # case-insensitive lookup


def test_plain_tiers_pass_through_unchanged():
    from metatv.core.channel_name_utils import quality_display
    for tier in ("4K", "UHD", "FHD", "HD", "SD", "HQ", "LQ", "CAM"):
        assert quality_display(tier) == tier


def test_hevc_keeps_short_form_but_is_explained_by_tooltip():
    """HEVC stays "HEVC" (that IS its recognizable name) — the tooltip does the work."""
    from metatv.core.channel_name_utils import quality_display, quality_tooltip
    assert quality_display("HEVC") == "HEVC"
    tip = quality_tooltip("HEVC")
    assert "codec" in tip.lower()
    assert "not a picture-quality tier" in tip.lower()


def test_raw_tooltip_explains_uncompressed():
    from metatv.core.channel_name_utils import quality_tooltip
    tip = quality_tooltip("RAW")
    assert "uncompressed" in tip.lower()
    assert "not a resolution tier" in tip.lower()


def test_unknown_token_falls_back_to_generic_quality_tooltip():
    from metatv.core.channel_name_utils import quality_tooltip
    assert quality_tooltip("4K") == "4K quality"
    assert quality_tooltip("") == ""


def test_mixed_case_group_name_is_not_uppercased():
    """Filter GROUP names share the namespace — they must survive intact.

    ``quality_display`` deliberately does not uppercase unknown values, or the
    "CAM / Pre-release" filter group would render as "CAM / PRE-RELEASE".
    """
    from metatv.core.channel_name_utils import quality_display
    assert quality_display("CAM / Pre-release") == "CAM / Pre-release"
    assert quality_display("4K / UHD") == "4K / UHD"


def test_display_map_never_renames_the_stored_token():
    """Identity guard: the token set the DB/parser uses is untouched by display."""
    from metatv.core.channel_name_utils import QUALITY_TOKENS, quality_display
    assert "RAW" in QUALITY_TOKENS and "HEVC" in QUALITY_TOKENS
    # Translating is a pure read — the source set still holds the raw tokens.
    _ = [quality_display(t) for t in QUALITY_TOKENS]
    assert "RAW" in QUALITY_TOKENS and "HEVC" in QUALITY_TOKENS


# ---------------------------------------------------------------------------
# Render sites
# ---------------------------------------------------------------------------

def test_quality_badge_chip_renders_translated_label_and_tooltip(qapp):
    """badge_utils.make_quality_chip — the shared chip factory (watchlist rows)."""
    from metatv.gui.badge_utils import make_quality_chip

    raw_chip = make_quality_chip("RAW")
    assert raw_chip.text() == "Uncompressed"
    assert "uncompressed" in raw_chip.toolTip().lower()

    hevc_chip = make_quality_chip("hevc")
    assert hevc_chip.text() == "HEVC"
    assert "codec" in hevc_chip.toolTip().lower()

    # A plain tier is still uppercased and unchanged
    assert make_quality_chip("4k").text() == "4K"


def test_sidebar_meta_line_renders_translated_quality(qapp):
    """The sidebar rows — Favorites / Queue / History / Recommended.

    V3 moved the quality out of a chip and into the row's meta line. The
    translation had to move with it: a meta line reading "RAW" tells the viewer
    the opposite of what the token means.
    """
    from metatv.gui.chip_row import quality_word, row_meta_label, sidebar_meta_line, build_chip_row

    assert quality_word("RAW") == "Uncompressed"
    assert quality_word("4k") == "4K"
    assert quality_word("") == ""

    from metatv.gui.chip_row import DENSITY_COMFORTABLE
    row = build_chip_row(
        title="Some Movie",
        meta=sidebar_meta_line("Movie", "1999", quality_word("RAW")),
        density=DENSITY_COMFORTABLE,
    )
    text = row_meta_label(row).text()
    assert "Uncompressed" in text, f"expected translated quality, got {text!r}"
    assert "RAW" not in text


@pytest.mark.parametrize("module", ["favorites", "queue", "recommended"])
def test_every_sidebar_section_translates_its_quality(module):
    """Wired at the call sites, not merely available — three sections, one helper."""
    import pathlib

    src = pathlib.Path(f"metatv/gui/sidebar/{module}.py").read_text()
    assert "quality_word(" in src, (
        f"{module}.py puts a raw quality token on the meta line"
    )
    assert "detected_quality,\n" not in src


def test_details_pane_quality_chip_translates_but_channel_keeps_token(qapp):
    """Details-pane title-bar chip shows the label; the channel field is untouched."""
    from metatv.core.config import Config
    from metatv.gui.details_sections import _MetadataSection

    ch = MagicMock()
    ch.id = "c1"
    ch.name = "Some Movie RAW"
    ch.media_type = "movie"
    ch.is_adult = False
    ch.detected_title = "Some Movie"
    ch.detected_year = None
    ch.detected_prefix = None
    ch.detected_quality = "RAW"
    ch.detected_region = None
    ch.provider_id = None

    section = _MetadataSection(Config())
    section.load_basic(ch)

    assert section._quality_chip.text() == "Uncompressed"
    assert "uncompressed" in section._quality_chip.toolTip().lower()
    # The stored field is identity — never rewritten for display
    assert ch.detected_quality == "RAW"


def test_details_pane_hevc_chip_carries_codec_tooltip(qapp):
    from metatv.core.config import Config
    from metatv.gui.details_sections import _MetadataSection

    ch = MagicMock()
    ch.id = "c2"
    ch.name = "Some Movie HEVC"
    ch.media_type = "movie"
    ch.is_adult = False
    ch.detected_title = "Some Movie"
    ch.detected_year = None
    ch.detected_prefix = None
    ch.detected_quality = "HEVC"
    ch.detected_region = None
    ch.provider_id = None

    section = _MetadataSection(Config())
    section.load_basic(ch)

    assert section._quality_chip.text() == "HEVC"
    assert "codec" in section._quality_chip.toolTip().lower()


def _list_dto(**overrides):
    """Build a ChannelListDTO with only the fields it actually declares."""
    import dataclasses
    from metatv.core.repositories.dtos import ChannelListDTO

    base = {
        "id": "c1", "name": "Some Movie RAW", "media_type": "movie",
        "provider_id": "p1", "is_favorite": False, "category": None, "quality": None,
        "detected_prefix": None, "detected_region": None, "detected_year": None,
        "detected_title": "Some Movie", "detected_quality": "RAW",
    }
    base.update(overrides)
    fields = {f.name for f in dataclasses.fields(ChannelListDTO)}
    return ChannelListDTO(**{k: v for k, v in base.items() if k in fields})


def test_channel_list_row_renders_translated_quality(qapp):
    """The channel-list row text ("· RAW") is a render site too."""
    from metatv.gui.channel_list_model import ChannelListModel

    model = ChannelListModel()
    text = model._compose_display_text(_list_dto())
    assert "Uncompressed" in text
    assert "· RAW" not in text


def test_channel_list_row_leaves_plain_tier_alone(qapp):
    from metatv.gui.channel_list_model import ChannelListModel

    model = ChannelListModel()
    text = model._compose_display_text(_list_dto(detected_quality="4K"))
    assert "· 4K" in text


def test_filter_panel_quality_chip_label_translates_but_key_does_not(qapp):
    """Filter chips show "Uncompressed"; the selectable KEY stays "RAW".

    This is the identity guard for the filter axis — translating the key would
    silently break every saved filter/recipe that stores the group name.
    """
    from PyQt6.QtWidgets import QLabel
    from metatv.core.config import Config
    from metatv.gui.filter_panel import FilterPanel

    panel = FilterPanel(Config())
    panel.update_data({"quality": {"RAW": 12, "4K / UHD": 30, "CAM / Pre-release": 3}})

    sec = panel._quality_sec
    labels = {lbl.text() for row in sec._rows for lbl in row.findChildren(QLabel)}

    assert "Uncompressed" in labels, f"expected translated label, got: {sorted(labels)}"
    assert "RAW" not in labels, "the misleading raw token must not reach the chip"
    assert "CAM / Pre-release" in labels, "mixed-case group name must not be uppercased"

    # The key the filter actually selects on is the UNtranslated group name —
    # translating it would break every saved filter/recipe storing that name.
    assert "RAW" in set(sec.get_all_keys())


# ---------------------------------------------------------------------------
# On Now quality column — the surface named in the bug report
# ---------------------------------------------------------------------------

def _on_now_host():
    """Minimal namespace for calling EpgView._render_on_now (mirrors the
    harness in tests/test_epg_on_now_display.py)."""
    from PyQt6.QtWidgets import QTreeWidget, QLabel
    from metatv.gui.epg_view import EpgView
    from metatv.gui.epg_widgets import _ProgressBarDelegate

    cfg = SimpleNamespace(
        epg_category_overrides={},
        epg_watchlist_patterns=[],
        epg_filter_state={},
        epg_hidden_prefixes=[],
        global_filter_excluded_categories=[],
        global_filter_excluded_prefixes=[],
        global_filter_paused=False,
        category_name_overrides={},
        close_icon="×",
        hide_icon="🚫",
        save=MagicMock(),
    )
    host = SimpleNamespace()
    host.config = cfg
    tree = QTreeWidget()
    tree.setColumnCount(6)
    tree.setHeaderLabels(["", "Channel", "Quality", "Show", "Progress", "Hide"])
    tree.setItemDelegateForColumn(4, _ProgressBarDelegate(tree))
    host.on_now_list = tree
    host.on_now_stats = QLabel("")
    host.status_message = MagicMock()
    host.on_now_prefix_dropdown = MagicMock()
    host._channel_name_map = {}
    host._channel_quality_map = {}
    host._channel_prefix_map = {}
    host._channel_title_map = {}
    host._channel_region_map = {}
    host._on_now_excluded_ct_ids = set()
    host._render_on_now = lambda progs: EpgView._render_on_now(host, progs)
    host._on_now_hidden_prefixes = EpgView._on_now_hidden_prefixes
    host._apply_on_now_filters = lambda: None
    # Slice 3C: the tree is grouped by prefix — this file only cares about the
    # Quality column on a rendered row, not group/type-dropdown behavior (that's
    # covered in tests/test_epg_on_now_display.py), so stub the type-dropdown sync.
    host._sync_on_now_type_dropdown = lambda type_counts: None
    host._update_filler_btn_label = lambda: None
    return host


class _FakeProgram:
    def __init__(self, channel_db_id="ch1", title="Test Show"):
        from datetime import datetime, timedelta
        _now = datetime(2026, 6, 19, 20, 0, 0)
        self.channel_db_id = channel_db_id
        self.channel_epg_id = "epg1"
        self.title = title
        self.start_time = _now - timedelta(minutes=30)
        self.stop_time = _now + timedelta(minutes=30)
        self.is_live = False
        self.is_new = False


def test_on_now_quality_column_shows_translated_label(qapp):
    host = _on_now_host()
    host._channel_title_map["ch1"] = "Movie Channel"
    host._channel_name_map["ch1"] = "Movie Channel"
    host._channel_quality_map["ch1"] = "RAW"

    host._render_on_now([_FakeProgram()])

    # Slice 3C: top-level rows are now prefix-group headers; the programme row is
    # the first (only) child.
    item = host.on_now_list.topLevelItem(0).child(0)
    assert item.text(2) == "Uncompressed"
    assert "uncompressed" in item.toolTip(2).lower()
    # The map (the view's keying data) still holds the stored token
    assert host._channel_quality_map["ch1"] == "RAW"


def test_on_now_hevc_column_keeps_short_form_with_tooltip(qapp):
    host = _on_now_host()
    host._channel_title_map["ch1"] = "Movie Channel"
    host._channel_name_map["ch1"] = "Movie Channel"
    host._channel_quality_map["ch1"] = "HEVC"

    host._render_on_now([_FakeProgram()])

    item = host.on_now_list.topLevelItem(0).child(0)
    assert item.text(2) == "HEVC"
    assert "codec" in item.toolTip(2).lower()


def test_on_now_plain_tier_is_unchanged_and_untooltipped_beyond_generic(qapp):
    host = _on_now_host()
    host._channel_title_map["ch1"] = "Movie Channel"
    host._channel_name_map["ch1"] = "Movie Channel"
    host._channel_quality_map["ch1"] = "4K"

    host._render_on_now([_FakeProgram()])

    item = host.on_now_list.topLevelItem(0).child(0)
    assert item.text(2) == "4K"
    assert item.toolTip(2) == "4K quality"


# ---------------------------------------------------------------------------
# quality_tier_rank — the single canonical sortable-rank lookup (Wave 3 slice
# 3A: used by the EPG watchlist to rank channels within a match group).
# ---------------------------------------------------------------------------

def test_quality_tier_rank_orders_resolution_tiers_descending():
    from metatv.core.channel_name_utils import quality_tier_rank

    assert quality_tier_rank("8K") > quality_tier_rank("4K")
    assert quality_tier_rank("4K") == quality_tier_rank("UHD")  # 4K/UHD synonyms
    assert quality_tier_rank("4K") > quality_tier_rank("FHD")
    assert quality_tier_rank("FHD") > quality_tier_rank("HD")
    assert quality_tier_rank("HD") > quality_tier_rank("SD")
    assert quality_tier_rank("SD") > quality_tier_rank("LQ")


def test_quality_tier_rank_is_case_insensitive():
    from metatv.core.channel_name_utils import quality_tier_rank
    assert quality_tier_rank("hd") == quality_tier_rank("HD")
    assert quality_tier_rank(" 4k ") == quality_tier_rank("4K")


def test_quality_tier_rank_unknown_and_missing_fall_to_default_between_sd_and_hd():
    from metatv.core.channel_name_utils import quality_tier_rank

    default = quality_tier_rank(None)
    assert default == quality_tier_rank("")
    assert default == quality_tier_rank("HEVC")   # codec, not a resolution tier
    assert default == quality_tier_rank("RAW")    # bitrate descriptor, not a tier
    assert quality_tier_rank("HD") > default > quality_tier_rank("SD")
