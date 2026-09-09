"""A refresh that FAILS must still cancel the in-flight chunked build (SIGABRT).

Owner crash, 2026-09-09:

    File "metatv/gui/sidebar/queue.py", line 557, in _apply_filter
        item.setHidden(not match)
    RuntimeError: wrapped C/C++ object of type QListWidgetItem has been deleted
    fish: Job 1, './run.sh' terminated by signal SIGABRT (Abort)

``BackgroundRefreshMixin._on_data_ready`` clears the list — deleting every
``QListWidgetItem`` the previous build produced — and only ``_populate_rows``
cancelled the build that produced them. The ``rows is None`` branch RETURNS
before reaching it, so a refresh whose query failed left the old build running
against a cleared list: its remaining batches kept appending, then ``on_done``
ran ``_apply_filter`` over deleted C++ objects. A ``RuntimeError`` raised inside
a Qt slot aborts the process.

Reachable in ordinary use: the same log shows SQLite write-gate timeouts (a
failing ``_load_rows``), and before the enrichment-settle floor landed the
refresh cascade fired every ~40s, so a build was very often still in flight.

``test_the_pending_batch_crashes_without_the_cancel`` pins the mechanism itself
against the real ``build_chunked``, so the guard cannot quietly stop describing
the bug it was written for.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QListWidget, QListWidgetItem

from metatv.gui.chunked_construction import build_chunked


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _chunked_into(lst, owner, rows, on_done, count=60, batch=20):
    """Start a real chunked build that appends items to *lst* and records them."""
    def build_one(n):
        item = QListWidgetItem(f"row {n}")
        lst.addItem(item)
        rows.append(item)
    return build_chunked(
        range(count), build_one, batch_size=batch, on_done=on_done, parent=owner
    )


def test_the_pending_batch_crashes_without_the_cancel(qtbot, qapp, owned_widgets):
    """The mechanism, pinned: clear the list mid-build WITHOUT cancelling → boom.

    This is the pre-fix behaviour, asserted directly rather than described, so
    the fix below is measured against a reproduction and not a theory.
    """
    lst = owned_widgets.own(QListWidget())
    owner = QObject()
    rows: list = []
    boom: list = []

    def on_done():
        try:
            for item in rows:
                item.setHidden(False)
        except RuntimeError as exc:
            boom.append(exc)

    handle = _chunked_into(lst, owner, rows, on_done)
    assert not handle.done, "the build must still be mid-flight for this to mean anything"

    lst.clear()  # what _on_data_ready does — the items are now deleted
    qtbot.waitUntil(lambda: bool(handle.done or boom), timeout=2000)

    assert boom, (
        "expected the pending batch to touch a deleted QListWidgetItem — if this "
        "stops happening, build_chunked's lifetime behaviour changed and this "
        "guard no longer describes the crash it was written for"
    )


def test_cancel_before_clear_makes_the_pending_batch_a_no_op(qtbot, qapp, owned_widgets):
    """With the cancel in place (what _on_data_ready now does), nothing runs."""
    lst = owned_widgets.own(QListWidget())
    owner = QObject()
    rows: list = []
    done_calls: list = []

    handle = _chunked_into(lst, owner, rows, lambda: done_calls.append(None))
    assert not handle.done

    handle.cancel()   # the fix: cancel FIRST...
    lst.clear()       # ...then clear

    qtbot.wait(200)
    assert done_calls == [], "a cancelled build must never run its on_done"


def test_failed_refresh_cancels_the_build(qtbot, qapp, owned_widgets):
    """The real path: _on_data_ready(None) must cancel before it clears.

    Drives ``BackgroundRefreshMixin._on_data_ready`` itself — the error branch —
    on a host wired the way ``WatchQueueSection`` is.
    """
    from metatv.gui.sidebar.background_refresh import BackgroundRefreshMixin

    lst = owned_widgets.own(QListWidget())
    owner = QObject()
    rows: list = []
    done_calls: list = []

    class _Section(BackgroundRefreshMixin):
        def __init__(self):
            self._list = lst
            self._build_handle = None

        def _refresh_list(self):
            return self._list

        def _load_error_message(self):
            return "boom"

        def show_load_error(self, lst_, msg):
            lst_.addItem(QListWidgetItem(msg))

        def _drop_captured_scroll(self):
            pass

        # The queue section's override, verbatim in shape.
        def cancel_pending_build(self):
            handle = self.__dict__.get("_build_handle")
            if handle is not None:
                handle.cancel()
            self._build_handle = None

    section = _Section()
    section._build_handle = _chunked_into(
        lst, owner, rows, lambda: done_calls.append(None)
    )
    assert not section._build_handle.done

    # A refresh whose query failed.
    section._on_data_ready(None)

    qtbot.wait(200)
    assert done_calls == [], (
        "the failed refresh cleared the list but left the old build running — "
        "its on_done will touch deleted items and abort the process"
    )


def test_the_mixin_cancels_on_the_success_path_too(qtbot, qapp, owned_widgets):
    """_populate_rows is no longer the only cancel — the mixin does it first."""
    from metatv.gui.sidebar.background_refresh import BackgroundRefreshMixin

    lst = owned_widgets.own(QListWidget())
    owner = QObject()
    rows: list = []
    done_calls: list = []
    cancelled: list = []

    class _Section(BackgroundRefreshMixin):
        def __init__(self):
            self._list = lst
            self._build_handle = None

        def _refresh_list(self):
            return self._list

        def _populate_rows(self, rows_):
            pass

        def _restore_scroll(self, lst_):
            pass

        def reapply_row_budget(self):
            pass

        def cancel_pending_build(self):
            cancelled.append(True)
            handle = self.__dict__.get("_build_handle")
            if handle is not None:
                handle.cancel()
            self._build_handle = None

    section = _Section()
    section._build_handle = _chunked_into(
        lst, owner, rows, lambda: done_calls.append(None)
    )

    section._on_data_ready([])

    assert cancelled == [True]
    qtbot.wait(200)
    assert done_calls == []


def test_the_default_hook_is_a_no_op_for_sections_without_builds():
    """Sections that never chunk must not have to implement anything."""
    from metatv.gui.sidebar.background_refresh import BackgroundRefreshMixin

    class _Plain(BackgroundRefreshMixin):
        pass

    _Plain().cancel_pending_build()  # must not raise
