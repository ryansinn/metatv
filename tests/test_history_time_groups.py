"""History groups by WHEN, and spends the freed slot on WHICH.

Two complaints, one cause. The list is ordered by when you watched something,
and every row spent a slot saying that again — while the chip that would tell
two copies of the same film apart had nowhere to go:

    Deathstalker   2025  1h
    Deathstalker   2025  1h

Owner: *"you play a 4k and the user chooses a lower quality but then when they
go back to resume there are just two with the same title and no indication of
what the difference is"*, and *"rather than having the time on the same line as
the history entries, why not just have subdivisions … does it really matter
when someone watched something? it's already in chronological order."*

So the time moved up to a heading and quality moved in beside the title. These
assert RENDERED GEOMETRY, not just that a chip exists — order is not position,
and a quality chip parked in the right-hand rail beside the year would satisfy
"the row has a quality chip" while leaving the two rows looking identical where
the eye actually compares them.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget

from metatv.core.history_buckets import BUCKETS
from metatv.core.repositories.dtos import HistoryDTO
from metatv.gui.sidebar.history import HistorySection

_ROLE_BUCKET = Qt.ItemDataRole.UserRole + 8


@pytest.fixture()
def section(qapp, tmp_path):
    from metatv.core.config import Config

    sec = HistorySection(Config(config_dir=tmp_path), db=None)
    yield sec
    sec.deleteLater()


def _dto(cid, title, *, ago, year="", quality="", lang="", media="movie"):
    return HistoryDTO(
        id=cid, name=title, media_type=media, episode_code=None,
        last_played=datetime.now() - ago, detected_title=title,
        detected_year=year, detected_quality=quality, detected_prefix=lang,
    )


def _items(section):
    """[(kind, widget)] in list order; kind is "heading" or "row"."""
    lst = section.history_list
    out = []
    for i in range(lst.count()):
        item = lst.item(i)
        kind = "heading" if item.data(_ROLE_BUCKET) is not None else "row"
        out.append((kind, lst.itemWidget(item)))
    return out


def _texts(widget) -> "list[tuple[str, int, str]]":
    """[(text, x, classname)] for every labelled child, left to right."""
    found = []
    for child in widget.findChildren(QWidget):
        text = child.text() if hasattr(child, "text") else ""
        if text:
            found.append((text, child.geometry().x(), type(child).__name__))
    return sorted(found, key=lambda t: t[1])


# --------------------------------------------------------------------------- #
# Grouping
# --------------------------------------------------------------------------- #

def test_rows_are_grouped_under_time_headings(section):
    section._populate_rows([
        _dto("a", "Just now", ago=timedelta(minutes=6)),
        _dto("b", "Earlier today", ago=timedelta(hours=7)),
        _dto("c", "Ancient", ago=timedelta(days=45)),
    ])
    kinds = [k for k, _ in _items(section)]
    assert kinds == ["heading", "row", "heading", "row", "heading", "row"]


def test_headings_appear_newest_first(section):
    section._populate_rows([
        _dto("a", "Recent", ago=timedelta(minutes=6)),
        _dto("c", "Ancient", ago=timedelta(days=45)),
        _dto("b", "Today", ago=timedelta(hours=7)),
    ])
    labels = [w.label.text() for k, w in _items(section) if k == "heading"]
    order = [b.label for b in BUCKETS]
    assert labels == sorted(labels, key=order.index), (
        f"headings are out of chronological order: {labels}"
    )
    assert labels[0] == "Last hour"


def test_an_empty_group_draws_no_heading(section):
    """Six buckets exist; only the occupied ones may appear."""
    section._populate_rows([_dto("a", "Only one", ago=timedelta(minutes=6))])
    headings = [w.label.text() for k, w in _items(section) if k == "heading"]
    assert headings == ["Last hour"], f"empty groups drew headings: {headings}"


def test_a_heading_counts_its_own_rows(section):
    section._populate_rows([
        _dto("a", "One", ago=timedelta(hours=5)),
        _dto("b", "Two", ago=timedelta(hours=6)),
        _dto("c", "Three", ago=timedelta(hours=7)),
    ])
    heading = next(w for k, w in _items(section) if k == "heading")
    assert heading.count_label.text().strip() == "3"


# --------------------------------------------------------------------------- #
# The reported bug: two rows for the same title must look different.
# --------------------------------------------------------------------------- #

def test_two_copies_of_one_title_are_told_apart_by_quality(section):
    """The exact rows from the owner's screenshot."""
    section._populate_rows([
        _dto("a", "Deathstalker", ago=timedelta(hours=9),
             year="2025", quality="4K", lang="EN"),
        _dto("b", "Deathstalker", ago=timedelta(hours=10),
             year="2025", quality="HD", lang="ES"),
    ])
    rows = [w for k, w in _items(section) if k == "row"]
    assert len(rows) == 2
    rendered = []
    for row in rows:
        row.resize(320, max(row.sizeHint().height(), 1))
        row.show()
        rendered.append([t for t, _x, _c in _texts(row)])

    assert rendered[0] != rendered[1], (
        f"both rows render identically: {rendered[0]} — this is the bug"
    )
    assert "4K" in rendered[0] and "HD" in rendered[1]


