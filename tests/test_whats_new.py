"""Behavioral tests for the What's New feature.

Covers:
- whats_new module functions (latest_id, entries_since ordering)
- WhatsNewDialog construction and rendered content
- MainWindow._whats_new_unseen decision logic
- maybe_show_whats_new cursor-advance + idempotency
- Config.last_seen_whats_new_id default and round-trip persistence
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Module-level qapp for headless Qt widget construction
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------------------
# 1. whats_new module functions
# ---------------------------------------------------------------------------

from metatv.whats_new import WhatsNewEntry, WHATS_NEW, latest_id, entries_since


def test_latest_id_returns_max():
    """latest_id() must equal the maximum id in WHATS_NEW."""
    assert latest_id() == max(e.id for e in WHATS_NEW)


def test_entries_since_zero_returns_all_newest_first():
    """entries_since(0) returns all entries, ordered newest id first."""
    result = entries_since(0)
    assert len(result) == len(WHATS_NEW)
    # Must be descending by id
    ids = [e.id for e in result]
    assert ids == sorted(ids, reverse=True)


def test_entries_since_latest_id_returns_empty():
    """entries_since(latest_id()) returns an empty list — nothing is unseen."""
    assert entries_since(latest_id()) == []


def test_entries_since_partial_filter():
    """entries_since(2) returns only entries with id > 2."""
    result = entries_since(2)
    assert all(e.id > 2 for e in result)
    # Should not include id=1 or id=2
    ids = {e.id for e in result}
    assert 1 not in ids
    assert 2 not in ids
    # Should include anything above 2 that exists in WHATS_NEW
    expected_ids = {e.id for e in WHATS_NEW if e.id > 2}
    assert ids == expected_ids


def test_entries_since_ordering():
    """entries_since result is always sorted descending by id."""
    for cutoff in [0, 1, 2, 3]:
        result = entries_since(cutoff)
        ids = [e.id for e in result]
        assert ids == sorted(ids, reverse=True), f"cutoff={cutoff}: not descending"


def test_whats_new_entries_have_required_fields():
    """All seed entries have non-empty title, version, date, and at least one item."""
    for entry in WHATS_NEW:
        assert entry.title, f"Entry id={entry.id} missing title"
        assert entry.version, f"Entry id={entry.id} missing version"
        assert entry.date, f"Entry id={entry.id} missing date"
        assert entry.items, f"Entry id={entry.id} has no items"


def test_whats_new_ids_are_unique():
    """No two entries share the same id."""
    ids = [e.id for e in WHATS_NEW]
    assert len(ids) == len(set(ids)), "Duplicate ids found in WHATS_NEW"


# ---------------------------------------------------------------------------
# 1b. Directory-loader invariants (package restructure)
# ---------------------------------------------------------------------------

def test_whats_new_sorted_ascending_by_id():
    """WHATS_NEW is sorted ascending by id — the loader must normalise discovery order."""
    ids = [e.id for e in WHATS_NEW]
    assert ids == sorted(ids), "WHATS_NEW is not sorted ascending by id"


def test_latest_id_equals_max_across_entry_files():
    """latest_id() must equal max(e.id for e in WHATS_NEW) — order-independent."""
    expected = max(e.id for e in WHATS_NEW)
    assert latest_id() == expected


def test_entries_since_returns_correct_sorted_subset():
    """entries_since(N) returns exactly entries with id > N, sorted descending."""
    cutoff = 10
    result = entries_since(cutoff)
    expected_ids = sorted({e.id for e in WHATS_NEW if e.id > cutoff}, reverse=True)
    assert [e.id for e in result] == expected_ids


def test_load_is_order_independent(tmp_path, monkeypatch):
    """Shuffling the discovered module order must produce the same sorted result.

    Simulates the disorder that arises when pkgutil.iter_modules returns files
    in filesystem order (which varies by OS and merge sequence).
    """
    import importlib
    import pkgutil
    import random

    # Capture original module infos so we can shuffle them
    import metatv.whats_new.entries as _entries_pkg
    all_infos = [
        mi for mi in pkgutil.iter_modules(_entries_pkg.__path__)
        if not mi.name.startswith("_")
    ]

    # Load in shuffled order and collect ENTRY objects
    shuffled = all_infos[:]
    random.shuffle(shuffled)
    loaded = []
    for mi in shuffled:
        mod = importlib.import_module(f"metatv.whats_new.entries.{mi.name}")
        loaded.append(mod.ENTRY)

    # Sorting by id on the shuffled result must equal WHATS_NEW
    sorted_loaded = sorted(loaded, key=lambda e: e.id)
    assert sorted_loaded == list(WHATS_NEW), (
        "Shuffled load + sort does not match WHATS_NEW — loader is order-sensitive"
    )


def test_all_entry_ids_are_unique():
    """All entry ids are distinct — no two entry files may share the same id.

    Gaps are allowed (e.g. 1, 2, 3, 5, 8 is fine); parallel PRs that each
    claim the next sequential id used to collide.  Uniqueness is the real
    invariant: duplicate ids would cause one entry to silently shadow another
    and break the 'seen' cursor arithmetic.
    """
    ids = [e.id for e in WHATS_NEW]
    assert len(ids) == len(set(ids)), (
        f"Duplicate ids found in WHATS_NEW: "
        f"{[i for i in ids if ids.count(i) > 1]}"
    )


def test_entry_files_match_loaded_entries():
    """Every .py file in entries/ (excluding __init__) corresponds to a loaded ENTRY."""
    import pkgutil
    import metatv.whats_new.entries as _entries_pkg

    file_names = {
        mi.name
        for mi in pkgutil.iter_modules(_entries_pkg.__path__)
        if not mi.name.startswith("_")
    }
    # There must be exactly one file per entry
    assert len(file_names) == len(WHATS_NEW), (
        f"File count ({len(file_names)}) != loaded entry count ({len(WHATS_NEW)})"
    )


# ---------------------------------------------------------------------------
# 2. WhatsNewDialog construction and rendered content
# ---------------------------------------------------------------------------

from metatv.gui.whats_new_dialog import WhatsNewDialog


def test_whats_new_dialog_constructs_headlessly(qapp):
    """WhatsNewDialog can be constructed headlessly without raising."""
    entries = entries_since(0)
    dlg = WhatsNewDialog(entries)
    assert dlg is not None


def _visible_label_texts(dlg) -> str:
    """Return all QLabel texts in dlg joined by newline (helper for content assertions)."""
    from PyQt6.QtWidgets import QLabel
    return "\n".join(w.text() for w in dlg.findChildren(QLabel))


def test_whats_new_dialog_renders_entry_titles(qapp):
    """The newest entry's title appears in the dialog on construction (carousel starts at index 0)."""
    entries = entries_since(0)
    dlg = WhatsNewDialog(entries)

    combined = _visible_label_texts(dlg)
    newest = entries[0]
    assert newest.title in combined, (
        f"Newest entry title '{newest.title}' not found in any QLabel"
    )


