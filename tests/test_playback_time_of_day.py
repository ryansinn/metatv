"""Failures by time of day (Source Analytics Q11): counted per LOCAL hour,
put into words, and painted as a 24-column strip once 30 plays exist."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from tests.conftest import destroy_widget
from tests.test_source_analytics_tab import _analytics, _seed, _texts


@pytest.fixture()
def file_db(tmp_path):
    from metatv.core.database import Database
    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.create_tables()
    yield d
    d.close()


def _hours(**cells: tuple[int, int]) -> tuple[tuple[int, int], ...]:
    """24 (attempts, failures) cells, 5 clean plays an hour unless given as hNN."""
    return tuple(cells.get(f"h{h:02d}", (5, 0)) for h in range(24))


def test_an_evening_run_is_named():
    from metatv.gui.hour_strip import struggle_span
    with patch("metatv.core.time_display._style", {"clock": "24h", "date": "iso"}):
        assert struggle_span(_hours(h20=(6, 4), h21=(6, 5), h22=(5, 3))) == "20:00–23:00"


def test_a_run_past_midnight_is_one_run():
    from metatv.gui.hour_strip import struggle_span
    with patch("metatv.core.time_display._style", {"clock": "24h", "date": "iso"}):
        assert struggle_span(_hours(h23=(5, 4), h00=(5, 4), h01=(5, 4))) == "23:00–02:00"


def test_one_failed_play_in_a_quiet_hour_is_not_a_pattern():
    from metatv.gui.hour_strip import struggle_span
    assert struggle_span(_hours(h04=(1, 1))) is None


def test_a_source_that_fails_everywhere_has_no_bad_hour():
    from metatv.gui.hour_strip import struggle_span
    assert struggle_span(tuple((5, 3) for _ in range(24))) is None


def _record(db, plays):
    from metatv.core.repositories import RepositoryFactory
    with db.session_scope() as s:
        repo = RepositoryFactory(s).playback_events
        for when, outcome in plays:
            repo.record(provider_id="trex", channel_id="c", title="t", outcome=outcome, started_at=when)


def test_the_summary_counts_by_local_hour(file_db):
    from metatv.core.repositories import RepositoryFactory
    _seed(file_db)
    # 19:30 UTC is 21:30 at UTC+2.
    _record(file_db, [(datetime(2026, 10, 20, 19, 30), "refused"),
                      (datetime(2026, 10, 21, 19, 10), "started")])
    with patch("metatv.core.epg_utils._local_tz", return_value=timezone(timedelta(hours=2))):
        with file_db.session_scope() as s:
            by_hour = RepositoryFactory(s).playback_events.summary("trex").by_hour
    assert by_hour[21] == (2, 1)
    assert sum(a for a, _ in by_hour) == 2


def test_too_few_plays_says_how_many_more(qapp, file_db):
    _seed(file_db)
    _record(file_db, [(datetime(2026, 10, 20, 12, 0), "started")] * 4)
    ed = _analytics(qapp, file_db)
    try:
        from metatv.gui.hour_strip import HourStrip
        assert any("shown once 30 plays are recorded (4 so far)" in t for t in _texts(ed._analytics_tab._playback))
        assert not ed._analytics_tab._playback.findChildren(HourStrip)
    finally:
        destroy_widget(ed)


def test_the_strip_paints_the_bad_hour_tall_and_a_clean_hour_flat(qapp, file_db):
    from metatv.gui import theme as _theme
    from metatv.gui.hour_strip import HourStrip
    from metatv.gui.token_color import to_qcolor
    _seed(file_db)
    utc = timezone.utc
    plays = [(datetime(2026, 10, 20, 9, 0), "started")] * 30
    plays += [(datetime(2026, 10, 20, 21, 0), "never_started")] * 4 + [(datetime(2026, 10, 20, 21, 5), "started")]
    _record(file_db, plays)
    with patch("metatv.core.epg_utils._local_tz", return_value=utc):
        ed = _analytics(qapp, file_db)
    try:
        playback = ed._analytics_tab._playback
        assert any(t.startswith("Failures by time of day — struggles") for t in _texts(playback))
        (strip,) = playback.findChildren(HourStrip)
        img = strip.grab().toImage()
        warn = to_qcolor(_theme.COLOR_WARN).name()

        def warn_rows(hour: int) -> int:
            r = strip.column_rect(hour)
            x = r.center().x()
            return sum(img.pixelColor(x, y).name() == warn for y in range(r.top(), r.bottom() + 1))

        bad, clean = strip.column_rect(21), strip.column_rect(9)
        assert warn_rows(21) == pytest.approx(bad.height() * 0.8, abs=2)   # 4 of 5 failed
        assert warn_rows(9) == 0 and clean.height() > 10                     # 30 clean plays
    finally:
        destroy_widget(ed)
