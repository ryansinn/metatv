"""One view over the dated content, with a scope switch.

``special_view`` carries three values and two are *events*: ``ppv`` (510 rows on
the owner's library) and ``live_event`` (2,319). The third, ``sports``, is
28,018 CHANNELS and has its own view — a sports channel is a place you go, an
event is a thing that happens at a time, and the countdown on every card here is
the difference.

Supersedes ``ppv_view.py``: 230 orphaned lines that queried on the UI thread,
held ORM rows in cards and read them after the session closed, and excluded no
hidden provider. Its countdown was the good part; the ladder now lives in
``relative_time.humanize_countdown`` beside the two other forward formatters.
"""

from datetime import datetime, timedelta

import pytest

from metatv.core.config import Config
from metatv.core.repositories.dtos import SpecialContentDTO
from metatv.gui.events_view import SCOPES, EventsView

_NOW = datetime(2026, 8, 30, 12, 0, 0)


def _dto(i=1, offset=None, bucket="ppv", meta=None, **over):
    base = {
        "id": f"c{i}", "name": f"RAW PROVIDER STRING {i}", "provider_id": "p",
        "media_type": "live", "special_view": bucket, "sport_type": None,
        "league_name": None, "team_name": None, "detected_title": f"T{i}",
        "detected_quality": "HD",
        "event_start_time": (_NOW + offset) if offset is not None else None,
        "event_metadata": meta,
    }
    base.update(over)
    return SpecialContentDTO(**base)


class _Runner:
    def __init__(self):
        self.calls = []

    def __call__(self, query_fn, on_result, *, token_ref=None, on_error=None):
        self.calls.append({"fn": query_fn, "ok": on_result,
                           "err": on_error, "token": token_ref})


@pytest.fixture
def view(qapp):
    runner = _Runner()
    v = EventsView(None, Config(), runner)
    v._runner = runner
    return v


def _load(view, rows):
    view.on_activate()
    view._runner.calls[-1]["ok"](list(rows))


# --------------------------------------------------------------------------
# The scope switch
# --------------------------------------------------------------------------

def test_all_is_the_default_scope(view):
    """"What is on" does not start by caring which kind of event it is."""
    assert SCOPES[0][0] == ""
    assert view._bucket == ""
    assert view.scope_buttons[""].isChecked()


def test_the_scopes_are_the_two_dated_buckets_plus_all(view):
    """Sports is NOT a scope here — it has its own view, and 28,018 channels
    would swamp 2,829 events."""
    assert [b for b, *_ in SCOPES] == ["", "ppv", "live_event"]


def test_switching_scope_requeries_and_moves_the_check(view):
    _load(view, [])
    before = len(view._runner.calls)
    view._set_bucket("ppv")
    assert len(view._runner.calls) == before + 1
    assert view.scope_buttons["ppv"].isChecked()
    assert not view.scope_buttons[""].isChecked()


def test_reselecting_the_same_scope_does_not_requery(view):
    _load(view, [])
    before = len(view._runner.calls)
    view._set_bucket("")
    assert len(view._runner.calls) == before


def test_all_asks_for_both_buckets_not_a_third_query_shape(view):
    """"All" is the union of the two, so the repository keeps one method."""
    from unittest.mock import MagicMock

    view.on_activate()
    repos = MagicMock()
    repos.providers.get_hidden_provider_ids.return_value = []
    repos.channels.get_events_channels.return_value = []
    view._runner.calls[-1]["fn"](repos)
    asked = [c.args[1] for c in repos.channels.get_events_channels.call_args_list]
    assert asked == ["ppv", "live_event"]


def test_a_single_scope_asks_for_only_that_bucket(view):
    from unittest.mock import MagicMock

    view._bucket = "ppv"
    view._reload()
    repos = MagicMock()
    repos.providers.get_hidden_provider_ids.return_value = []
    repos.channels.get_events_channels.return_value = []
    view._runner.calls[-1]["fn"](repos)
    assert [c.args[1] for c in
            repos.channels.get_events_channels.call_args_list] == ["ppv"]


