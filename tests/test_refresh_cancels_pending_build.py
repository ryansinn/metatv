"""A refresh landing mid-build must cancel the chunked queue build (SIGABRT).

Owner crash, 2026-10-01:

    File "metatv/gui/sidebar/queue.py", line 520, in _on_queue_build_done
        self._apply_filter(self._filter_box_text())
    File "metatv/gui/sidebar/queue.py", line 585, in _apply_filter
        item.setHidden(not match)
    RuntimeError: wrapped C/C++ object of type QListWidgetItem has been deleted

#838 made ``_on_data_ready`` cancel before it clears, but
``BackgroundRefreshMixin.refresh()`` clears the list too — to show "Loading…" —
and did not. A refresh kicked while the queue's rows were still being built
deleted them under the build, whose ``on_done`` then filtered deleted items.
The same stale groups were reachable by typing in the find-in-queue box while
"Loading…" showed.

Drives the REAL ``refresh``/``_populate_rows``/``_apply_filter`` on a
``WatchQueueSection`` skeleton with a real ``QListWidget`` and a real chunked
build.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from PyQt6.QtWidgets import QListWidget, QListWidgetItem

from metatv.gui.sidebar import background_refresh
from metatv.gui.sidebar.queue import WatchQueueSection
from tests.conftest import wire_watch_queue_filter


def _entry(n: int) -> SimpleNamespace:
    return SimpleNamespace(
        available=True, last_played=None, added_at=datetime(2026, 9, 1),
        search_title=f"title {n}", channel_name=f"title {n}",
        episode_title=None, detected_year=None,
    )


def _queue_section(lst: QListWidget, monkeypatch) -> WatchQueueSection:
    """A queue section whose row builders add real items to a real list."""
    sec = WatchQueueSection.__new__(WatchQueueSection)
    sec._list = lst
    wire_watch_queue_filter(sec)
    sec._available_unviewed = 0
    sec.update_new_match_count = lambda *a, **k: None
    sec.set_empty = lambda *a, **k: None

    def _header(text, count=None):
        item = QListWidgetItem(text)
        lst.addItem(item)
        return item, SimpleNamespace(set_count=lambda c: None)

    def _row(e):
        item = QListWidgetItem(e.channel_name)
        lst.addItem(item)
        return item

    sec._add_header = _header
    sec._add_entry_item = _row
    # refresh()'s own collaborators: no real executor, scroll or loading row.
    monkeypatch.setattr(background_refresh.migration_gate, "is_running", lambda: False)
    sec._capture_scroll = lambda l: None
    sec.show_loading = lambda l, m: l.addItem(QListWidgetItem(m))
    sec._executor = SimpleNamespace(submit=lambda fn: None)
    return sec


def test_a_refresh_mid_build_cancels_it(qtbot, owned_widgets, monkeypatch) -> None:
    lst = owned_widgets.own(QListWidget())
    sec = _queue_section(lst, monkeypatch)
    sec._populate_rows([_entry(n) for n in range(200)])
    handle = sec._build_handle
    assert handle is not None and not handle.done, "build must be mid-flight"

    sec.refresh()   # clears the list for "Loading…" — the crash site

    qtbot.wait(300)  # let any still-scheduled batch run (pytest-qt fails on a slot error)
    assert not handle.done, "the build kept running into a cleared list"
    assert lst.count() == 1, "only the loading row may remain"


def test_filtering_while_loading_does_not_touch_deleted_rows(
        qtbot, owned_widgets, monkeypatch) -> None:
    lst = owned_widgets.own(QListWidget())
    sec = _queue_section(lst, monkeypatch)
    sec._populate_rows([_entry(n) for n in range(200)])

    sec.refresh()
    sec._no_match_item = None
    sec._apply_filter("title 7")   # a keystroke while "Loading…" shows

    assert sec._groups == []