def test_whats_new_dialog_renders_bullet_items(qapp):
    """The newest entry's bullet items appear in the dialog on construction."""
    entries = entries_since(0)
    dlg = WhatsNewDialog(entries)

    combined = _visible_label_texts(dlg)
    newest = entries[0]
    found = any(item in combined for item in newest.items)
    assert found, (
        f"No item from newest entry id={newest.id} found in any QLabel"
    )


def test_whats_new_dialog_empty_list(qapp):
    """WhatsNewDialog with an empty entry list constructs without raising."""
    dlg = WhatsNewDialog([])
    assert dlg is not None


# ---------------------------------------------------------------------------
# 2a-2. Entry-item clipping fix — expand-to-content, single outer scroller
#
# Regression coverage for the clipping bug where a card's word-wrapped title
# and bullet QLabels were laid out using Qt's naive (too-wide-assumed)
# sizeHint instead of the label's real heightForWidth at its *actual* render
# width, so the box given to the label was shorter than the wrapped text
# needed — clipping the tail — while the scroll area still stretched the
# empty remainder to fill the viewport. See ``no_width_force`` in
# metatv/gui/qt_size_utils.py (applied in
# WhatsNewDialog._build_entry_card) for the full root-cause.
# ---------------------------------------------------------------------------

from PyQt6.QtWidgets import QLabel, QScrollArea, QWIDGETSIZE_MAX


