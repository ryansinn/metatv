"""A section header counts CONTENT, never the chrome around it.

Owner report: "even though there are no favorites, it reports 2." The empty
state adds two rows — "No favorites yet" and "Right-click any channel to add to
favorites" — and the header counted them, so the two lines saying there is
nothing WERE the something.

The same screenshot showed Watch Queue reading 5 for three titles under two
group headings, which is the same defect: a heading is a list row too.

Each of the four sections carried its own copy of the count, and every copy
excluded exactly one kind of chrome — the ``+N more`` tail — by role. That is
the enumeration failure this codebase keeps meeting: a list of what to skip
cannot see a kind nobody remembered to add, and two of the three kinds were
already there.

The rule is now inverted and shared: count what QUALIFIES. Chrome is
non-selectable (placeholders and headings are built with ``NoItemFlags``, the
more-row clears ``ItemIsSelectable``); real rows are selectable because they can
be clicked. One predicate covers all three kinds and a fourth not yet invented.
"""

from __future__ import annotations

import pathlib

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QListWidget, QListWidgetItem

from metatv.core.config import Config
from metatv.gui.sidebar.base import CollapsibleSection
from metatv.gui.sidebar.favorites import FavoritesSection

SECTION_MODULES = ("favorites.py", "recommended.py", "history.py", "queue.py")


def _list(*rows: tuple[str, bool]) -> QListWidget:
    """Build a list from (text, is_content) pairs; chrome gets NoItemFlags."""
    lst = QListWidget()
    for text, is_content in rows:
        item = QListWidgetItem(text)
        if not is_content:
            item.setFlags(Qt.ItemFlag.NoItemFlags)
        lst.addItem(item)
    return lst


def test_an_empty_favorites_section_reports_zero(qapp, tmp_path):
    """The reported bug, end to end through the real section."""
    section = FavoritesSection(Config(config_dir=tmp_path), db=None)
    section._populate_rows(([], []))

    assert section.favorites_list.count() == 2, "precondition: the two placeholders"
    assert section.item_count() == 0, (
        "the two lines telling the user there are no favorites were counted AS "
        f"favorites; got {section.item_count()}"
    )


def test_group_headings_are_not_content(qapp):
    """Watch Queue read 5 for three titles under two headings."""
    lst = _list(("CONTINUE WATCHING", False), ("The Naked Gun", True),
                ("NEVER WATCHED (2)", False), ("Cool Hand Luke", True),
                ("All Night Wrong", True))
    assert lst.count() == 5
    assert CollapsibleSection.count_content_rows(lst) == 3


def test_the_more_tail_is_still_excluded(qapp):
    """The one kind the old rule DID exclude must stay excluded."""
    lst = _list(("A title", True), ("+3 more", False))
    assert CollapsibleSection.count_content_rows(lst) == 1


def test_a_list_of_only_content_counts_all_of_it(qapp):
    """The floor: the predicate must not exclude real rows."""
    lst = _list(("one", True), ("two", True), ("three", True))
    assert CollapsibleSection.count_content_rows(lst) == 3


def test_an_empty_list_is_zero_not_none(qapp):
    assert CollapsibleSection.count_content_rows(_list()) == 0


@pytest.mark.parametrize("module", SECTION_MODULES)
def test_no_section_keeps_its_own_copy_of_the_count(module):
    """Derived: four copies drifted once, so there must be one.

    A section that reintroduces a private row count will diverge from the other
    three the next time a new kind of chrome is added — which is exactly how
    headings and placeholders came to be counted.
    """
    src = (pathlib.Path("metatv/gui/sidebar") / module).read_text(encoding="utf-8")
    body = src[src.index("def item_count"):]
    body = body[:body.index("\n    def ", 1)] if "\n    def " in body[1:] else body
    assert "_MORE_ROLE" not in body, (
        f"{module} counts rows by excluding the more-row itself — call "
        "count_content_rows so every kind of chrome is handled in one place"
    )
    assert "count_content_rows" in body, f"{module} must use the shared counter"
