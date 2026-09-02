"""The search section header, painted: label · rule · count · Whole|Part · caret.

Built to the settled design (the "Finding Tron" artifact, Concept E), which the
first attempt did not follow — it read the SIDEBAR's ``GroupHeading`` grammar
instead and got three things backwards. Recorded here because the difference is
not arbitrary and the next person will otherwise "fix" it back:

* the **label is bright and the count is muted**, the opposite of the sidebar.
  In the sidebar the label is the constant ("SERIES" always says SERIES) so the
  count carries the emphasis. Here the label names the FIELD THAT MATCHED —
  which is the whole explanation of why a row is on screen — so it leads.
* a **hairline rule** runs from the label across to the count. It is the reason
  the band reads as a band; without it the header is a short text run and the
  rest of the width is void. Owner: *"why is there so much empty space on the
  right side of the search results area now."*
* the **caret sits at the far right**, after the control — not before the label.

Painted rather than composed as rich text because none of that survives Qt's
rich-text subset: a ``flex:1`` rule has no equivalent, and a segmented control
needs its own hit rectangles anyway.

Every colour is a token, and the mockup's literals mapped almost one-to-one onto
ones that already existed: the band takes ``COLOR_BG_SECTION``, its borders and
the rule take ``COLOR_LINE``, the active half takes ``COLOR_ACCENT`` with
``COLOR_ON_ACCENT`` on it — the on-fill rule arriving at the same answer by
itself — and the quiet half and caret take ``COLOR_FAINT``.

The hex values are deliberately NOT repeated here. ``test_no_stray_color_literals``
scans source text, not just code, and it is right to: a hex in a comment is one
copy-paste away from being a hex in a stylesheet, which is the whole failure the
token layer exists to stop. It caught this docstring.
"""

from __future__ import annotations

from typing import NamedTuple

from PyQt6.QtCore import QRect, QRectF, Qt
from PyQt6.QtGui import QFont, QFontMetrics, QPainter, QPainterPath

from metatv.gui import theme as _theme
from metatv.gui.channel_list_roles import (
    ROW_KIND_ROLE, SECTION_COLLAPSED_ROLE, SECTION_COUNT_ROLE,
    SECTION_LABEL_ROLE, SECTION_WORD_ONLY_ROLE,
)
from metatv.gui.filter_bar import ToggleChip
from metatv.gui.token_color import to_qcolor

#: Horizontal inset, and the gap between the band's parts. From the mockup's
#: ``padding: 9px 12px 8px`` and ``gap: 10px``.
PAD_H = 12
PAD_TOP = 9
PAD_BOTTOM = 8
GAP = 10

#: The segmented track's corner radius comes from ``ToggleChip``, which is the
#: widget version of this control and already owns the number. Two definitions
#: of one radius is how a painted control and a real one drift apart by a pixel
#: nobody can find.
SEG_RADIUS = ToggleChip.SEGMENT_RADIUS
SEG_PAD_H = 8
SEG_PAD_V = 2

#: Tracking on the label, as a percentage — the mockup's ``.14em``.
LABEL_TRACKING = 114.0

#: The two halves, broadest first so the track reads loose → tight.
#:
#: ``All`` and ``Word``, not the ``Whole | Part`` first built. ``Part`` is a
#: SUPERSET of ``Whole`` — tiers 0-3 against 0-2 — so calling it "Part" said the
#: opposite of what it does, reading as "only partial matches" when it means
#: whole AND partial. Owner: *"Part basically includes Whole, and Whole is more
#: restrictive, right? … so Part should be All and Whole should be Word."*
#:
#: It also settles why there is no third state: ``All`` IS the everything, so an
#: ``All | Whole | Part`` would carry a synonym.
ALL = "All"
WORD = "Word"
CARET_OPEN = "▾"      # ▾
CARET_SHUT = "▸"      # ▸


class BandLayout(NamedTuple):
    """Where every part of the band sits. Geometry, so a test can assert it."""

    label: QRect
    rule: QRect
    count: QRect
    all_seg: QRect    # "All" — null when the section offers no toggle
    word_seg: QRect   # "Word" — null when the section offers no toggle
    caret: QRect


