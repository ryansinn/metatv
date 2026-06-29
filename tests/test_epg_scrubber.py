"""Behavioral tests for the EPG Browse Phase-2 timeline scrubber.

Three layers are pinned, mirroring ``tests/test_epg_browse_forward.py``:

1. Repository — ``EpgRepository.get_guide_bounds`` returns the scoped guide's
   (earliest, latest) start, honouring ``excluded_channel_provider_ids``; and
   ``get_schedule_forward(floor_to_now=False)`` lets the scrubber seek back into
   the bounded recent past (still capped by ``max_age``).
2. Pure time math — ``epg_utils`` scrubber helpers: snap a time to 15/30/60-minute
   grids (and back), size the track bounds, and format local day-context labels.
3. UI wiring — ``_EpgBrowseMixin``: dragging the handle reloads anchored at the
   snapped time; scrolling maps the topmost visible programme onto the handle; the
   seek↔scroll feedback loop is guarded; the snap increment is config-driven and
   persists.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from metatv.core.database import ChannelDB, Database, EpgProgramDB, ProviderDB
from metatv.core.repositories.epg import EpgRepository
from metatv.core.epg_utils import (
    EPG_SCRUBBER_INCREMENTS,
    scrubber_bounds,
    scrubber_label,
    scrubber_time_for,
    scrubber_value_for,
)
from metatv.gui.epg_browse_mixin import _EpgBrowseMixin, _START_ROLE


_NOW = datetime(2026, 6, 28, 12, 0, 0)  # UTC-naive reference "now" (a Sunday)


# ===========================================================================
# 1. Repository
# ===========================================================================

@pytest.fixture()
def bounds_db(tmp_path):
    """File-backed DB: feed p1 (visible) cross-matches into hidden provider p2.

    All EPG rows carry provider_id="p1" (the feed). Channel c1 belongs to the
    visible provider p1; c2 belongs to the hidden provider p2. One future row is
    unmatched (channel_db_id NULL) and must never count toward the bounds.
    """
    db = Database(f"sqlite:///{tmp_path / 'epg_bounds.db'}")
    db.create_tables()
    with db.session_scope() as s:
        s.add(ProviderDB(id="p1", name="Visible", type="xtream", url="http://a",
                         username="u", password="p", is_active=True))
        s.add(ProviderDB(id="p2", name="Hidden", type="xtream", url="http://b",
                         username="u", password="p", is_active=False))
        s.add(ChannelDB(id="c1", source_id="s1", provider_id="p1", name="ESPN HD",
                        detected_title="ESPN"))
        s.add(ChannelDB(id="c2", source_id="s2", provider_id="p2", name="FOX HD",
                        detected_title="FOX"))

        def _prog(cid, title, start, *, matched=True):
            s.add(EpgProgramDB(
                provider_id="p1",
                channel_epg_id=f"{cid}.epg",
                channel_db_id=(cid if matched else None),
                channel_name=cid,
                title=title,
                description="",
                start_time=start,
                stop_time=start + timedelta(hours=1),
            ))

        _prog("c1", "Earliest", _NOW - timedelta(hours=2))      # min for c1
        _prog("c1", "Mid",      _NOW + timedelta(hours=1))
        _prog("c1", "Latest c1", _NOW + timedelta(hours=3))     # max when p2 excluded
        _prog("c2", "Hidden Far", _NOW + timedelta(hours=5))    # max when p2 included
        _prog("c1", "Unmatched", _NOW + timedelta(hours=10), matched=False)
    return db


def test_guide_bounds_returns_min_and_max_start(bounds_db):
    """(a) Bounds span the scoped, matched rows' earliest→latest start."""
    session = bounds_db.get_session()
    try:
        lo, hi = EpgRepository(session).get_guide_bounds(["p1"])
        assert lo == _NOW - timedelta(hours=2), "earliest matched start"
        assert hi == _NOW + timedelta(hours=5), "latest matched start (incl. cross-match)"
    finally:
        session.close()


