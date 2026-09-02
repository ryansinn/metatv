"""A sub-heading is measured and painted as a LABEL, not as a channel row.

The model grew a third row kind — the matched-person sub-heading under Cast &
Crew — and the delegate was never told. It had three ``== "header"`` branches,
so a person row fell through all of them and was measured, painted and
hit-tested as a CHANNEL: full channel height, the artwork path, and every field
read as ``None``.

Every test of the sub-headings was green, because they asserted the MODEL's role
data. CLAUDE.md's rule is exactly this case — *"a UI test that checks parsed
data, cell ORDER, or token existence passes for infinitely many wrong-looking
renderings"*. So this file asks the delegate itself: how tall, painted by what,
and what is clickable.
"""

from __future__ import annotations

import uuid

import pytest

from metatv.core.repositories.dtos import ChannelListDTO
from metatv.gui.channel_list_roles import ROW_KIND_ROLE


@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _dto(name, section_key=None, match_person=None):
    return ChannelListDTO(
        id=str(uuid.uuid4()), name=name, media_type="movie", provider_id="p1",
        is_favorite=False, category=None, quality=None, detected_prefix=None,
        detected_region=None, detected_quality=None, detected_year=None,
        detected_title=name, section_key=section_key, match_person=match_person,
    )


@pytest.fixture()
def rows(qapp):
    """A grouped search, and the (delegate, model, index-by-kind) to inspect."""
    from PyQt6.QtWidgets import QStyleOptionViewItem
    from metatv.gui.channel_list_model import ChannelListModel
    from metatv.gui.channel_list_delegate import ChannelRowDelegate

    model = ChannelListModel()
    model.set_channels(
        [_dto("Cage", "title"),
         _dto("Con Air", "cast", match_person="Nicolas Cage")],
        provider_icon_map={}, show_provider_icon=False, has_more=False,
        query_params={"search_query": "cage"}, favorite_icon="★",
        unfavorite_icon="☆",
    )
    delegate = ChannelRowDelegate()
    by_kind = {}
    for r in range(model.rowCount()):
        idx = model.index(r, 0)
        by_kind.setdefault(idx.data(ROW_KIND_ROLE) or "channel", idx)
    assert {"header", "person", "channel"} <= set(by_kind), by_kind
    return delegate, model, by_kind, QStyleOptionViewItem()


def test_a_subheading_is_one_line_tall_like_a_header(rows):
    """Not the channel height, which is a poster row on a comfy density."""
    from PyQt6.QtCore import QRect
    delegate, _model, by_kind, opt = rows
    opt.rect = QRect(0, 0, 600, 40)

    person_h = delegate.sizeHint(opt, by_kind["person"]).height()
    header_h = delegate.sizeHint(opt, by_kind["header"]).height()
    channel_h = delegate.sizeHint(opt, by_kind["channel"]).height()

    # The SECTION header is a band — it carries the rule, the Whole|Part control
    # and the caret, and the design gives it 9px/8px of padding for them. A
    # sub-heading is a bare line of type, so it is deliberately shorter.
    assert person_h < header_h, (
        f"a sub-heading ({person_h}px) is as tall as the section band "
        f"({header_h}px) — the second level must read as the second level")
    assert person_h < channel_h, (
        f"a sub-heading ({person_h}px) is as tall as a result row "
        f"({channel_h}px) — it is being measured as a channel")


def test_a_subheading_is_painted_by_the_label_path(rows, monkeypatch):
    """The HTML path, not the channel path that reads artwork and fields."""
    from PyQt6.QtCore import QRect
    from PyQt6.QtGui import QPainter, QPixmap
    delegate, _model, by_kind, opt = rows
    opt.rect = QRect(0, 0, 600, 40)

    seen = []
    monkeypatch.setattr(type(delegate), "_paint_html_row",
                        lambda self, p, o, i: seen.append(i.data(ROW_KIND_ROLE)))

    pix = QPixmap(600, 40)
    painter = QPainter(pix)
    try:
        for kind in ("header", "person", "channel"):
            delegate.paint(painter, opt, by_kind[kind])
    finally:
        painter.end()

    assert seen == ["person"], (
        f"the label path painted {seen}. A sub-heading must go through it; a "
        "channel must not; and the SECTION header must not either — it is "
        "painted by channel_list_section_band, which draws a rule and a "
        "segmented control that Qt rich text cannot express.")


def test_a_subheading_offers_nothing_to_click(rows):
    """No favourite star, no rating hit-zones — it is a label."""
    from PyQt6.QtCore import QRect
    delegate, _model, by_kind, _opt = rows
    rect = QRect(0, 0, 600, 40)

    assert delegate.action_rect(rect, by_kind["person"]).isNull(), (
        "a sub-heading exposes clickable regions")
    assert delegate.action_rect(rect, by_kind["header"]).isNull()
    assert not delegate.action_rect(rect, by_kind["channel"]).isNull(), (
        "a real row lost its clickable regions — this guard is inverted")
