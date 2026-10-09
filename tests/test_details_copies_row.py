"""Behavioral + rendered-appearance tests for "Available in" (DETAILS-3c).

The redesigned, non-collapsible "Available in" row: the copy you are on is
the first chip (selected), siblings with identical labels merge into one
"×N" chip with a picker menu, a quality tier renders as the app's one
quality badge, the source icon appears only when more than one ENABLED
source is in play, and "Filtered"/"Offline" start behind a dashed "+N …"
chip that opens into its own labelled row — remembered per-bucket, not
reset on every reload.

Also pins the absolute gate at the loader (``main_window_metadata.py``):
a sibling on a DISABLED provider never reaches the pane at all; a sibling on
an ENABLED-but-EXPIRED provider still does, flagged ``is_inactive=True``
("offline").

Per CLAUDE.md's "UI slices must assert rendered appearance" rule, chip
assertions compare against the SAME builders the production code uses
(``chip_sheet``, ``chip_row.quality_chip_style``) rather than re-deriving a
string, and are driven through the REAL ``_VersionSection``/``_bg_fetch_versions``
code paths rather than through a double.
"""

from __future__ import annotations

import concurrent.futures
from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QApplication, QMenu, QPushButton

from metatv.gui.detail_chips import chip_sheet
from metatv.gui.chip_row import quality_chip_style


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _version(cid, *, prefix=None, quality=None, provider_id=None, collection=None,
             filtered=False, inactive=False, provider_name=None):
    from metatv.gui.details_versions import ChannelVersion
    return ChannelVersion(
        channel_id=cid, name=f"V {cid}", in_queue=False,
        detected_prefix=prefix, detected_quality=quality, provider_id=provider_id,
        collection=collection, is_filtered=filtered, is_inactive=inactive,
        provider_name=provider_name,
    )


def _make_section():
    from metatv.core.config import Config
    from metatv.gui.details_versions import _VersionSection
    return _VersionSection(Config())


def _available_grid(section):
    return section._body_layout.itemAt(0).widget().layout()


def _available_key(section):
    return _available_grid(section).itemAtPosition(0, 0).widget()


def _available_flow_chips(section):
    flow = _available_grid(section).itemAtPosition(0, 1).widget()
    lay = flow.layout()
    return [lay.itemAt(i).widget() for i in range(lay.count())]


def _bucket_row(section, word):
    """(key_widget, [chips]) for an OPEN bucket's own labelled row, else None."""
    grid = _available_grid(section)
    for row in range(1, grid.rowCount()):
        key_item = grid.itemAtPosition(row, 0)
        if key_item is None or key_item.widget() is None:
            continue
        if key_item.widget().text().lower() == word:
            flow = grid.itemAtPosition(row, 1).widget()
            lay = flow.layout()
            return key_item.widget(), [lay.itemAt(i).widget() for i in range(lay.count())]
    return None


# ---------------------------------------------------------------------------
# 1. The current copy is the first chip, selected
# ---------------------------------------------------------------------------

def test_current_copy_is_first_and_selected(qapp, owned_widgets):
    section = owned_widgets.own(_make_section())
    current = _version("cur", prefix="EN")
    sibling = _version("sib", prefix="ES")

    section.load([sibling], provider_map={}, current=current)

    chips = _available_flow_chips(section)
    assert chips, "expected the current chip to render"
    assert chips[0].styleSheet() == chip_sheet("COLOR_TEXT_HI", selected=True, bold=True), (
        "the current copy's chip must use the selected+bold sheet"
    )


# ---------------------------------------------------------------------------
# 2. Identical labels merge into "label ×N"; the picker menu names collections
# ---------------------------------------------------------------------------