def test_guide_bounds_respects_exclusion(bounds_db):
    """(b) Excluding the hidden provider's channels pulls the right edge in."""
    session = bounds_db.get_session()
    try:
        lo, hi = EpgRepository(session).get_guide_bounds(
            ["p1"], excluded_channel_provider_ids={"p2"},
        )
        assert lo == _NOW - timedelta(hours=2)
        assert hi == _NOW + timedelta(hours=3), "hidden cross-matched row dropped"
    finally:
        session.close()


def test_guide_bounds_empty_when_no_providers(bounds_db):
    """(c) No scoped providers → (None, None), not an error."""
    session = bounds_db.get_session()
    try:
        assert EpgRepository(session).get_guide_bounds([]) == (None, None)
    finally:
        session.close()


def test_forward_floor_off_shows_bounded_past(bounds_db):
    """(d) floor_to_now=False lets the scrubber seek back; max_age still bounds it."""
    session = bounds_db.get_session()
    try:
        repo = EpgRepository(session)
        # Seek back to now-3h with a 4h window → the now-2h row is included.
        back = repo.get_schedule_forward(
            ["p1"], anchor=_NOW - timedelta(hours=3),
            max_age=timedelta(hours=4), floor_to_now=False, _now=_NOW,
        )
        assert "Earliest" in {p.title for p in back}, "past row must surface when seeking back"

        # A tighter 1h window re-excludes the now-2h row (max_age is the hard floor).
        tight = repo.get_schedule_forward(
            ["p1"], anchor=_NOW - timedelta(hours=3),
            max_age=timedelta(hours=1), floor_to_now=False, _now=_NOW,
        )
        assert "Earliest" not in {p.title for p in tight}

        # Default (floor_to_now=True) never shows the past — Phase-1 contract intact.
        fwd = repo.get_schedule_forward(["p1"], anchor=_NOW - timedelta(hours=3), _now=_NOW)
        assert all(p.start_time >= _NOW for p in fwd)
        assert "Earliest" not in {p.title for p in fwd}
    finally:
        session.close()


# ===========================================================================
# 2. Pure time math (epg_utils)
# ===========================================================================

@pytest.mark.parametrize("increment, expected_minutes", [
    (15, 30),   # round(37/15)=2 → 30m
    (30, 30),   # round(37/30)=1 → 30m
    (60, 60),   # round(37/60)=1 → 60m
])
def test_scrubber_snaps_drag_to_increment(increment, expected_minutes):
    """A time is snapped to the nearest increment-grid boundary, round-trip stable."""
    left = _NOW
    target = _NOW + timedelta(minutes=37)
    value = scrubber_value_for(left, target, increment)
    snapped = scrubber_time_for(left, value, increment)
    assert snapped == _NOW + timedelta(minutes=expected_minutes)
    # Round-trip: a snapped time maps to the same value it came from.
    assert scrubber_value_for(left, snapped, increment) == value


def test_scrubber_increment_choices():
    """The Settings choices are exactly 15 / 30 / 60, with 30 as the middle option."""
    assert EPG_SCRUBBER_INCREMENTS == [15, 30, 60]


def test_scrubber_bounds_window_and_clamps():
    """Back-browse window extends left; result clamped to guide_start & now.

    (With ``oldest_airing_start`` omitted the default left edge is ``now``; the
    back-browse window then pulls it further back — see the dedicated test below for
    the oldest-currently-airing default.)
    """
    # Past data present, 24h window → left pulled to now-10h (guide_start dominates).
    left, right = scrubber_bounds(
        _NOW - timedelta(hours=10), _NOW + timedelta(hours=48), 24, _now=_NOW,
    )
    assert left == _NOW - timedelta(hours=10)
    assert right == _NOW + timedelta(hours=48)

    # window=0, nothing airing → left == now (no extra back-browse).
    left0, _ = scrubber_bounds(
        _NOW - timedelta(hours=10), _NOW + timedelta(hours=48), 0, _now=_NOW,
    )
    assert left0 == _NOW

    # guide_start in the future → left clamps down to now (handle-at-now stays in range).
    left_fut, _ = scrubber_bounds(
        _NOW + timedelta(hours=2), _NOW + timedelta(hours=48), 24, _now=_NOW,
    )
    assert left_fut == _NOW

    # No data → collapse to a point at now.
    assert scrubber_bounds(None, None, 24, _now=_NOW) == (_NOW, _NOW)


