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
from metatv.gui.chip_row import row_title_label
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


def _real_row_title(section, item) -> str:
    """Title text of one item in a REAL ``QListWidget`` — a header's own text,
    or a chip row's title label (mirrors ``test_sidebar_in_place_removal.py``)."""
    widget = section._list.itemWidget(item)
    if widget is None:
        return item.text()
    label = row_title_label(widget)
    return label.text() if label is not None else ""


def _real_texts(section) -> list[str]:
    return [_real_row_title(section, section._list.item(i)) for i in range(section._list.count())]


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


class TestChunkedBuild:
    """PERF-17: the owner's 666-entry Watch Queue froze the main thread
    building one chip row per entry synchronously — sampled 4x in one launch,
    worst 3,753ms. ``_populate_rows`` now streams rows through
    ``build_chunked`` in batches of 40. These use a REAL ``WatchQueueSection``
    over a REAL ``QListWidget`` (the stub in ``section`` above fakes out row
    construction entirely, which is exactly what these need to observe).
    """

    def _real_section(self, qapp):
        from metatv.core.config import Config
        sec = WatchQueueSection(Config(), db=None)
        sec.resize(260, 480)
        sec.show()
        QApplication.processEvents()
        return sec

    def _built_row_count(self, sec) -> int:
        return sum(
            1 for i in range(sec._list.count())
            if sec._list.itemWidget(sec._list.item(i)) is not None
        )

    def _pump_until_done(self, sec, max_iterations: int = 200) -> None:
        for _ in range(max_iterations):
            if sec._build_handle.done:
                return
            QApplication.processEvents()
        raise AssertionError("chunked build never finished")

    def test_first_batch_renders_before_the_rest_arrives(self, qapp):
        """The rendered-construction assertion: an actual batch's worth of row
        WIDGETS exists before the event loop has had a single turn."""
        sec = self._real_section(qapp)
        entries = [_entry(f"m{i}", days=i) for i in range(120)]

        sec._populate_rows(entries)

        assert self._built_row_count(sec) == 40, (
            "expected exactly one batch of row widgets before any event processing"
        )

        self._pump_until_done(sec)

        assert self._built_row_count(sec) == 120
        assert "Never Watched (120)" in _real_texts(sec)
        sec.hide()

    def test_a_refresh_mid_build_cancels_the_old_one_no_duplicates(self, qapp):
        """The bug this exists to prevent: a refresh (second data-ready) while
        the first build is still streaming in must not leave any of the
        superseded build's later rows mixed into the new one. Mirrors what
        ``BackgroundRefreshMixin._on_data_ready`` actually does: clear the
        list, then populate."""
        sec = self._real_section(qapp)

        sec._list.clear()
        sec._populate_rows([_entry(f"old{i}", days=i) for i in range(120)])
        old_handle = sec._build_handle
        assert self._built_row_count(sec) == 40

        sec._list.clear()
        sec._populate_rows([_entry(f"new{i}", days=i) for i in range(50)])

        assert old_handle._cancelled is True

        self._pump_until_done(sec)

        rows = [
            _real_row_title(sec, sec._list.item(i))
            for i in range(sec._list.count())
            if sec._list.itemWidget(sec._list.item(i)) is not None
        ]
        assert len(rows) == 50
        assert all(t.startswith("new") for t in rows), (
            f"a superseded row from the old build leaked in: {rows}"
        )
        sec.hide()

    def test_filter_hides_a_later_batch_row_as_it_arrives(self, qtbot, qapp):
        """A row that fails an ACTIVE filter must be hidden the moment it is
        built, even when it arrives in the second (or later) batch — not only
        once the whole build finishes and the final ``_apply_filter`` sweep
        runs.

        Records each row's hidden state the INSTANT ``_build_queue_row``
        builds it, rather than inspecting ``_list`` afterwards: the section's
        UNRELATED row-budget mechanism (``row_budget.py``'s
        ``apply_row_budget``) unhides every row on its own schedule (a resize
        event), which would otherwise race this assertion and prove nothing
        about the filter specifically.
        """
        sec = self._real_section(qapp)
        entries = [
            _entry(f"keep {i}" if i % 2 == 0 else f"skip {i}", days=i)
            for i in range(120)
        ]
        sec._set_filter_visible(True, save=False)
        sec._filter.setText("keep")

        seen: list[tuple[str, bool]] = []
        real_build_row = sec._build_queue_row

        def spy(work_item):
            real_build_row(work_item)
            item, haystack = work_item.group.rows[-1]
            seen.append((haystack, item.isHidden()))

        sec._build_queue_row = spy
        sec._populate_rows(entries)

        qtbot.waitUntil(lambda: sec._build_handle.done, timeout=2000)

        assert len(seen) == 120
        batch_2_plus = seen[40:]
        assert batch_2_plus, "no rows were built past the first batch"
        skip_rows = [hidden for haystack, hidden in batch_2_plus if "skip" in haystack]
        keep_rows = [hidden for haystack, hidden in batch_2_plus if "keep" in haystack]
        assert skip_rows and all(skip_rows), (
            "a later-batch row failing the filter was not hidden AS it was built"
        )
        assert keep_rows and not any(keep_rows), (
            "a later-batch row matching the filter was wrongly hidden AS it was built"
        )
        sec.hide()
