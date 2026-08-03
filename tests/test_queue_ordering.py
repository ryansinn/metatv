"""Watch Queue ordering and the unavailable group (#289).

The owner deleted a source and found items in their Watch Queue they had no
memory of adding, alongside entries marked removed — and reasonably read that as
the queue having invented content.

Investigating against the real library found no fabrication: 611 queued rows, all
pointing at live channels, 610 of 611 holding exactly the name recorded when they
were queued, no two rows sharing an insertion second (so no bulk add ever ran),
and no code path that enqueues without a click.

What was real: ``Never Watched`` rendered in raw queue ``position`` order, which
is append-only. So the top of the queue was permanently the OLDEST things ever
added — months-old entries the owner genuinely didn't recognise — while anything
queued today landed ~600 rows down. ``Continue Watching`` directly above it had
always sorted newest-first, so the two groups disagreed. Deleting the source
dimmed 37 entries scattered through that list, which is what finally drew the eye
to it.

Ordering by recency is safe here specifically because ``position`` is NOT a user
ordering: there is no reorder API and no drag-and-drop: ``add()`` only ever
appends. If a manual reorder is ever added, this sort has to give way to it.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from PyQt6.QtWidgets import QApplication

from metatv.core.repositories.queue import QueueEntry
from metatv.gui.sidebar.queue import WatchQueueSection


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


_BASE = datetime(2026, 5, 1, 12, 0, 0)


def _entry(name, *, days, played=None, available=True):
    return QueueEntry(
        queue_id=abs(hash(name)) % 100000,
        channel_id=f"ch-{name}",
        channel_name=name,
        media_type="movie",
        last_played=played,
        channel=None,
        available=available,
        search_title=name,
        added_at=_BASE + timedelta(days=days),
    )


@pytest.fixture()
def section(qapp, monkeypatch):
    """A WatchQueueSection with the real _populate_rows over a stub list widget."""
    from tests.conftest import wire_watch_queue_section

    sec = WatchQueueSection.__new__(WatchQueueSection)
    rendered: list = []
    wire_watch_queue_section(sec, rendered)
    sec._rendered = rendered
    return sec


def _rows(section) -> list[str]:
    return [v for kind, v in section._rendered if kind == "ROW"]


def _headers(section) -> list[str]:
    return [v for kind, v in section._rendered if kind == "HEADER"]


class TestNeverWatchedOrder:

    def test_newest_addition_is_first(self, section):
        """The defect: the oldest thing you ever queued sat permanently on top."""
        section._populate_rows([
            _entry("queued in May",   days=0),
            _entry("queued in June",  days=40),
            _entry("queued today",    days=90),
        ])

        assert _rows(section) == ["queued today", "queued in June", "queued in May"], (
            "queue still renders oldest-first — anything queued today is buried"
        )

    def test_it_matches_continue_watching_above_it(self, section):
        """Two adjacent groups sorting in opposite directions is incoherent."""
        section._populate_rows([
            _entry("watched old", days=0,  played=_BASE),
            _entry("watched new", days=1,  played=_BASE + timedelta(days=30)),
            _entry("queued old",  days=2),
            _entry("queued new",  days=3),
        ])

        rows = _rows(section)
        assert rows.index("watched new") < rows.index("watched old")
        assert rows.index("queued new") < rows.index("queued old")

    def test_entries_with_no_timestamp_sink_rather_than_crash(self, section):
        """Pre-migration rows can have a NULL added_at; they must not blow up
        the comparison or leapfrog dated entries."""
        undated = _entry("undated", days=0)
        undated.added_at = None
        section._populate_rows([undated, _entry("dated", days=5)])

        assert _rows(section) == ["dated", "undated"]


class TestUnavailableGroup:

    def test_dead_entries_are_grouped_at_the_bottom(self, section):
        section._populate_rows([
            _entry("gone",    days=0, available=False),
            _entry("fine",    days=1),
            _entry("gone too", days=2, available=False),
        ])

        rows = _rows(section)
        assert rows[0] == "fine", "a dead entry is still above watchable content"
        assert set(rows[1:]) == {"gone", "gone too"}

    def test_the_group_header_carries_the_count(self, section):
        section._populate_rows([
            _entry("a", days=0, available=False),
            _entry("b", days=1, available=False),
            _entry("c", days=2),
        ])

        assert "Unavailable (2)" in _headers(section), (
            f"no count in the header: {_headers(section)}"
        )

    def test_no_unavailable_header_when_everything_works(self, section):
        section._populate_rows([_entry("a", days=0), _entry("b", days=1)])
        assert not any("Unavailable" in h for h in _headers(section))

    def test_dead_entries_do_not_pollute_continue_watching(self, section):
        """A source you deleted should not sit in your Continue Watching list."""
        section._populate_rows([
            _entry("dead but played", days=0, played=_BASE, available=False),
            _entry("live and played", days=1, played=_BASE),
        ])

        rows = _rows(section)
        assert rows[0] == "live and played"
        assert rows[-1] == "dead but played"


class TestTheQueueStatesItsSize:
    """611 entries had accumulated with the size shown nowhere."""

    def test_never_watched_header_carries_the_count(self, section):
        section._populate_rows([_entry(f"m{i}", days=i) for i in range(7)])
        assert "Never Watched (7)" in _headers(section)

    def test_the_count_excludes_unavailable_entries(self, section):
        """It has to count what you can actually watch, or it overstates."""
        section._populate_rows([
            _entry("ok1", days=0),
            _entry("ok2", days=1),
            _entry("dead", days=2, available=False),
        ])
        assert "Never Watched (2)" in _headers(section)
        assert "Unavailable (1)" in _headers(section)
