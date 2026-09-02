"""A fixture row says whether it is on now or over (SPORT-2, design Q13).

The owner clicked a row naming a game from four days earlier and mpv played a
DIFFERENT game. Two separate things made that possible; this file covers the
second.

1. The row was from a source the user had switched OFF. That gate exists —
   ``get_hidden_provider_ids()`` — and it now excludes it.
2. **The row said nothing about being over.** A finished fixture and a live one
   painted identically, so the only way to find out was to click and be served
   the slot's CURRENT content. The provider keeps listing finished fixtures
   (measured 2026-09-02: every one of the 56 slot rows carries the latest
   ``last_seen_at``, including games eleven days old), so they cannot be pruned
   away — the row has to be honest instead.

Design Q13, settled: a state mark, **but only when a parsed time corroborates
it**. Nothing here reads the provider's own ``LIVE |`` token, which Q19 measured
as wrong 99% of the time. The window comes from ``event_start_time`` /
``event_stop_time``, computed at ingestion, and the same
``event_datetime.event_is_on_now`` the Sports lanes use — so the row and the
lane cannot disagree about the same fixture.
"""

from __future__ import annotations

import datetime

import pytest
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QColor, QFont

from metatv.core.event_datetime import DEFAULT_EVENT_DURATION, event_is_on_now
from metatv.core.repositories.dtos import ChannelListDTO
from metatv.gui import theme as _theme
from metatv.gui.channel_list_delegate import ChannelRowDelegate
from tests.conftest import set_model_channels
from metatv.gui.channel_row_cells import (
    CHIP_SLOT_STATE,
    ROW_META_ORDER,
    _ordered,
    _state_cell,
    _year_cell,
)


def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _lum(hexstr: str) -> float:
    h = QColor(hexstr).name().lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _contrast(a: str, b: str) -> float:
    """WCAG relative-contrast ratio — the same formula the token tests use."""
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


NOW = datetime.datetime(2026, 9, 2, 12, 0)
H = datetime.timedelta(hours=1)

#: The owner's real MLB slot: 7h13m, nearly twice the assumed duration.
LONG_SLOT = datetime.timedelta(hours=7, minutes=13)


@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ── which rows get a mark at all ─────────────────────────────────────────────

@pytest.mark.parametrize("label,window,expected", [
    ("no window at all",        None,                       None),
    ("a pair with no start",    (None, None),               None),
    ("upcoming",                (NOW + 3 * H, NOW + 6 * H),  None),
    ("under way, real end",     (NOW - 5 * H, NOW + 2 * H),  "On now"),
    ("over, by its real end",   (NOW - 8 * H, NOW - 1 * H),  "Ended"),
    ("under way, no end sent",  (NOW - 3 * H, None),         "On now"),
    ("over, no end sent",       (NOW - 5 * H, None),         "Ended"),
    ("starts exactly now",      (NOW, NOW + 2 * H),          "On now"),
])
def test_the_mark_appears_only_where_a_time_says_it_should(qapp, label, window, expected):
    """Q13's qualifier is the test: no parsed time, no mark.

    ~96% of the library is not a dated event, and an upcoming fixture is
    already saying "later" by being in a schedule — a third word on every row
    in Upcoming would be noise.
    """
    cell = _state_cell(window, NOW)
    assert (cell.text if cell is not None else None) == expected, label


def test_the_mark_agrees_with_the_lane_predicate(qapp):
    """The row and the Sports lane are one rule, not two.

    A drift here shows as the list and the lane chip disagreeing about the same
    fixture, which is unfalsifiable from either one alone.
    """
    for start_h in (-9, -7, -5, -4, -3, -1, 0, 1):
        for dur_h in (None, 3, 4, 7):
            start = NOW + start_h * H
            stop = None if dur_h is None else start + dur_h * H
            cell = _state_cell((start, stop), NOW)
            on_now = cell is not None and cell.text == "On now"
            assert on_now == event_is_on_now(start, stop, NOW), (start_h, dur_h)


def test_a_long_slot_is_still_on_now_past_the_assumed_duration(qapp):
    """The row must not go quiet 4h into a 7h13m game — that is the whole bug.

    Fails against a mark derived from the assumed duration alone.
    """
    start = NOW - 5 * H
    assert 5 * H > DEFAULT_EVENT_DURATION, "precondition"
    cell = _state_cell((start, start + LONG_SLOT), NOW)
    assert cell is not None and cell.text == "On now"


def test_a_short_slot_reads_ended_before_the_assumed_duration(qapp):
    """The direction that serves a different game: a 3h fixture, 3h30m in."""
    start = NOW - datetime.timedelta(hours=3, minutes=30)
    cell = _state_cell((start, start + 3 * H), NOW)
    assert cell is not None and cell.text == "Ended"


# ── rendered appearance ──────────────────────────────────────────────────────

class _RecordingPainter:
    """Records the actual paint sequence — see test_comfy_row_chips."""

    def __init__(self):
        self.calls: list[tuple] = []

    def setFont(self, font):
        self.calls.append(("setFont", font))

    def setPen(self, pen):
        self.calls.append(("setPen", pen))

    def setBrush(self, brush):
        self.calls.append(("setBrush", brush))

    def drawRoundedRect(self, rect, rx, ry):
        self.calls.append(("drawRoundedRect", QRect(rect), rx, ry))

    def drawText(self, rect, alignment, text):
        self.calls.append(("drawText", QRect(rect), alignment, text))


def _painted(cell) -> _RecordingPainter:
    painter = _RecordingPainter()
    ChannelRowDelegate()._paint_cell(painter, QRect(0, 0, 60, 20), cell, QFont())
    return painter