def _label_font(base: QFont) -> QFont:
    font = QFont(base)
    font.setPixelSize(int(_theme.FONT_XS.replace("px", "")))
    font.setCapitalization(QFont.Capitalization.AllUppercase)
    font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, LABEL_TRACKING)
    font.setWeight(QFont.Weight.DemiBold)
    return font


def _small_font(base: QFont) -> QFont:
    font = QFont(base)
    font.setPixelSize(int(_theme.FONT_XS.replace("px", "")))
    return font


def band_height(base: QFont) -> int:
    """One line of band type plus the mockup's asymmetric padding."""
    return QFontMetrics(_small_font(base)).height() + PAD_TOP + PAD_BOTTOM


def layout(rect: QRect, *, label: str, count: int, has_toggle: bool,
           base_font: QFont) -> BandLayout:
    """Lay the band out right-to-left, so the rule takes whatever is left.

    The caret, the control and the count are measured from the right edge in
    that order; the label is placed at the left; the rule fills the gap. That is
    what ``flex: 1`` does, and doing it any other way is how the rule ends up
    either missing or overlapping the count.
    """
    lm = QFontMetrics(_label_font(base_font))
    sm = QFontMetrics(_small_font(base_font))
    mid = rect.center().y() + 1

    def _centred(right: int, w: int, h: int) -> QRect:
        return QRect(right - w, mid - h // 2, w, h)

    x_right = rect.right() + 1 - PAD_H
    caret_w = sm.horizontalAdvance(CARET_OPEN)
    caret = _centred(x_right, caret_w, sm.height())
    x_right = caret.left() - GAP

    all_seg = word_seg = QRect()
    if has_toggle:
        seg_h = sm.height() + 2 * SEG_PAD_V
        word_w = sm.horizontalAdvance(WORD) + 2 * SEG_PAD_H
        all_w = sm.horizontalAdvance(ALL) + 2 * SEG_PAD_H
        # Word is the tighter half and sits on the right, so the track reads
        # broad → narrow in the direction the eye travels.
        word_seg = _centred(x_right, word_w, seg_h)
        # Adjacent, sharing an edge: one track with a divide, not two pills.
        all_seg = _centred(word_seg.left() + 1, all_w, seg_h)
        x_right = all_seg.left() - GAP

    count_w = sm.horizontalAdvance(f"{count:,}")
    count_rect = _centred(x_right, count_w, sm.height())

    label_w = lm.horizontalAdvance(label)
    label_rect = QRect(rect.left() + PAD_H, mid - lm.height() // 2,
                       label_w, lm.height())

    rule_left = label_rect.right() + GAP
    rule_right = count_rect.left() - GAP
    rule = (QRect(rule_left, mid, max(0, rule_right - rule_left), 1)
            if rule_right > rule_left else QRect())
    return BandLayout(label_rect, rule, count_rect, all_seg, word_seg, caret)


def paint_row(painter: QPainter, rect: QRect, index, base_font: QFont) -> bool:
    """Paint *index* if it is a section band. Returns whether it did.

    The delegate asks this one question instead of holding the band's roles,
    its layout and its colours — all of which are this module's business.
    """
    if index.data(ROW_KIND_ROLE) != "header":
        return False
    paint(painter, rect,
          label=index.data(SECTION_LABEL_ROLE) or "",
          count=int(index.data(SECTION_COUNT_ROLE) or 0),
          word_only=index.data(SECTION_WORD_ONLY_ROLE),
          collapsed=bool(index.data(SECTION_COLLAPSED_ROLE)),
          base_font=base_font)
    return True


def toggle_rects_for(rect: QRect, index, base_font: QFont):
    """``(all, word)`` for *index*, or two nulls when it offers no toggle."""
    if index.data(ROW_KIND_ROLE) != "header":
        return QRect(), QRect()
    if index.data(SECTION_WORD_ONLY_ROLE) is None:
        return QRect(), QRect()
    return toggle_rects(rect, label=index.data(SECTION_LABEL_ROLE) or "",
                        count=int(index.data(SECTION_COUNT_ROLE) or 0),
                        base_font=base_font)


def toggle_rects(rect: QRect, *, label: str, count: int, base_font: QFont):
    """``(all, word)`` hit rectangles for the segmented control.

    Recomputed from the SAME layout the paint uses rather than stashed during
    it — the reason is the one ``ChannelRowDelegate.action_rect`` gives: a
    stashed rect exists only for rows that have already been painted, and the
    first click on a freshly scrolled header is exactly the case that must work.
    """
    box = layout(rect, label=label, count=count, has_toggle=True,
                 base_font=base_font)
    return box.all_seg, box.word_seg


def paint(painter: QPainter, rect: QRect, *, label: str, count: int,
          word_only: bool | None, collapsed: bool, base_font: QFont) -> None:
    """Draw the band. ``word_only`` of None means the section offers no toggle."""
    has_toggle = word_only is not None
    box = layout(rect, label=label, count=count, has_toggle=has_toggle,
                 base_font=base_font)

    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    line = to_qcolor(_theme.COLOR_LINE)
    painter.fillRect(rect, to_qcolor(_theme.COLOR_BG_SECTION))
    painter.setPen(line)
    painter.drawLine(rect.left(), rect.top(), rect.right(), rect.top())
    painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())

    painter.setFont(_label_font(base_font))
    painter.setPen(to_qcolor(_theme.COLOR_TEXT_HI))
    painter.drawText(box.label, int(Qt.AlignmentFlag.AlignVCenter), label)

    if not box.rule.isNull():
        painter.fillRect(box.rule, line)

    small = _small_font(base_font)
    painter.setFont(small)
    painter.setPen(to_qcolor(_theme.COLOR_TEXT))
    painter.drawText(box.count, int(Qt.AlignmentFlag.AlignVCenter), f"{count:,}")

    if has_toggle:
        _paint_segment(painter, box, word_only=bool(word_only))

    painter.setFont(small)
    painter.setPen(to_qcolor(_theme.COLOR_FAINT))
    painter.drawText(box.caret, int(Qt.AlignmentFlag.AlignVCenter),
                     CARET_SHUT if collapsed else CARET_OPEN)
    painter.restore()