def _long_bullet_entry() -> WhatsNewEntry:
    """Synthetic entry mirroring the real long-bullet entry (the migration-
    toast row-height fix) that first exposed the clipping bug in the owner's
    screenshot — multi-sentence bullets long enough to need several wrapped
    lines at the dialog's default width."""
    return WhatsNewEntry(
        id=999999,
        version="0.10.0",
        date="2026-07-22",
        title="Migration toast no longer clips a second progress row",
        items=(
            "The \"Migration in progress\" toast now grows to fit every running "
            "migration. Previously the panel kept its one-row height even when a "
            "second migration started — both rows got squeezed into that height, "
            "with the labels clipped to about half their text and the second "
            "row's bar squeezed against the frame edge. This first became visible "
            "when two migrations ran back-to-back on launch (detected_title_reparse "
            "v5 + tag_backfill v8), but the underlying sizing bug was pre-existing "
            "and would have hit any future multi-migration launch.",
            "The panel now measures its own content directly instead of trusting "
            "a nested layout's size hint, so it reliably grows one full row per "
            "concurrent migration (and stays put once tasks are running — the "
            "one-row case already worked correctly).",
        ),
    )


def _settle(app, cycles: int = 15) -> None:
    """Pump the event loop so pending resize/layout passes converge."""
    for _ in range(cycles):
        app.processEvents()


def _item_wrap_labels(dlg) -> list[QLabel]:
    """Return every word-wrapped ``QLabel`` (title + bullets) in the currently
    shown card — the widgets the clipping bug hit."""
    card = dlg._card_layout.itemAt(0).widget()
    layout = card.layout()
    labels = []
    for i in range(layout.count()):
        w = layout.itemAt(i).widget()
        if isinstance(w, QLabel) and w.wordWrap():
            labels.append(w)
    return labels


def test_long_entry_body_not_clipped(qapp):
    """Every wrapped item widget's actual height must be >= its own
    heightForWidth at the width it was actually given — never less, which is
    exactly what clipping looked like (the layout gave the label a shorter
    box than the wrapped text needs at that width)."""
    entry = _long_bullet_entry()
    dlg = WhatsNewDialog([entry])
    dlg.resize(540, 300)  # smaller than the full content needs — forces real scrolling
    dlg.show()
    _settle(qapp)

    labels = _item_wrap_labels(dlg)
    assert len(labels) == 3, "Expected title + 2 word-wrapped bullet QLabels"
    for label in labels:
        needed = label.heightForWidth(label.width())
        assert label.height() >= needed, (
            f"Label clipped: height={label.height()} needed={needed} "
            f"text={label.text()[:60]!r}"
        )


def test_no_per_item_scroll_area_or_capped_height(qapp):
    """No item widget may carry its own QScrollArea or a capped maximumHeight
    — the outer dialog scroll area is the only scrollable surface, and every
    item must be free to grow to whatever height its content needs."""
    entry = _long_bullet_entry()
    dlg = WhatsNewDialog([entry])
    dlg.show()
    _settle(qapp)

    labels = _item_wrap_labels(dlg)
    assert labels
    for label in labels:
        assert label.maximumHeight() == QWIDGETSIZE_MAX, (
            f"Item label has a capped maximumHeight={label.maximumHeight()}"
        )
        assert label.findChildren(QScrollArea) == [], "Item widget has a nested scroll area"


