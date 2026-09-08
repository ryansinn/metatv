"""STALE-1: the pure staleness judgement behind the failure toast's offer."""
from __future__ import annotations

from datetime import datetime, timedelta

from metatv.core.source_staleness import STALE_AFTER_H, is_probably_stale, stale_hint

NOW = datetime(2026, 9, 7, 12, 0, 0)


def test_never_refreshed_is_stale():
    assert is_probably_stale(None, NOW)
    assert "never been refreshed" in stale_hint("Shark", None, NOW)


def test_fresh_within_the_window_is_not_stale():
    recent = NOW - timedelta(hours=STALE_AFTER_H - 1)
    assert not is_probably_stale(recent, NOW)
    assert stale_hint("Shark", recent, NOW) is None


def test_older_than_the_window_is_stale_and_says_how_long():
    old = NOW - timedelta(days=3, hours=2)
    assert is_probably_stale(old, NOW)
    assert stale_hint("Shark", old, NOW) == (
        "Last refreshed 3 days ago — its stream links may have expired"
    )


def test_one_day_is_singular():
    assert "1 day ago" in stale_hint("Shark", NOW - timedelta(hours=STALE_AFTER_H), NOW)


def test_the_clock_is_injected_not_read():
    """Same inputs, same answer, whatever the wall clock says."""
    old = NOW - timedelta(days=2)
    assert stale_hint("Shark", old, NOW) == stale_hint("Shark", old, NOW)
    assert stale_hint("Shark", old, NOW + timedelta(days=5)).startswith("Last refreshed 7 days")