def test_the_query_carries_a_resolved_visibility_scope(view):
    """A disabled source must not surface here either — same gate as Sports."""
    from unittest.mock import MagicMock

    view.on_activate()
    captured = {}
    repos = MagicMock()
    repos.providers.get_hidden_provider_ids.return_value = ["off"]
    def _capture(scope, bucket):
        captured["scope"] = scope
        return []          # NOT `... or []` — setdefault returns the scope,
                           # and the caller would then try to iterate it.

    repos.channels.get_events_channels.side_effect = _capture
    view._runner.calls[-1]["fn"](repos)
    assert "off" in captured["scope"].excluded_provider_ids


# --------------------------------------------------------------------------
# Ordering — three groups, not one sort key
# --------------------------------------------------------------------------

def test_upcoming_then_ended_then_undated(view):
    """An event with no start is not "infinitely far away" — it is a feed that
    is always on, and burying it under 900 finished fights would be the wrong
    answer to "what can I watch"."""
    rows = [
        _dto(1, timedelta(days=-2)),                 # ended, older
        _dto(2, None, "live_event"),                 # always on
        _dto(3, timedelta(days=3)),                  # upcoming, later
        _dto(4, timedelta(minutes=10)),              # upcoming, sooner
        _dto(5, timedelta(hours=-1)),                # ended, recent
    ]
    assert [d.id for d in EventsView._ordered(rows, _NOW)] == [
        "c4", "c3", "c5", "c1", "c2"]


def test_ordering_renders_in_that_order(view):
    _load(view, [_dto(1, timedelta(days=-2)), _dto(2, None),
                 _dto(3, timedelta(minutes=10))])
    assert [c.dto.id for c in view._cards] == ["c3", "c1", "c2"]


# --------------------------------------------------------------------------
# The card
# --------------------------------------------------------------------------

def test_the_title_is_the_parsed_event_name(view):
    """The channel name is "End | India tour of Sri Lanka 2026 - 2nd Test |
    all | 27-08-2026 | 00:00 (GMT) | 8K EXCLUSIVE". The classifier already
    pulled the event out of it."""
    _load(view, [_dto(1, timedelta(days=1), meta={"event_name": "Strife MMA 15"})])
    card = view._cards[0]
    assert card.title_label.text() == "Strife MMA 15"
    assert card.toolTip() == "RAW PROVIDER STRING 1", (
        "the raw string must stay reachable")


def test_the_title_falls_back_when_nothing_was_parsed(view):
    _load(view, [_dto(1, timedelta(days=1), meta=None)])
    assert view._cards[0].title_label.text() == "T1"


def test_each_bucket_shows_its_own_badges(view):
    """The two buckets carry different keys — that is the providers' doing."""
    _load(view, [
        _dto(1, timedelta(days=1), "ppv",
             meta={"quality": "8K", "sport_type": "mma"}),
        _dto(2, timedelta(days=1), "live_event",
             meta={"network": "Paramount", "region": "us"}),
    ])
    assert view._cards[0]._badge_texts() == ["8K", "MMA"]
    assert view._cards[1]._badge_texts()[:2] == ["Paramount", "US"]


def test_a_three_letter_sport_is_an_acronym(view):
    """``str.title`` renders the classifier's canonical "mma" as "Mma"."""
    _load(view, [_dto(1, timedelta(days=1), meta={"sport_type": "mma"}),
                 _dto(2, timedelta(days=1), meta={"sport_type": "soccer"})])
    assert "MMA" in view._cards[0]._badge_texts()
    assert "Soccer" in view._cards[1]._badge_texts()


def test_an_undated_feed_says_so(view):
    """923 live_event rows have availability "always" and no start. "Date
    unavailable" would be a lie about a feed that is simply always on."""
    _load(view, [_dto(1, None, "live_event")])
    card = view._cards[0]
    assert card.when_label.text() == "Always available"
    assert card.countdown_label.text() == ""


def test_the_countdown_reads_from_the_frame_not_the_clock(view):
    """One ``now`` per tick for the whole grid — a per-card ``datetime.now()``
    cannot promise that a screenful agrees with itself."""
    card_dto = _dto(1, timedelta(days=3, hours=4))
    _load(view, [card_dto])
    card = view._cards[0]
    card.refresh_countdown(_NOW)
    assert card.countdown_label.text() == "in 3d 4h"
    card.refresh_countdown(_NOW + timedelta(days=3, hours=3, minutes=50))
    assert card.countdown_label.text() == "in 10m 0s"
    card.refresh_countdown(_NOW + timedelta(days=4))
    assert card.countdown_label.text() == "ended"


# --------------------------------------------------------------------------
# Ticking
# --------------------------------------------------------------------------