def test_outer_scroll_area_is_the_only_vertical_scroller(qapp):
    """Exactly one QScrollArea exists in the whole dialog, and it never shows
    a horizontal scrollbar — the single scrollable surface for every entry's
    full content, with no horizontal scrolling anywhere."""
    entries = [_long_bullet_entry()]
    dlg = WhatsNewDialog(entries)
    dlg.resize(540, 260)
    dlg.show()
    _settle(qapp)

    scroll_areas = dlg.findChildren(QScrollArea)
    assert len(scroll_areas) == 1, (
        f"Expected exactly one QScrollArea (the outer dialog body), found {len(scroll_areas)}"
    )
    from PyQt6.QtCore import Qt as _Qt

    scroll = scroll_areas[0]
    assert scroll.horizontalScrollBarPolicy() == _Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert scroll.horizontalScrollBar().maximum() == 0, "Horizontal scrolling appeared"


def test_real_whats_new_entries_render_without_clipping(qapp):
    """Every real WHATS_NEW entry (not just the synthetic long-bullet one)
    renders without clipping as the carousel steps through all of them —
    the fix must hold for actual shipped changelog content, not just the
    synthetic repro."""
    entries = sorted(WHATS_NEW, key=lambda e: e.id, reverse=True)
    if not entries:
        pytest.skip("No WHATS_NEW entries to check")
    dlg = WhatsNewDialog(entries)
    dlg.resize(540, 260)  # small enough that at least some entries must scroll
    dlg.show()
    _settle(qapp)

    for _ in range(len(entries)):
        for label in _item_wrap_labels(dlg):
            needed = label.heightForWidth(label.width())
            assert label.height() >= needed, (
                f"Clipped at entry idx={dlg._index} (id={entries[dlg._index].id}): "
                f"height={label.height()} needed={needed}"
            )
        if dlg._btn_older.isEnabled():
            dlg._go_older()
            _settle(qapp, cycles=8)
        else:
            break


# ---------------------------------------------------------------------------
# 2b. Carousel behavioral tests
# ---------------------------------------------------------------------------

def _make_entries(n: int) -> list[WhatsNewEntry]:
    """Return n synthetic entries, newest-first (highest id first)."""
    return [
        WhatsNewEntry(
            id=n - i,
            version="0.1.0",
            date="2026-06-01",
            title=f"Release {n - i}",
            items=(f"Item A for release {n - i}", f"Item B for release {n - i}"),
        )
        for i in range(n)
    ]


def test_carousel_starts_at_newest(qapp):
    """On construction the dialog shows the newest (index-0) entry's title."""
    entries = _make_entries(3)
    dlg = WhatsNewDialog(entries)

    combined = _visible_label_texts(dlg)
    assert entries[0].title in combined, "Newest entry title not shown on open"


def test_carousel_position_indicator_initial(qapp):
    """Position indicator reads '1 / N' after construction with N entries."""
    n = 4
    entries = _make_entries(n)
    dlg = WhatsNewDialog(entries)

    assert dlg._pos_label.text() == f"1 / {n}"


def test_carousel_newer_arrow_disabled_at_start(qapp):
    """The 'Newer' (left) arrow is disabled when the newest entry is shown."""
    entries = _make_entries(3)
    dlg = WhatsNewDialog(entries)

    assert not dlg._btn_newer.isEnabled(), "'Newer' arrow should be disabled at index 0"


def test_carousel_older_arrow_enabled_at_start(qapp):
    """The 'Older' (right) arrow is enabled when there are older entries."""
    entries = _make_entries(3)
    dlg = WhatsNewDialog(entries)

    assert dlg._btn_older.isEnabled(), "'Older' arrow should be enabled at index 0 with 3 entries"


