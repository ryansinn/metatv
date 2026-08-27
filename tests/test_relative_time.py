"""The "how long ago" ladder (metatv/gui/relative_time.py).

The V3 sidebar puts a time on the second line of every History row, and the
render names the rungs: "2 hours ago", "yesterday", "3 days ago", "last week",
"2 weeks ago". Injecting ``now`` is what makes these assertions about the ladder
rather than about the clock.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from metatv.gui.relative_time import humanize_ago

NOW = datetime(2026, 8, 25, 12, 0, 0)


def ago(**kw) -> str:
    return humanize_ago(NOW - timedelta(**kw), now=NOW)


@pytest.mark.parametrize("kwargs,expected", [
    (dict(seconds=5), "just now"),
    (dict(seconds=59), "just now"),
    (dict(minutes=1), "1 min ago"),
    (dict(minutes=45), "45 min ago"),
    (dict(hours=1), "an hour ago"),
    (dict(hours=2), "2 hours ago"),
    (dict(hours=23), "23 hours ago"),
    (dict(days=1), "yesterday"),
    (dict(days=1, hours=12), "yesterday"),
    (dict(days=3), "3 days ago"),
    (dict(days=6), "6 days ago"),
    (dict(days=7), "last week"),
    (dict(days=13), "last week"),
    (dict(days=14), "2 weeks ago"),
    (dict(days=28), "4 weeks ago"),
    (dict(days=30), "last month"),
    (dict(days=90), "3 months ago"),
    (dict(days=400), "last year"),
    (dict(days=1000), "2 years ago"),
])
def test_the_ladder(kwargs, expected):
    assert ago(**kwargs) == expected


def test_the_render_s_own_examples_all_come_out():
    """Every phrase the V3 sidebar render shows must be reachable."""
    produced = {ago(days=d) for d in range(30)} | {ago(hours=h) for h in range(24)}
    for phrase in ("2 hours ago", "yesterday", "3 days ago", "last week", "2 weeks ago"):
        assert phrase in produced, f"the ladder cannot produce {phrase!r}"


def test_no_timestamp_contributes_nothing():
    """``None`` yields "" so a caller can pass it straight to sidebar_meta_line.

    Returning "None" or raising would each put the word None on screen or force
    every caller to guard — a live channel that has never been played is normal.
    """
    assert humanize_ago(None) == ""
    assert humanize_ago(None, now=NOW) == ""


def test_a_future_timestamp_never_reads_as_a_negative_age():
    """Clock skew and optimistic provider stamps happen; "-3 hours ago" must not."""
    assert humanize_ago(NOW + timedelta(hours=3), now=NOW) == "just now"
    assert humanize_ago(NOW + timedelta(days=400), now=NOW) == "just now"


def test_it_never_returns_a_dangling_or_empty_phrase():
    """Every rung produces real words — a gap in the ladder would show as ""."""
    for days in range(0, 1200, 7):
        out = humanize_ago(NOW - timedelta(days=days), now=NOW)
        assert out and out.strip() == out and "None" not in out, (days, out)
