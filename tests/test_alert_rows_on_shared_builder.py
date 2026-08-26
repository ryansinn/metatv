"""Watch Alerts rows are built by the shared builder, and therefore elide.

Watch Alerts was the last sidebar section hand-assembling its own QHBoxLayout.
The visible cost was that its titles CLIPPED at the panel edge where every
other list middle-elides with a tooltip — for a reason that is entirely about
sizing, and is the thing most of this file guards:

A row laid out by ``setItemWidget`` is sized from the ITEM's size hint. A row
reporting its NATURAL width — 462px for a long rule name against a 300px
sidebar — makes the list grow a horizontal range and hands the row that full
width, so ``MiddleElideLabel`` has nothing to elide against and the panel edge
does the cutting instead. Reporting the MINIMUM width is what lets it work.

The rest guards the four slots added to ``build_chip_row`` for this, since the
alternative to adding them was a trimmed copy of the builder.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QPushButton

from metatv.core.config import Config
from metatv.gui import theme as _theme
from metatv.gui.chip_row import (
    CHIP_NEWS, CHIP_QUALITY, CHIP_YEAR, SUFFIX_OBJECT_NAME, build_chip_row,
    chip_widget, row_title_label,
)
from metatv.gui.sidebar.alerts_rows import SLOT_W, _AlertRow, _VodAlertRow

NOW = datetime(2026, 8, 26, 12, 0, 0)
LONG = "A Very Long Keyword Rule That Should Middle Elide Somewhere Along It"
NARROW = 300


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _in_list(qapp, row):
    """Put a row in a real QListWidget the way the section does.

    Not a bare ``row.setFixedWidth()``: the bug was in how the LIST sizes the
    row from its hint, so a test that sets the width by hand would pass against
    the broken code.
    """
    lst = QListWidget()
    lst.setFixedWidth(NARROW)
    item = QListWidgetItem()
    lst.addItem(item)
    item.setSizeHint(row.sizeHint())
    lst.setItemWidget(item, row)
    lst.show()
    for _ in range(4):
        qapp.processEvents()
    return lst


class TestALongTitleElidesInsteadOfClipping:
    """The visible payoff, asserted on rendered geometry."""

    @pytest.mark.parametrize("make", [
        lambda tmp: _VodAlertRow(LONG, "17"),
        lambda tmp: _AlertRow(LONG, "3m left", Config(config_dir=tmp)),
    ], ids=["movies-series", "epg"])
    def test_the_title_is_narrower_than_its_own_text(self, qapp, tmp_path, make):
        """A title label narrower than its full text MUST elide.

        ``MiddleElideLabel.paintEvent`` elides against its own ``width()``, so
        this is a statement about what gets painted, not about intent. Against
        the pre-fix sizing the label was handed the row's full natural width
        and this is false — nothing elided, and the panel edge cut the text.
        """
        row = make(tmp_path)
        lst = _in_list(qapp, row)
        try:
            title = row_title_label(row)
            assert title is not None
            full = title.fontMetrics().horizontalAdvance(title.text())
            assert title.width() < full, (
                f"title got {title.width()}px for {full}px of text — it will be "
                "cut off rather than elided"
            )
            assert title.text() == LONG, "the full text stays available"
            assert title.toolTip() == LONG, "and is reachable on hover"
        finally:
            lst.deleteLater()
            qapp.processEvents()

    def test_the_row_never_asks_the_list_to_widen(self, qapp, tmp_path):
        """The size hint reports MINIMUM width and FULL height.

        Both halves matter and both were wrong when the rows first moved onto
        the shared builder: the builder's own row is tighter than the section's
        29px, and its natural width is what widened the list.
        """
        row = _VodAlertRow(LONG, "17")
        assert row.sizeHint().width() < NARROW, (
            "the row demands more width than the sidebar has, which is what "
            "defeats elision"
        )
        assert row.sizeHint().height() >= row.minimumHeight() > 20, (
            "the row reports the inner chip row's tighter height, so the list "
            "would draw cramped rows"
        )

    def test_a_short_title_is_left_alone(self, qapp, tmp_path):
        """Eliding is for text that does not fit — nothing else."""
        row = _VodAlertRow("Dune", "3")
        lst = _in_list(qapp, row)
        try:
            title = row_title_label(row)
            full = title.fontMetrics().horizontalAdvance("Dune")
            assert title.width() >= full, "a short title was squeezed"
        finally:
            lst.deleteLater()
            qapp.processEvents()


class TestTheSlotsAddedToTheSharedBuilder:
    """Each is a grammar element, not a Watch-Alerts-shaped hole."""

    def test_leading_slot_is_the_absolute_left(self, qapp):
        slot = QLabel()
        slot.setFixedWidth(SLOT_W)
        row = build_chip_row(title="Dune", leading_slot=slot, liked=True,
                             icon_role="movie")
        row.show()
        qapp.processEvents()
        title = row_title_label(row)
        assert slot.x() < title.x(), "the slot must precede the title"
        # ...and everything else, including the elements that used to lead.
        for other in row.findChildren(QLabel):
            if other is slot or other is title:
                continue
            assert slot.x() <= other.x(), "something was placed left of the slot"
        row.deleteLater()

    def test_a_reserved_slot_does_not_move_the_title(self, qapp):
        """The whole point of a fixed-width column, asserted as geometry."""
        empty, marked = QLabel(), QLabel("*")
        for s in (empty, marked):
            s.setFixedWidth(SLOT_W)
        a = build_chip_row(title="Dune", leading_slot=empty)
        b = build_chip_row(title="Dune", leading_slot=marked)
        for r in (a, b):
            r.setFixedWidth(NARROW)
            r.show()
        qapp.processEvents()
        assert row_title_label(a).x() == row_title_label(b).x(), (
            "a marker in the slot shifted the title — the column is not reserved"
        )
        a.deleteLater(); b.deleteLater()

    def test_title_chips_sit_left_of_rail_chips(self, qapp):
        """A claim about the copy travels with the name; a list fact does not.

        Owner, on the Watch Alerts grammar: "the quality chip should be align
        left right after the channel title".
        """
        row = build_chip_row(
            title="Dune",
            title_chips=((CHIP_QUALITY, "4K"),),
            chips=((CHIP_YEAR, "1984"),),
        )
        row.setFixedWidth(NARROW)
        row.show()
        qapp.processEvents()
        chips = {c.text(): c for c in row.findChildren(QPushButton)}
        title = row_title_label(row)
        title_gap = chips["4K"].x() - (title.x() + title.width())
        rail_gap = chips["1984"].x() - (title.x() + title.width())
        # Ordering alone does not discriminate: put the title chips AFTER the
        # stretch and they still come before the rail chips. What separates the
        # two is the STRETCH between them, so measure the gap.
        assert 0 <= title_gap < 12, (
            f"the quality chip sits {title_gap}px from the title — it is in "
            "the rail, not with the name"
        )
        assert rail_gap > title_gap + 40, (
            f"the year chip is only {rail_gap}px out; it should be pushed to "
            "the right edge by the stretch"
        )
        assert chips["1984"].x() > NARROW // 2
        row.deleteLater()

    def test_title_suffix_takes_the_existing_subordinate_role(self, qapp):
        """No new theme role: SIDEBAR_ROW_TAIL already means exactly this."""
        row = build_chip_row(title="Alone", title_suffix="(US)")
        suffix = row.findChild(QLabel, SUFFIX_OBJECT_NAME)
        assert suffix is not None and suffix.text() == "(US)"
        assert suffix.styleSheet() == _theme.SIDEBAR_ROW_TAIL

    def test_tail_widget_lands_in_the_right_cluster(self, qapp):
        bar = QLabel("bar")
        bar.setFixedWidth(44)
        row = build_chip_row(title="Dune", tail_widget=bar)
        row.setFixedWidth(NARROW)
        row.show()
        qapp.processEvents()
        assert bar.x() > row_title_label(row).x()
        assert bar.x() > NARROW // 2, "a tail must be pinned right, not centred"
        row.deleteLater()

    def test_indent_insets_the_whole_row(self, qapp):
        flat = build_chip_row(title="Dune")
        deep = build_chip_row(title="Dune", indent=14)
        for r in (flat, deep):
            r.setFixedWidth(NARROW)
            r.show()
        qapp.processEvents()
        assert row_title_label(deep).x() - row_title_label(flat).x() == 14
        flat.deleteLater(); deep.deleteLater()


class TestChipsComeFromOnePlace:
    """The copies that went stale on a theme switch are gone."""

    def test_the_news_pill_is_filled_and_reads_its_fill(self, qapp):
        chip = chip_widget(CHIP_NEWS, "+3")
        sheet = chip.styleSheet()
        assert _theme.COLOR_OK in sheet
        assert "background" in sheet, "the news count is a FILLED pill"
        assert _theme.on_fill(_theme.COLOR_OK) in sheet, (
            "the foreground must come from on_fill, not a hardcoded colour"
        )

    def test_a_new_series_row_gets_the_pill_and_an_idle_one_does_not(self, qapp):
        new = _VodAlertRow("Severance", "+3", is_new=True)
        idle = _VodAlertRow("Severance", "", is_new=False)
        new_sheets = [c.styleSheet() for c in new.findChildren(QPushButton)]
        assert any("background" in s and _theme.COLOR_OK in s for s in new_sheets)
        idle_texts = [c.text() for c in idle.findChildren(QPushButton)]
        assert not any(t.startswith("+") for t in idle_texts)

    def test_every_alerts_chip_is_registered_for_theme_switches(self, qapp, tmp_path):
        """The stale-sheet bug, asserted at the registry.

        The old rows built chip sheets as f-strings and applied them with
        ``setStyleSheet``, which Qt renders ONCE — so a chip kept the previous
        palette's colours forever.

        Asserted as membership of ``theme._style_registry`` rather than by
        switching palettes and watching the sheets change: that weaker version
        was written first and PASSED with the chips put back on
        ``setStyleSheet``, because a palette switch dirties those sheets by
        other routes. A test that cannot fail for the bug it names is worse
        than no test.
        """
        row = _AlertRow("ORF 2", "3m left", Config(config_dir=tmp_path),
                        quality="4K", when=NOW + timedelta(minutes=3), live=True)
        chips = row.findChildren(QPushButton)
        assert chips, "the row should carry at least the quality and time chips"

        registered = {id(ref()) for ref, _ in _theme._style_registry
                      if ref() is not None}
        for chip in chips:
            assert id(chip) in registered, (
                f"chip {chip.text()!r} is not registered with the theme — it "
                "will keep this palette's colours after a switch"
            )


class TestTheRowStillBehavesLikeARow:
    """What the shell kept: the slot's meaning and the row's own mouse."""

    def test_the_slot_is_hit_tested_in_the_rows_own_coordinates(self, qapp, tmp_path):
        """The slot lives inside the built row now, so its own geometry() is
        relative to that child rather than to the row a click arrives on."""
        row = _AlertRow("ORF 2", "3m left", Config(config_dir=tmp_path),
                        when=NOW + timedelta(minutes=3), live=True,
                        started_at=NOW - timedelta(minutes=27))
        row.setFixedWidth(NARROW)
        row.show()
        qapp.processEvents()
        rect = row._slot_rect()
        assert rect.width() == SLOT_W
        assert rect.topLeft() == row._slot.mapTo(row, QPoint(0, 0))
        assert rect.left() < NARROW // 2, "the slot is on the LEFT"
        row.deleteLater()

    def test_the_time_chip_is_the_one_the_tick_rewrites(self, qapp, tmp_path):
        """The row holds its time widget directly rather than finding it by
        text — a lookup that returns the wrong widget when a title happens to
        equal a time string."""
        row = _AlertRow("in 13m", "in 13m", Config(config_dir=tmp_path),
                        when=NOW + timedelta(minutes=13), live=False)
        assert row.time_lbl is not None
        assert row.time_lbl.text() == "in 13m"
        assert row.time_lbl is not row_title_label(row), (
            "the row grabbed its own TITLE as the time widget"
        )
        row.refresh_time(NOW + timedelta(minutes=5))
        assert row.time_lbl.text() != "in 13m"
        assert row_title_label(row).text() == "in 13m", "the title was rewritten"