def test_carousel_navigate_to_older(qapp):
    """Clicking the 'Older' arrow advances to the next-older entry and updates indicator."""
    entries = _make_entries(3)
    dlg = WhatsNewDialog(entries)

    # Navigate to the second entry (index 1 = one step older)
    dlg._btn_older.click()

    combined = _visible_label_texts(dlg)
    assert entries[1].title in combined, "Second entry title not shown after one step back"
    assert dlg._pos_label.text() == "2 / 3"
    assert dlg._btn_newer.isEnabled(), "'Newer' arrow should be enabled at index 1"


def test_carousel_older_arrow_disabled_at_oldest(qapp):
    """The 'Older' (right) arrow is disabled when the oldest entry is shown."""
    entries = _make_entries(3)
    dlg = WhatsNewDialog(entries)

    # Navigate to the last entry
    dlg._go_older()  # index 1
    dlg._go_older()  # index 2 (oldest)

    assert not dlg._btn_older.isEnabled(), "'Older' arrow should be disabled at last index"
    assert dlg._pos_label.text() == "3 / 3"
    combined = _visible_label_texts(dlg)
    assert entries[2].title in combined, "Oldest entry title not shown at last index"


def test_carousel_navigate_back_to_newest(qapp):
    """After navigating to oldest, stepping forward returns to newest and disables newer arrow."""
    entries = _make_entries(3)
    dlg = WhatsNewDialog(entries)

    dlg._go_older()  # → index 1
    dlg._go_older()  # → index 2
    dlg._go_newer()  # → index 1
    dlg._go_newer()  # → index 0

    combined = _visible_label_texts(dlg)
    assert entries[0].title in combined, "Newest entry title not restored after forward navigation"
    assert dlg._pos_label.text() == "1 / 3"
    assert not dlg._btn_newer.isEnabled(), "'Newer' arrow should be disabled back at index 0"
    assert dlg._btn_older.isEnabled(), "'Older' arrow should be enabled at index 0"


def test_carousel_single_entry_hides_nav(qapp):
    """With a single entry both arrows are hidden and no position indicator is shown."""
    entries = _make_entries(1)
    dlg = WhatsNewDialog(entries)

    # The nav widget (parent of both buttons and pos label) should be hidden
    assert dlg._nav_widget.isHidden(), "Nav widget should be hidden for a single entry"


def test_carousel_single_entry_renders_content(qapp):
    """With a single entry the entry's title and items still render."""
    entries = _make_entries(1)
    dlg = WhatsNewDialog(entries)

    combined = _visible_label_texts(dlg)
    assert entries[0].title in combined, "Single entry title not rendered"
    assert any(item in combined for item in entries[0].items), "Single entry items not rendered"


def test_carousel_empty_hides_nav(qapp):
    """With an empty list the nav widget is hidden and the empty-state text is shown."""
    dlg = WhatsNewDialog([])

    assert dlg._nav_widget.isHidden(), "Nav widget should be hidden for empty entry list"
    combined = _visible_label_texts(dlg)
    assert "No new changes" in combined, "Empty-state text not rendered"


# ---------------------------------------------------------------------------
# 3. MainWindow._whats_new_unseen decision logic
# ---------------------------------------------------------------------------

import metatv.whats_new as _whats_new_mod


class _FakeConfig:
    """Minimal config stub for _whats_new_unseen tests."""
    def __init__(self, last_seen_whats_new_id: int = 0):
        self.last_seen_whats_new_id = last_seen_whats_new_id
        self._save_calls = 0

    def save(self):
        self._save_calls += 1


def _make_window_stub(last_seen_id: int):
    """Return a lightweight object that has _whats_new_unseen wired up."""
    from metatv.gui.main_window import MainWindow

    host = MainWindow.__new__(MainWindow)
    host.config = _FakeConfig(last_seen_whats_new_id=last_seen_id)
    return host


def test_whats_new_unseen_all_when_id_zero():
    """_whats_new_unseen() returns all entries when last_seen_id == 0."""
    host = _make_window_stub(last_seen_id=0)
    result = host._whats_new_unseen()
    assert len(result) == len(WHATS_NEW)