def test_identical_labels_merge_and_menu_lists_both_collections(qapp, monkeypatch, owned_widgets):
    section = owned_widgets.own(_make_section())
    v1 = _version("a1", prefix="EN", collection="Marvel", provider_name="TREX")
    v2 = _version("a2", prefix="EN", collection="DC", provider_name="TREX")

    section.load([v1, v2], provider_map={})

    chips = _available_flow_chips(section)
    assert len(chips) == 1, f"two identical-prefix copies should merge into one chip, got {len(chips)}"
    chip = chips[0]
    assert chip.text() == "English (EN) ×2"

    captured = {}

    def _fake_exec(self, pos=None):
        captured["texts"] = [a.text() for a in self.actions()]
        return None

    monkeypatch.setattr(QMenu, "exec", _fake_exec)
    chip.click()

    texts = captured.get("texts", [])
    assert len(texts) == 2, f"the picker menu must list both copies, got {texts!r}"
    assert any("Marvel" in t for t in texts), f"menu must name the first copy's collection: {texts!r}"
    assert any("DC" in t for t in texts), f"menu must name the second copy's collection: {texts!r}"


def test_choosing_a_menu_entry_emits_version_selected(qapp, monkeypatch, owned_widgets):
    """The other half of the merge behaviour: picking an entry switches to it."""
    section = owned_widgets.own(_make_section())
    v1 = _version("a1", prefix="EN", collection="Marvel")
    v2 = _version("a2", prefix="EN", collection="DC")
    section.load([v1, v2], provider_map={})

    chip = _available_flow_chips(section)[0]
    seen = []
    section.version_selected.connect(seen.append)

    def _fake_exec(self, pos=None):
        # Choose the SECOND action — added in version order, so this is v2/"DC".
        return self.actions()[1]

    monkeypatch.setattr(QMenu, "exec", _fake_exec)
    chip.click()

    assert seen == ["a2"], f"choosing the second menu entry must emit its channel_id, got {seen!r}"


# ---------------------------------------------------------------------------
# 3. A quality tier renders as the app's one quality badge
# ---------------------------------------------------------------------------

def test_quality_chip_gets_a_badge(qapp, owned_widgets):
    section = owned_widgets.own(_make_section())
    v = _version("a1", prefix="EN", quality="4K")

    section.load([v], provider_map={})

    chips = _available_flow_chips(section)
    assert len(chips) == 1
    badges = [w for w in chips[0].findChildren(QPushButton) if w is not chips[0]]
    assert len(badges) == 1, "the quality tier must split into exactly one nested badge"
    assert badges[0].text() == "4K"
    assert badges[0].styleSheet() == quality_chip_style("4K"), (
        "the badge must be the app's ONE quality-chip look (chip_row.quality_chip_style)"
    )


# ---------------------------------------------------------------------------
# 4. Source icon only when more than one source is ENABLED
# ---------------------------------------------------------------------------

def test_source_icon_absent_with_one_enabled_source(qapp, owned_widgets):
    section = owned_widgets.own(_make_section())
    v = _version("a1", prefix="EN", provider_id="p1")

    section.load([v], provider_map={"p1": {"icon": "🦖", "name": "TREX", "enabled": True}})

    texts = "".join(c.text() for c in _available_flow_chips(section))
    assert "🦖" not in texts, f"a single enabled source must not prefix the icon: {texts!r}"


def test_source_icon_present_with_two_enabled_sources(qapp, owned_widgets):
    section = owned_widgets.own(_make_section())
    v1 = _version("a1", prefix="EN", provider_id="p1")
    v2 = _version("a2", prefix="ES", provider_id="p2")

    section.load([v1, v2], provider_map={
        "p1": {"icon": "🦖", "name": "TREX", "enabled": True},
        "p2": {"icon": "🟡", "name": "Other", "enabled": True},
    })

    texts = "".join(c.text() for c in _available_flow_chips(section))
    assert "🦖" in texts and "🟡" in texts, (
        f"two enabled sources must each prefix their chip with their icon: {texts!r}"
    )


# ---------------------------------------------------------------------------
# 5. Filtered/Offline buckets: closed "+N …" chip, open into a labelled row
# ---------------------------------------------------------------------------