def _paint_segment(painter: QPainter, box: BandLayout, *, word_only: bool) -> None:
    """One track, one divide, and the active half FILLS its cell.

    Not a rounded pill floating inside a rounded box — ``ToggleChip`` states
    why: "a segmented chip fills its whole cell when selected instead of
    floating as a pill, which is what makes the active view read as the active
    view rather than as one more button." The first version of this painted the
    pill-in-a-box that rule exists to forbid.

    So the fill is clipped to the track: rounded on the track's outer end, square
    against the divide.
    """
    outer = box.all_seg.united(box.word_seg)
    on_rect = box.word_seg if word_only else box.all_seg

    path = QPainterPath()
    path.addRoundedRect(QRectF(outer), SEG_RADIUS, SEG_RADIUS)
    painter.save()
    painter.setClipPath(path)
    painter.fillRect(on_rect, to_qcolor(_theme.COLOR_ACCENT))
    painter.restore()

    line = to_qcolor(_theme.COLOR_LINE)
    painter.setPen(line)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(outer, SEG_RADIUS, SEG_RADIUS)
    # Exactly one rule per boundary, the same as the widget track.
    painter.drawLine(box.word_seg.left(), outer.top() + 1,
                     box.word_seg.left(), outer.bottom() - 1)

    for rect_, text in ((box.all_seg, ALL), (box.word_seg, WORD)):
        active = rect_ is on_rect
        font = QFont(painter.font())
        font.setWeight(QFont.Weight.DemiBold if active else QFont.Weight.Normal)
        painter.setFont(font)
        # COLOR_ON_ACCENT is the foreground for a solid COLOR_ACCENT fill —
        # never the on-background text ramp.
        painter.setPen(to_qcolor(
            _theme.COLOR_ON_ACCENT if active else _theme.COLOR_FAINT))
        painter.drawText(rect_, int(Qt.AlignmentFlag.AlignCenter), text)