def test_only_cards_under_a_day_want_ticks(view):
    """"in 3d 4h" is stable for the next hour. Repainting 2,800 of those at
    1 Hz burns the UI thread to change nothing."""
    _load(view, [_dto(1, timedelta(days=3)), _dto(2, timedelta(hours=2)),
                 _dto(3, timedelta(days=-1)), _dto(4, None)])
    wants = [c.dto.id for c in view._cards if c.wants_ticks(_NOW)]
    assert wants == ["c2"]


def test_the_timer_runs_only_while_the_view_is_active(view):
    assert not view._timer.isActive()
    view.on_activate()
    assert view._timer.isActive()
    view.on_deactivate()
    assert not view._timer.isActive(), (
        "a 1 Hz timer behind a hidden view is pure waste")


def test_deactivate_also_invalidates_an_in_flight_result(view):
    _load(view, [])
    before = view._token[0]
    view.on_deactivate()
    assert view._token[0] > before


# --------------------------------------------------------------------------
# Failure and emptiness — different facts, different words
# --------------------------------------------------------------------------

def test_a_failed_load_says_so(view):
    view.on_activate()
    view._runner.calls[-1]["err"](RuntimeError("boom"))
    assert "Couldn't load" in view.message_label.text()
    assert view._cards == []


def test_a_none_result_is_also_a_failure(view):
    view.on_activate()
    view._runner.calls[-1]["ok"](None)
    assert "Couldn't load" in view.message_label.text()


def test_an_empty_scope_is_not_a_failure(view):
    """CLAUDE.md: never ``clear(); return``. But "none here" and "it broke" are
    different facts and must not share a sentence."""
    _load(view, [])
    assert "No events" in view.message_label.text()
    assert "Couldn't load" not in view.message_label.text()


# --------------------------------------------------------------------------
# Interaction
# --------------------------------------------------------------------------

def test_the_play_button_emits_the_channel_id(view):
    _load(view, [_dto(1, timedelta(days=1))])
    seen = []
    view.playRequested.connect(seen.append)
    view._cards[0].play_button.click()
    assert seen == ["c1"]


def test_no_signal_carries_an_orm_object():
    """``ppv_view`` emitted ``play_channel_requested(object)`` with a ChannelDB
    — an ORM row across a signal, read on the main thread after its session
    closed."""
    for name in ("channelSelected", "playRequested", "channelMiddleClicked"):
        # PyQt renders a `str` argument as QString in the signal's repr.
        assert "QString" in str(getattr(EventsView, name)), (
            f"{name} should carry a channel_id, not an object")


# --------------------------------------------------------------------------
# Rendered appearance
# --------------------------------------------------------------------------

def test_a_card_is_painted_with_real_size(view, qapp):
    """Membership passes for a zero-size card."""
    _load(view, [_dto(1, timedelta(days=1), meta={"event_name": "Strife MMA 15"})])
    view.resize(760, 500)
    view.show()
    qapp.processEvents()

    card = view._cards[0]
    geo = card.geometry()
    assert geo.width() == card._CARD_W, (
        f"card width {geo.width()} — a fixed-width card that is not its width "
        "means the flow layout is fighting it")
    assert geo.height() > 60, f"card height {geo.height()}px — nothing painted"
    assert card.title_label.geometry().top() < card.play_button.geometry().top(), (
        "the title must sit above the Play button")


def test_cards_flow_onto_more_than_one_row(view, qapp):
    """A FlowLayout that never wraps is a column with extra steps."""
    _load(view, [_dto(i, timedelta(days=i)) for i in range(1, 7)])
    view.resize(760, 900)
    view.show()
    qapp.processEvents()
    tops = {c.geometry().top() for c in view._cards}
    assert len(tops) > 1, "every card landed on one row — the layout did not wrap"


def test_the_view_is_registered_and_in_the_one_view_list():
    from pathlib import Path

    import metatv.gui.main_window as mw
    import metatv.gui.main_window_nav as nav
    from metatv.gui.app_header import NAV_CHIP_SPECS

    main = Path(mw.__file__).read_text()
    assert "self.events_view = EventsView(" in main
    assert "self._list_layout.addWidget(self.events_view)" in main
    assert "events_view" in nav.CONTENT_VIEW_ATTRS
    assert any(attr == "events_chip" for attr, *_ in NAV_CHIP_SPECS)

    navsrc = Path(nav.__file__).read_text()
    assert "def switch_to_events_view" in navsrc
    assert "def on_events_view_toggle" in navsrc