def test_filtered_bucket_closed_by_default_shows_a_dashed_summary_chip(qapp, tmp_path, owned_widgets):
    from metatv.core.config import Config
    from metatv.gui.details_versions import _VersionSection

    cfg = Config(config_dir=tmp_path)
    section = owned_widgets.own(_VersionSection(cfg))
    active = _version("a1", prefix="EN")
    filtered = [_version(f"f{i}", prefix=p, filtered=True) for i, p in enumerate(["FR", "DE", "PL"])]

    section.load([active, *filtered], provider_map={})

    row0 = _available_flow_chips(section)
    assert any(c.text() == "+3 filtered" for c in row0), (
        f"closed bucket must end the row with a '+3 filtered' chip: {[c.text() for c in row0]!r}"
    )
    assert _bucket_row(section, "filtered") is None, "no 'Filtered' row while closed"


def test_opening_the_filtered_bucket_shows_its_row_and_drops_the_summary_chip(
    qapp, tmp_path, owned_widgets,
):
    from metatv.core.config import Config
    from metatv.gui.details_versions import _VersionSection

    cfg = Config(config_dir=tmp_path)
    section = owned_widgets.own(_VersionSection(cfg))
    active = _version("a1", prefix="EN")
    filtered = [_version(f"f{i}", prefix=p, filtered=True) for i, p in enumerate(["FR", "DE", "PL"])]
    section.load([active, *filtered], provider_map={})

    summary_chip = next(c for c in _available_flow_chips(section) if c.text() == "+3 filtered")
    summary_chip.click()

    row0 = _available_flow_chips(section)
    assert not any(c.text() == "+3 filtered" for c in row0), (
        "the '+3 filtered' chip must be gone once the bucket is open"
    )
    bucket = _bucket_row(section, "filtered")
    assert bucket is not None, "opening must add a 'Filtered' labelled row"
    key, chips = bucket
    assert key.text() == "Filtered"
    assert len(chips) == 3
    assert cfg.details_pane_open_copy_buckets == ["filtered"], (
        "opening must persist into config.details_pane_open_copy_buckets"
    )


def test_clicking_the_filtered_key_folds_the_row_back(qapp, tmp_path, owned_widgets):
    from metatv.core.config import Config
    from metatv.gui.details_versions import _VersionSection

    cfg = Config(config_dir=tmp_path)
    section = owned_widgets.own(_VersionSection(cfg))
    active = _version("a1", prefix="EN")
    filtered = [_version(f"f{i}", prefix=p, filtered=True) for i, p in enumerate(["FR", "DE", "PL"])]
    section.load([active, *filtered], provider_map={})
    section._open_bucket("filtered")

    key, _chips = _bucket_row(section, "filtered")
    key.click()

    assert _bucket_row(section, "filtered") is None, "the 'Filtered' row must fold back"
    row0 = _available_flow_chips(section)
    assert any(c.text() == "+3 filtered" for c in row0), (
        "closing must restore the '+3 filtered' summary chip"
    )
    assert cfg.details_pane_open_copy_buckets == [], (
        "closing must persist the empty open-bucket list"
    )


def test_a_reload_does_not_reset_an_open_bucket_to_closed(qapp, tmp_path, owned_widgets):
    """Open/closed is a remembered PREFERENCE (config), not per-title state —
    the opposite of the old nested-CollapsibleHeader sub-section, which reset
    to collapsed on every load()."""
    from metatv.core.config import Config
    from metatv.gui.details_versions import _VersionSection

    cfg = Config(config_dir=tmp_path)
    section = owned_widgets.own(_VersionSection(cfg))
    filtered = _version("f1", prefix="FR", filtered=True)
    section.load([filtered], provider_map={})
    section._open_bucket("filtered")
    assert _bucket_row(section, "filtered") is not None

    section.load([filtered], provider_map={})

    assert _bucket_row(section, "filtered") is not None, (
        "an open bucket must survive a reload of a new title's versions"
    )


# ---------------------------------------------------------------------------
# 6. No CollapsibleHeader remains inside the section
# ---------------------------------------------------------------------------