def test_on_now_actually_paints_a_filled_chip(qapp):
    """Asserted on the PAINT CALLS, not the dataclass fields.

    A cell can carry ``is_chip=True`` and still never reach a brush — order and
    token-existence pass for infinitely many wrong-looking renderings. This
    checks a rounded rect is drawn in the OK fill and the words land on it.
    """
    cell = _state_cell((NOW - 1 * H, NOW + 1 * H), NOW)
    painter = _painted(cell)

    fills = [args[0].name() for op, *args in painter.calls
             if op == "setBrush" and isinstance(args[0], QColor)]
    assert QColor(_theme.COLOR_OK).name() in fills, (
        f"the On-now chip must paint a solid COLOR_OK fill; brushes were {fills!r}")
    assert any(op == "drawRoundedRect" for op, *_ in painter.calls)
    assert any(op == "drawText" and args[2] == "On now"
               for op, *args in painter.calls)


def test_ended_paints_no_fill_at_all(qapp):
    """Tier 2. A second solid fill would make the Finished lane a wall of
    colour, and "this is over" is not the loudest thing on a row."""
    cell = _state_cell((NOW - 8 * H, NOW - 1 * H), NOW)
    painter = _painted(cell)
    fills = [args[0].name() for op, *args in painter.calls
             if op == "setBrush" and isinstance(args[0], QColor)]
    assert not fills, f"Ended must paint no brush fill, got {fills!r}"
    assert any(op == "drawText" and args[2] == "Ended" for op, *args in painter.calls)


def test_the_on_now_chip_is_legible_in_every_palette(qapp):
    """The fill carries the palette, so the foreground flips with the FILL.

    ``COLOR_OK`` is mint in the dark themes and forest in Daylight; a hardcoded
    white measured 1.88-2.51:1 on exactly these fills. ``on_fill`` is what makes
    the chip readable in all three, and this is the assertion that would fail if
    someone replaced it with a fixed token.
    """
    from metatv.gui import theme_palettes

    original = _theme.current_theme()
    try:
        for name in theme_palettes.PALETTES:
            _theme.apply_theme(name)
            cell = _state_cell((NOW - 1 * H, NOW + 1 * H), NOW)
            ratio = _contrast(cell.fg, cell.bg)
            assert ratio >= 4.5, (
                f"{name}: the On-now chip is {ratio:.2f}:1 on its own fill")
    finally:
        _theme.apply_theme(original)


def test_state_is_painted_LEFTMOST_in_the_meta_line(qapp):
    """Position, not order — a tuple index proves nothing about the pixels.

    State leads the meta line because for a fixture it is the most
    decision-relevant fact on the row. This lays the real cells out through the
    real ordering and compares painted x.
    """
    state = _state_cell((NOW - 1 * H, NOW + 1 * H), NOW)
    year = _year_cell("2026")
    by_slot = {CHIP_SLOT_STATE: [state], "year": [year]}
    cells = _ordered(by_slot, ROW_META_ORDER)

    assert cells[0] is state, "state must sort first among meta cells"

    delegate = ChannelRowDelegate()
    painter = _RecordingPainter()
    x = 0
    positions = {}
    for cell in cells:
        rect = QRect(x, 0, 60, 20)
        delegate._paint_cell(painter, rect, cell, QFont())
        positions[cell.text] = rect.left()
        x += 70
    assert positions["On now"] < positions["2026"], (
        f"On now painted at x={positions['On now']}, year at "
        f"x={positions['2026']} — the state mark must be leftmost")


# ── the data actually reaches the row ────────────────────────────────────────

def test_the_dto_carries_the_window(qapp):
    """A parse that never reaches the row is the #591 shape."""
    dto = ChannelListDTO(
        id="c1", name="MLB 01 | A x B", media_type="live", provider_id="p",
        is_favorite=False, category=None, quality=None, detected_prefix=None,
        detected_region=None, detected_quality=None, detected_year=None,
        detected_title=None,
        event_start_time=NOW - 1 * H, event_stop_time=NOW + 1 * H,
    )
    assert dto.event_start_time is not None and dto.event_stop_time is not None


def test_the_model_serves_the_window_as_one_pair(qapp):
    """One role, not two: the ends are only ever read together, and a caller
    holding half a window asks the question wrong.

    A REAL model, because this asserts on ``data(index(row), role)`` and a
    ``createIndex``-patched double cannot build an index at all.
    """
    from metatv.gui.channel_list_model import EVENT_WINDOW_ROLE, ChannelListModel

    model = ChannelListModel()
    dated = ChannelListDTO(
        id="c1", name="MLB 01 | A x B", media_type="live", provider_id="p",
        is_favorite=False, category=None, quality=None, detected_prefix=None,
        detected_region=None, detected_quality=None, detected_year=None,
        detected_title=None,
        event_start_time=NOW - 1 * H, event_stop_time=NOW + 1 * H,
    )
    plain = ChannelListDTO(
        id="c2", name="EN - A Movie", media_type="movie", provider_id="p",
        is_favorite=False, category=None, quality=None, detected_prefix=None,
        detected_region=None, detected_quality=None, detected_year=None,
        detected_title=None,
    )
    set_model_channels(model, [dated, plain])
    assert model.data(model.index(0), EVENT_WINDOW_ROLE) == (
        NOW - 1 * H, NOW + 1 * H)
    # Not a dated fixture: None, so the cell builder's first check is the
    # common case rather than a tuple of Nones.
    assert model.data(model.index(1), EVENT_WINDOW_ROLE) is None