def test_quality_sits_beside_the_title_not_in_the_right_rail(section):
    """Position, not presence. A quality chip parked beside the year would
    satisfy "the row has a quality chip" and still leave the two rows looking
    the same where the eye compares them (V3; ledger F10)."""
    section._populate_rows([
        _dto("a", "Deathstalker", ago=timedelta(hours=9),
             year="2025", quality="4K", lang="EN"),
    ])
    row = next(w for k, w in _items(section) if k == "row")
    row.resize(320, max(row.sizeHint().height(), 1))
    row.show()

    placed = {t: (x, cls) for t, x, cls in _texts(row)}
    assert "4K" in placed, f"no quality chip rendered: {list(placed)}"
    title_x, _ = placed["Deathstalker"]
    quality_x, _ = placed["4K"]
    year_x, _ = placed["2025"]

    assert title_x < quality_x < year_x, (
        f"quality at x={quality_x} is not between the title (x={title_x}) and "
        f"the right-rail year (x={year_x})"
    )
    # And it must HUG the title rather than drift toward the rail.
    assert quality_x - year_x < 0
    assert (quality_x - title_x) < (year_x - quality_x), (
        "the quality chip is nearer the right rail than the title it belongs to"
    )


def test_the_row_no_longer_repeats_the_time(section):
    """The heading says when; a per-row "9h" would say it twice."""
    section._populate_rows([
        _dto("a", "Deathstalker", ago=timedelta(hours=9),
             year="2025", quality="4K", lang="EN"),
    ])
    row = next(w for k, w in _items(section) if k == "row")
    row.resize(320, max(row.sizeHint().height(), 1))
    row.show()
    texts = [t for t, _x, _c in _texts(row)]
    assert not any(t.endswith("h") and t[:-1].isdigit() for t in texts), (
        f"a terse age is still rendered on the row: {texts}"
    )


# --------------------------------------------------------------------------- #
# Each heading forgets its own group, and only its own.
# --------------------------------------------------------------------------- #

def test_every_heading_carries_a_forget_button(section):
    section._populate_rows([
        _dto("a", "Recent", ago=timedelta(minutes=6)),
        _dto("b", "Ancient", ago=timedelta(days=45)),
    ])
    headings = [w for k, w in _items(section) if k == "heading"]
    # Without this the loop below has nothing to check and the test passes on a
    # History that renders no headings at all — which is the state it exists to
    # forbid. It passed exactly that way against the pre-fix code.
    assert len(headings) == 2, f"expected two headings, got {len(headings)}"
    for widget in headings:
        assert widget.trailing_button is not None, (
            f"{widget.label.text()} has no forget control"
        )
        assert widget.trailing_button.toolTip()


def test_the_forget_button_emits_its_own_bucket(section):
    section._populate_rows([
        _dto("a", "Recent", ago=timedelta(minutes=6)),
        _dto("b", "Ancient", ago=timedelta(days=45)),
    ])
    emitted = []
    section.clearHistoryGroupClicked.connect(emitted.append)
    for kind, widget in _items(section):
        if kind == "heading":
            widget.trailing_button.click()
    assert emitted == ["hour", "older"], (
        f"headings emitted {emitted}; each must name its OWN group"
    )


def test_the_forget_button_uses_a_vector_icon_not_an_emoji(section):
    """An emoji set as a button's TEXT is drawn at the font size and clips in a
    20x20 button (ledger F13)."""
    section._populate_rows([_dto("a", "Recent", ago=timedelta(minutes=6))])
    heading = next(w for k, w in _items(section) if k == "heading")
    button = heading.trailing_button
    assert button.text() == "", (
        f"the glyph is button TEXT ({button.text()!r}) rather than an icon"
    )
    assert not button.icon().isNull(), "no vector icon was set"


# --------------------------------------------------------------------------- #
# Removing the last row under a heading removes the heading.
# --------------------------------------------------------------------------- #

def test_a_heading_whose_group_empties_is_removed(section):
    section._populate_rows([
        _dto("a", "Recent", ago=timedelta(minutes=6)),
        _dto("b", "Ancient", ago=timedelta(days=45)),
    ])
    lst = section.history_list
    # Drop the "Older" row, leaving its heading stranded over nothing.
    for i in range(lst.count()):
        if lst.item(i).data(Qt.ItemDataRole.UserRole) == "b":
            lst.takeItem(i)
            break
    section._after_rows_removed(lst)

    headings = [w.label.text() for k, w in _items(section) if k == "heading"]
    assert headings == ["Last hour"], (
        f"a heading survived its group emptying: {headings}"
    )


def test_removing_every_row_empties_the_section(section):
    section._populate_rows([_dto("a", "Recent", ago=timedelta(minutes=6))])
    lst = section.history_list
    assert lst.count() == 2, (
        "expected a heading and a row; without the heading this test would pass "
        "on a list that never had one"
    )
    for i in range(lst.count() - 1, -1, -1):
        if lst.item(i).data(Qt.ItemDataRole.UserRole):
            lst.takeItem(i)
    section._after_rows_removed(lst)
    assert lst.count() == 0, "an orphaned heading was left behind"


def test_a_heading_is_not_clickable_as_a_channel(section):
    """Headings must not fire the play path — they carry no channel id."""
    section._populate_rows([_dto("a", "Recent", ago=timedelta(minutes=6))])
    played = []
    section.historyItemClicked.connect(lambda *a: played.append(a))
    lst = section.history_list
    heading_item = next(
        lst.item(i) for i in range(lst.count())
        if lst.item(i).data(_ROLE_BUCKET) is not None
    )
    section.on_history_item_clicked(heading_item)
    assert played == [], "double-clicking a heading tried to play something"