def test_ppv_view_is_gone():
    """Two views over the same rows is the duplication the ledger tracks."""
    import importlib

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("metatv.gui.ppv_view")


def test_the_count_says_how_much_is_still_ahead(view):
    """Often the answer is "none": every one of the owner's 408 ppv rows has a
    start time in the past. A bare "408 events" over a screen of finished
    fights reads as a bug in the view rather than a fact about the catalogue."""
    assert EventsView._count_line(
        [_dto(1, timedelta(days=-1)), _dto(2, timedelta(days=-2))], _NOW
    ) == "2 events · none upcoming"
    assert EventsView._count_line(
        [_dto(1, timedelta(days=1)), _dto(2, timedelta(days=-2))], _NOW
    ) == "2 events · 1 upcoming"
    assert EventsView._count_line([_dto(1, timedelta(days=1))], _NOW) == (
        "1 event · 1 upcoming")
    assert EventsView._count_line([], _NOW) == ""


def test_an_undated_feed_is_not_counted_as_upcoming(view):
    """"Always available" is not a future event — it is on now."""
    assert EventsView._count_line([_dto(1, None)], _NOW) == "1 event · none upcoming"


# ---------------------------------------------------------------------------
# Title box — rendered geometry, not token existence (owner report 2026-08-31)
# ---------------------------------------------------------------------------

def _long_title_card(qapp):
    """A card whose title is a real fixture name — the reported case."""
    from datetime import datetime, timedelta

    from metatv.gui.events_view import _EventCard

    title = ("Manchester United v Ipswich Town  Premier League "
             "Matchweek 2 2026/2027")
    dto = _dto(detected_title=title, name=title,
               event_start_time=datetime.now() + timedelta(hours=1))
    card = _EventCard(dto, None)
    card.adjustSize()
    qapp.processEvents()
    return card, title


def test_a_long_event_title_is_not_clipped_mid_glyph(qapp):
    """The reported defect: titles "too large and unreadable".

    The title was styled with ``DIALOG_TITLE`` — 17px bold, correct for the top
    of a modal — so a fixture name wrapped to three lines inside a box a wrapped
    QLabel had size-hinted for one, and was cut through the middle of the
    glyphs, top and bottom.

    Asserts the PAINTED box is a whole number of lines. A test on the token
    ("is the font 15px?") passes for a box of any height, including the broken
    one, which is the distinction this file's other geometry tests already make.
    """
    card, _ = _long_title_card(qapp)
    label = card.title_label
    line = label.fontMetrics().lineSpacing()

    assert label.height() == line * 2, (
        f"title box is {label.height()}px against a {line}px line — a box that "
        f"is not a whole number of lines clips through the glyphs")


def test_the_title_box_does_not_depend_on_the_title(qapp):
    """Every card in the grid must be the same height.

    A wrapped label that sizes to its content makes each tile a different
    height, which is what produced the ragged grid in the report alongside the
    clipping.
    """
    from datetime import datetime, timedelta

    from metatv.gui.events_view import _EventCard

    heights = set()
    for title in ("A", "Race 2: Grand Prix of Milwaukee",
                  "Manchester United v Ipswich Town  Premier League "
                  "Matchweek 2 2026/2027"):
        dto = _dto(detected_title=title, name=title,
                   event_start_time=datetime.now() + timedelta(hours=1))
        heights.add(_EventCard(dto, None).sizeHint().height())

    assert len(heights) == 1, f"cards vary in height by title: {heights}"


def test_the_full_title_stays_reachable(qapp):
    """Two lines is a cap, so the text it cuts has to survive somewhere."""
    card, title = _long_title_card(qapp)
    assert card.title_label.toolTip() == title


def test_the_card_title_is_not_a_dialog_heading(qapp):
    """It was literally ``EVENT_CARD_TITLE = DIALOG_TITLE``.

    Guarding the alias, not the pixel value: an improvement is free to move the
    size, but re-pointing a card title at the modal-heading role is the specific
    regression, and it is invisible until someone opens Events.
    """
    from metatv.gui import theme as _t

    assert _t.EVENT_CARD_TITLE != _t.DIALOG_TITLE, (
        "the event card title is aliased to the dialog heading role again")