def test_no_collapsible_header_remains_inside_the_section(qapp, owned_widgets):
    from metatv.gui.details_section_header import CollapsibleHeader

    section = owned_widgets.own(_make_section())
    active = _version("a1", prefix="EN")
    filtered = _version("f1", prefix="FR", filtered=True)
    offline = _version("o1", prefix="DE", inactive=True, provider_name="TREX")
    section.load([active, filtered, offline], provider_map={})
    section._open_bucket("filtered")
    section._open_bucket("offline")

    assert section.findChildren(CollapsibleHeader) == [], (
        "DETAILS-3c removed the section's own header AND both nested "
        "sub-sections — nothing in this widget should be a CollapsibleHeader"
    )


# ---------------------------------------------------------------------------
# 7. Loader: disabled sources never appear; enabled-but-expired is "offline"
# ---------------------------------------------------------------------------

def _loader_config():
    return SimpleNamespace(
        global_filter_paused=False,
        global_filter_excluded_categories=[],
        global_filter_excluded_prefixes=[],
        preferred_version_prefixes=[],
        preferred_version_provider_ids=[],
        preferred_version_quality=None,
    )


def _make_loader_mixin(db):
    from metatv.gui.main_window_metadata import _MetadataMixin

    emitted: list[tuple] = []
    obj = _MetadataMixin.__new__(_MetadataMixin)
    obj.db = db
    obj.config = _loader_config()
    obj._versions_loaded = SimpleNamespace(emit=lambda cid, vs: emitted.append((cid, vs)))
    obj._emitted = emitted
    return obj


def test_loader_drops_a_disabled_providers_sibling_entirely(file_db):
    from metatv.core.database import ChannelDB, ProviderDB

    with file_db.session_scope() as session:
        session.add(ProviderDB(id="p-active", name="Active", type="xtream",
                                url="http://example", is_active=True))
        session.add(ProviderDB(id="p-off", name="Off", type="xtream",
                                url="http://example", is_active=False))
        key = "dark star|movie|2017"
        session.add(ChannelDB(id="ch-main", source_id="ch-main", provider_id="p-active",
                               name="EN Dark Star (2017)", media_type="movie",
                               content_key=key, detected_prefix="EN"))
        session.add(ChannelDB(id="ch-dead", source_id="ch-dead", provider_id="p-off",
                               name="4K Dark Star (2017)", media_type="movie",
                               content_key=key, detected_prefix="4K"))

    obj = _make_loader_mixin(file_db)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(obj._bg_fetch_versions, "ch-main").result(timeout=10)

    assert obj._emitted
    _, versions = obj._emitted[0]
    ids = {v.channel_id for v in versions}
    assert "ch-dead" not in ids, "a disabled provider's sibling must never reach the emitted versions"


def test_loader_keeps_an_enabled_but_expired_siblings_as_offline(file_db):
    from datetime import datetime, timedelta

    from metatv.core.database import ChannelDB, ProviderDB

    with file_db.session_scope() as session:
        session.add(ProviderDB(id="p-active", name="Active", type="xtream",
                                url="http://example", is_active=True))
        session.add(ProviderDB(
            id="p-expired", name="Expired", type="xtream", url="http://example",
            is_active=True, account_exp_date=datetime.now() - timedelta(days=1),
        ))
        key = "dark star|movie|2017"
        session.add(ChannelDB(id="ch-main", source_id="ch-main", provider_id="p-active",
                               name="EN Dark Star (2017)", media_type="movie",
                               content_key=key, detected_prefix="EN"))
        session.add(ChannelDB(id="ch-expired", source_id="ch-expired", provider_id="p-expired",
                               name="4K Dark Star (2017)", media_type="movie",
                               content_key=key, detected_prefix="4K"))

    obj = _make_loader_mixin(file_db)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(obj._bg_fetch_versions, "ch-main").result(timeout=10)

    assert obj._emitted
    _, versions = obj._emitted[0]
    by_id = {v.channel_id: v for v in versions}
    assert "ch-expired" in by_id, "an enabled-but-expired sibling must still appear, as 'offline'"
    assert by_id["ch-expired"].is_inactive is True
