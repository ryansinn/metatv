"""Play on a similar-title row is pointer-only.

Eighteen similar titles rendered eighteen Play buttons down the left edge: a
column of identical glyphs carrying no information, because every row can be
played. The owner's report was "a sea of play buttons … very very busy looking".

Play is an *affordance*; Favourite and Queue are *state*. Only the first one
hides. And it hides without moving anything, because a row that reflows under
the cursor is the same defect as a badge that shifts the columns beside it.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QEvent, QPointF
from PyQt6.QtGui import QEnterEvent
from PyQt6.QtWidgets import QPushButton

from metatv.gui import icons as _icons
from metatv.gui.details_similar import _SimilarSection
from metatv.gui.details_versions import ChannelVersion


def _titles(n=5, **kw):
    return [
        ChannelVersion(
            channel_id=f"c{i}", name=f"Title {i}", in_queue=kw.get("in_queue", False),
            detected_title=f"Title {i}", detected_year="2024", media_type="movie",
            is_favorite=kw.get("is_favorite", False),
        )
        for i in range(n)
    ]


@pytest.fixture
def section(qapp, tmp_path):
    from metatv.core.config import Config

    sec = _SimilarSection(Config(config_dir=tmp_path))
    sec.resize(460, 300)
    sec.show()
    qapp.processEvents()
    return sec


def _rows(section):
    return [section._body_layout.itemAt(i).widget()
            for i in range(section._body_layout.count())]


def _button(row, glyph):
    for i in range(row.layout().count()):
        w = row.layout().itemAt(i).widget()
        if isinstance(w, QPushButton) and w.text() == glyph:
            return w
    raise AssertionError(f"no {glyph!r} button in the row")


def _hover(row):
    row.enterEvent(QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5)))


def _unhover(row):
    row.leaveEvent(QEvent(QEvent.Type.Leave))


def test_play_is_hidden_until_the_row_is_hovered(section, qapp):
    section.load(_titles())
    qapp.processEvents()

    for row in _rows(section):
        assert not _button(row, _icons.play_icon).isVisible(), (
            "a Play button is showing on an un-hovered row — this is the sea "
            "of identical glyphs the change removes"
        )


def test_hovering_reveals_play_and_leaving_hides_it_again(section, qapp):
    section.load(_titles())
    qapp.processEvents()
    row = _rows(section)[0]
    play = _button(row, _icons.play_icon)

    _hover(row)
    qapp.processEvents()
    assert play.isVisible(), "hovering the row did not reveal Play"

    _unhover(row)
    qapp.processEvents()
    assert not play.isVisible(), "Play stayed visible after the pointer left"


def test_only_the_hovered_row_reveals_its_play(section, qapp):
    """Otherwise hovering anywhere restores the sea."""
    section.load(_titles())
    qapp.processEvents()
    rows = _rows(section)

    _hover(rows[2])
    qapp.processEvents()

    visible = [i for i, r in enumerate(rows)
               if _button(r, _icons.play_icon).isVisible()]
    assert visible == [2], f"rows {visible} are showing Play, expected only [2]"


def test_nothing_moves_when_play_appears(section, qapp):
    """Rendered geometry — the reason the button hides rather than unloads.

    A plain hide() removes the widget from the layout and every title steps
    22px left as the pointer runs down the list. The size policy retains the
    space instead, so the column is still a column.
    """
    section.load(_titles())
    qapp.processEvents()
    row = _rows(section)[0]
    play = _button(row, _icons.play_icon)
    others = [row.layout().itemAt(i).widget().geometry()
              for i in range(1, row.layout().count())]
    play_rect = play.geometry()

    _hover(row)
    qapp.processEvents()

    after = [row.layout().itemAt(i).widget().geometry()
             for i in range(1, row.layout().count())]
    assert after == others, (
        "the row reflowed when Play appeared — every title shifts as the "
        "pointer moves down the list"
    )
    assert play.geometry() == play_rect, "Play itself moved when it appeared"
    assert play_rect.width() > 0, (
        "Play occupies no space even hidden — the comparison above would pass "
        "for a row that never reserved room for it"
    )


def test_favorite_and_queue_stay_visible_because_they_are_state(section, qapp):
    """A gold star you can only see by hovering is a star you cannot see.

    These two say something about the title. Play says only that the row is a
    row, which is why it is the one that hides.
    """
    section.load(_titles(is_favorite=True, in_queue=True))
    qapp.processEvents()

    for row in _rows(section):
        assert _button(row, _icons.favorite_icon).isVisible(), (
            "Favorite is hidden — its state is no longer visible at a glance"
        )
        assert _button(row, _icons.watched_icon).isVisible(), (
            "the in-queue marker is hidden — same problem"
        )


def test_play_still_plays_when_revealed(section, qapp):
    """Hiding the control must not disconnect it."""
    played = []
    section.play_requested.connect(played.append)
    section.load(_titles())
    qapp.processEvents()

    row = _rows(section)[1]
    _hover(row)
    qapp.processEvents()
    _button(row, _icons.play_icon).click()

    assert played == ["c1"]