def test_scrubber_bounds_default_left_is_oldest_airing_then_extends():
    """Default left edge = oldest currently-airing start; a non-zero back-browse
    window reaches further into the past."""
    min_start = _NOW - timedelta(hours=10)   # an already-ended row sits this far back
    max_start = _NOW + timedelta(hours=48)
    oldest_airing = _NOW - timedelta(hours=2)  # the oldest show on right now

    # Default (window=0): left bound is exactly the oldest currently-airing start —
    # you can scrub back to the start of everything on now, but no further.
    left, _ = scrubber_bounds(min_start, max_start, 0, oldest_airing, _now=_NOW)
    assert left == _NOW - timedelta(hours=2)

    # Non-zero window (6 h) reaches further back than the oldest-airing default.
    left6, _ = scrubber_bounds(min_start, max_start, 6, oldest_airing, _now=_NOW)
    assert left6 == _NOW - timedelta(hours=6)

    # The window can never reach before the guide's earliest real data.
    left_far, _ = scrubber_bounds(min_start, max_start, 100, oldest_airing, _now=_NOW)
    assert left_far == _NOW - timedelta(hours=10)

    # Nothing airing (oldest_airing=None) + window=0 → left falls back to now.
    left_none, _ = scrubber_bounds(min_start, max_start, 0, None, _now=_NOW)
    assert left_none == _NOW


def test_scrubber_label_day_context(monkeypatch):
    """Local day-context labels: Today/Tonight/Tomorrow/Yesterday/weekday."""
    monkeypatch.setattr("metatv.core.epg_utils._local_tz", lambda: timezone.utc)
    assert scrubber_label(_NOW + timedelta(hours=2), _now=_NOW).startswith("Today")
    assert scrubber_label(_NOW + timedelta(hours=8), _now=_NOW).startswith("Tonight")
    assert scrubber_label(_NOW + timedelta(days=1), _now=_NOW).startswith("Tomorrow")
    assert scrubber_label(_NOW - timedelta(days=1), _now=_NOW).startswith("Yesterday")
    weekday = (_NOW + timedelta(days=3)).strftime("%A")
    assert scrubber_label(_NOW + timedelta(days=3), _now=_NOW).startswith(weekday)


# ===========================================================================
# 3. UI wiring — _EpgBrowseMixin
# ===========================================================================

class _FakeSlider:
    """Minimal QSlider stand-in. setValue emulates Qt by firing valueChanged."""

    def __init__(self, host):
        self._host = host
        self._value = 0
        self._min = 0
        self._max = 10_000
        self._down = False
        self.enabled = True
        self.set_calls: list[int] = []

    def value(self):
        return self._value

    def setValue(self, v):
        self._value = v
        self.set_calls.append(v)
        self._host._on_scrubber_value_changed(v)  # emulate the signal

    def minimum(self):
        return self._min

    def maximum(self):
        return self._max

    def isSliderDown(self):
        return self._down

    def setRange(self, lo, hi):
        self._min, self._max = lo, hi

    def setTickInterval(self, _n):
        pass

    def setEnabled(self, flag):
        self.enabled = flag


def _make_scrubber_host(*, left=_NOW, increment=30, provider_ids=("p1",)):
    host = _EpgBrowseMixin.__new__(_EpgBrowseMixin)
    host._provider_ids = list(provider_ids)
    host._filtered_provider_ids = lambda: host._provider_ids
    host.search_input = SimpleNamespace(text=lambda: "")
    host.anchor_combo = SimpleNamespace(currentData=lambda: None)
    host.hide_filler_btn = SimpleNamespace(isChecked=lambda: False)
    host.submitted = []
    host._executor = SimpleNamespace(submit=lambda fn, *a: host.submitted.append((fn, a)))
    host._data_loaded = SimpleNamespace(emit=lambda p: None)
    host._scrubber_left = left
    host._scrubber_right = left + timedelta(hours=48)
    host._scrubber_increment = increment
    host._scrubber_ready = True
    host._scrubber_syncing = False
    host._last_seek_value = None
    host._scrubber_pos_label = None  # labels no-op (guard returns early)
    host._browse_scrubber = _FakeSlider(host)
    return host