def test_whats_new_unseen_empty_when_seen_latest():
    """_whats_new_unseen() returns [] when last_seen_id == latest_id()."""
    host = _make_window_stub(last_seen_id=latest_id())
    result = host._whats_new_unseen()
    assert result == []


# ---------------------------------------------------------------------------
# 4. maybe_show_whats_new — cursor advance + idempotency
# ---------------------------------------------------------------------------

def test_maybe_show_whats_new_advances_cursor_and_saves(qapp):
    """maybe_show_whats_new with unseen entries advances the cursor and saves config."""
    from metatv.gui.main_window import MainWindow
    import metatv.gui.main_window as _mw_mod

    host = MainWindow.__new__(MainWindow)
    host.config = _FakeConfig(last_seen_whats_new_id=0)
    host._whats_new_checked = False

    exec_calls = []

    # Patch WhatsNewDialog in the main_window module so the ctor receives None parent
    class _FakeDialog:
        def __init__(self_d, entries, parent=None):
            pass
        def exec(self_d):
            exec_calls.append(1)

    with patch.object(_mw_mod, "WhatsNewDialog", _FakeDialog):
        host.maybe_show_whats_new()

    # Dialog was shown once
    assert len(exec_calls) == 1
    # Cursor advanced to latest
    assert host.config.last_seen_whats_new_id == latest_id()
    # Config was saved
    assert host.config._save_calls == 1


def test_maybe_show_whats_new_does_not_show_twice(qapp):
    """maybe_show_whats_new is idempotent — second call does nothing."""
    from metatv.gui.main_window import MainWindow
    import metatv.gui.main_window as _mw_mod

    host = MainWindow.__new__(MainWindow)
    host.config = _FakeConfig(last_seen_whats_new_id=0)
    host._whats_new_checked = False

    exec_calls = []

    class _FakeDialog:
        def __init__(self_d, entries, parent=None):
            pass
        def exec(self_d):
            exec_calls.append(1)

    with patch.object(_mw_mod, "WhatsNewDialog", _FakeDialog):
        host.maybe_show_whats_new()
        host.maybe_show_whats_new()   # second call — must be a no-op

    assert len(exec_calls) == 1, "Dialog shown more than once"


def test_maybe_show_whats_new_skips_when_all_seen(qapp):
    """maybe_show_whats_new does not open dialog when nothing is unseen."""
    from metatv.gui.main_window import MainWindow
    import metatv.gui.main_window as _mw_mod

    host = MainWindow.__new__(MainWindow)
    host.config = _FakeConfig(last_seen_whats_new_id=latest_id())
    host._whats_new_checked = False

    exec_calls = []

    class _FakeDialog:
        def __init__(self_d, entries, parent=None):
            pass
        def exec(self_d):
            exec_calls.append(1)

    with patch.object(_mw_mod, "WhatsNewDialog", _FakeDialog):
        host.maybe_show_whats_new()

    assert exec_calls == [], "Dialog shown even though all entries were seen"


# ---------------------------------------------------------------------------
# 5. Config.last_seen_whats_new_id default and persistence
# ---------------------------------------------------------------------------

def test_config_default_last_seen_id():
    """A fresh Config has last_seen_whats_new_id == 0."""
    from metatv.core.config import Config
    cfg = Config()
    assert cfg.last_seen_whats_new_id == 0


def test_config_last_seen_id_round_trip(tmp_path):
    """last_seen_whats_new_id persists through save/load."""
    from metatv.core.config import Config

    # Build a config pointing to tmp_path so we don't touch real user config
    cfg = Config(
        config_dir=tmp_path,
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )
    cfg.last_seen_whats_new_id = 42
    cfg.save()

    # Reload from file
    cfg2, _recovered = Config.load.__func__(Config) if False else (None, None)
    # Direct load via yaml to avoid touching the real config file
    import yaml
    config_file = tmp_path / "config.yaml"
    with open(config_file) as f:
        data = yaml.safe_load(f)

    assert data["last_seen_whats_new_id"] == 42