def test_drag_seeks_to_snapped_anchor():
    """Releasing the handle reloads the list anchored at the handle's snapped time."""
    host = _make_scrubber_host(increment=30)
    host._browse_scrubber._value = 3  # user dragged to step 3 → +90m
    _EpgBrowseMixin._scrubber_seek(host)
    assert len(host.submitted) == 1
    fn, args = host.submitted[0]
    assert fn == host._fetch_browse
    _provider_ids, anchor, _search, _hide, after, append, _gen = args
    assert anchor == _NOW + timedelta(minutes=90), "anchor = snapped handle time"
    assert after is None and append is False


def test_drag_anchor_lands_on_increment_grid():
    """With a 15-minute increment the seek anchor is always a 15-minute multiple."""
    host = _make_scrubber_host(increment=15)
    host._browse_scrubber._value = 5  # +75m
    _EpgBrowseMixin._scrubber_seek(host)
    anchor = host.submitted[0][1][1]
    offset_min = int((anchor - _NOW).total_seconds() // 60)
    assert offset_min == 75
    assert offset_min % 15 == 0


def test_seek_deduped_when_value_unchanged():
    """A second release at the same step does not issue a duplicate reload."""
    host = _make_scrubber_host()
    host._browse_scrubber._value = 4
    _EpgBrowseMixin._scrubber_seek(host)
    _EpgBrowseMixin._scrubber_seek(host)  # same value → no-op
    assert len(host.submitted) == 1


def test_scroll_maps_topmost_programme_onto_handle():
    """Scrolling moves the handle to the topmost visible programme's start time."""
    host = _make_scrubber_host(increment=30)
    top_start = _NOW + timedelta(minutes=90)
    fake_item = SimpleNamespace(
        data=lambda col, role: top_start if role == _START_ROLE else None
    )
    host.browse_list = SimpleNamespace(itemAt=lambda x, y: fake_item)

    _EpgBrowseMixin._sync_scrubber_to_scroll(host)

    assert host._browse_scrubber.value() == 3, "90m / 30m increment = step 3"
    # Scroll-driven move must NOT seek (feedback-loop guard).
    assert host.submitted == []
    assert host._scrubber_syncing is False
    assert host._last_seek_value == 3


def test_no_seek_scroll_feedback_loop():
    """A scroll-driven handle move, then a release at that position, never reloads."""
    host = _make_scrubber_host(increment=30)
    top_start = _NOW + timedelta(minutes=60)
    host.browse_list = SimpleNamespace(
        itemAt=lambda x, y: SimpleNamespace(
            data=lambda col, role: top_start if role == _START_ROLE else None
        )
    )
    _EpgBrowseMixin._sync_scrubber_to_scroll(host)   # programmatic setValue fires handler
    assert host.submitted == []                       # guard suppressed the seek
    _EpgBrowseMixin._scrubber_seek(host)              # release at the synced position
    assert host.submitted == [], "release after scroll-sync is a no-op (deduped)"


def test_value_changed_while_syncing_does_not_seek():
    """A programmatic value change (syncing flag set) never triggers a reload."""
    host = _make_scrubber_host()
    host._scrubber_syncing = True
    _EpgBrowseMixin._on_scrubber_value_changed(host, 7)
    assert host.submitted == []


# ===========================================================================
# Config persistence
# ===========================================================================

def test_scrubber_increment_default_is_30():
    from metatv.core.config import Config
    assert Config().epg_scrubber_increment_minutes == 30


def test_scrubber_increment_persists_and_restores():
    """The snap increment round-trips through save()/load() (isolated tmp home)."""
    from metatv.core.config import Config

    cfg = Config()
    cfg.epg_scrubber_increment_minutes = 60
    cfg.save()

    cfg2, _ = Config.load()
    assert cfg2.epg_scrubber_increment_minutes == 60
