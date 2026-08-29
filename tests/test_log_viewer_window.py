"""The log viewer streams live, filters without losing lines, and lets go on close.

The logs were already reachable — Tools ▸ Open config folder reveals the
directory. That is right for sending a file to someone and wrong for watching
what the app is doing *now*, which is when a log is actually wanted: the thing
being reproduced is happening while the user hunts for a text editor.

Two properties carry the whole window and both are easy to get wrong:

* **The sink must not outlive the widget.** loguru calls sinks on whatever
  thread logged, and this app logs from EPG fetches, the series monitor and
  ingestion workers. A sink still registered after the window is destroyed
  calls into a deleted C++ object on the next line from any thread — the fault
  that has been aborting this app's shutdown.
* **Filtering must not consume lines.** The window receives DEBUG and filters in
  the UI, so raising and lowering the level re-reveals what is already held.
  Filtering by dropping would make the control one-way and silently lossy.
"""

from __future__ import annotations

import pathlib

import pytest
from loguru import logger

from metatv.core.log_paths import ACTIVE_LOG_NAME, log_directory
from metatv.gui.log_viewer_window import MAX_LINES, LogViewerWindow, clear_log_files


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def viewer(qapp):
    w = LogViewerWindow(None)
    yield w
    w.close()


def _pump(qapp):
    """Let the queued signal deliver — the bridge is deliberately not direct."""
    for _ in range(3):
        qapp.processEvents()


# ── the live stream ─────────────────────────────────────────────────────────

def test_a_line_logged_now_appears_now(viewer, qapp):
    """THE assertion. This is the entire reason the window exists."""
    logger.info("a distinctive marker line")
    _pump(qapp)

    assert "a distinctive marker line" in viewer.view.toPlainText()


def test_a_worker_thread_can_log_without_touching_the_widget(viewer, qapp):
    """loguru calls sinks on the emitting thread; Qt widgets are main-thread.

    The bridge exists to turn that into a queued signal. If it were ever
    replaced by a direct write, this is the test that would crash rather than
    fail.
    """
    import threading

    done = threading.Event()

    def _work():
        logger.info("logged from a worker thread")
        done.set()

    t = threading.Thread(target=_work)
    t.start()
    t.join(2)
    assert done.is_set()
    _pump(qapp)

    assert "logged from a worker thread" in viewer.view.toPlainText()


# ── filtering keeps the lines ───────────────────────────────────────────────

def test_raising_the_level_hides_lines_without_discarding_them(viewer, qapp):
    """Lowering it again must bring them back — the control is two-way."""
    logger.info("an info line")
    logger.warning("a warning line")
    _pump(qapp)

    viewer.level_combo.setCurrentText("WARNING")
    shown = viewer.view.toPlainText()
    assert "a warning line" in shown
    assert "an info line" not in shown

    viewer.level_combo.setCurrentText("DEBUG")
    shown = viewer.view.toPlainText()
    assert "an info line" in shown, (
        "the info line was consumed by the filter rather than hidden by it"
    )


def test_a_line_filtered_out_when_it_arrived_is_still_recoverable(viewer, qapp):
    """The lossy case: the filter is already raised WHEN the line is logged.

    Filtering after the fact proves nothing — the buffer already holds
    everything by then. This raises the level first, so a window that filtered
    on the way IN would have thrown the line away with nothing to restore.
    """
    viewer.level_combo.setCurrentText("ERROR")

    logger.info("quiet line logged while the filter was raised")
    _pump(qapp)
    assert "quiet line" not in viewer.view.toPlainText()

    viewer.level_combo.setCurrentText("DEBUG")

    assert "quiet line logged while the filter was raised" in viewer.view.toPlainText(), (
        "the line was discarded on arrival, so lowering the level cannot bring "
        "it back — the filter is one-way and silently lossy"
    )


def test_the_text_filter_narrows_within_the_level(viewer, qapp):
    logger.info("apples are red")
    logger.info("bananas are yellow")
    _pump(qapp)

    viewer.filter_edit.setText("banana")
    shown = viewer.view.toPlainText()

    assert "bananas are yellow" in shown
    assert "apples are red" not in shown


def test_the_status_line_says_how_much_is_hidden(viewer, qapp):
    logger.info("one")
    logger.warning("two")
    _pump(qapp)
    viewer.level_combo.setCurrentText("WARNING")

    assert "of" in viewer.status_lbl.text(), (
        "the status line must say the view is filtered, or a user reads an "
        "empty window as 'nothing is happening'"
    )


def test_the_buffer_is_capped(viewer, qapp):
    """An open window during ingestion is otherwise a leak with a scrollbar."""
    assert viewer._buffer.maxlen == MAX_LINES
    assert viewer.view.maximumBlockCount() == MAX_LINES


def test_clear_view_does_not_touch_the_files(viewer, qapp, tmp_path):
    d = log_directory(create=True)
    (d / ACTIVE_LOG_NAME).write_text("still here")
    logger.info("something")
    _pump(qapp)

    viewer.clear_view()

    assert viewer.view.toPlainText() == ""
    assert (d / ACTIVE_LOG_NAME).read_text() == "still here", (
        "'Clear view' deleted from disk; that is what 'Clear log files' is for"
    )


# ── letting go ──────────────────────────────────────────────────────────────

def test_closing_removes_the_sink(qapp):
    """THE other assertion — a sink outliving its widget is the crash."""
    w = LogViewerWindow(None)
    sink_id = w._sink_id
    assert sink_id is not None

    w.close()

    assert w._sink_id is None
    with pytest.raises(ValueError):
        logger.remove(sink_id)  # already gone — removing twice must raise


def test_logging_after_close_does_not_reach_the_window(qapp):
    """The real failure mode: a line arriving after the widget is gone."""
    w = LogViewerWindow(None)
    w.close()
    before = len(w._buffer)

    logger.info("emitted after the window closed")
    _pump(qapp)

    assert len(w._buffer) == before, "the closed window is still receiving lines"


def test_closing_twice_is_safe(qapp):
    w = LogViewerWindow(None)
    w.close()
    w.close()


# ── clearing the files ──────────────────────────────────────────────────────

def test_clearing_removes_rotated_copies_and_truncates_the_active_one(tmp_path):
    """Rotation is what produced 330 MB; clearing only the live file frees ~0.

    The active file is truncated rather than unlinked because loguru holds it
    open — unlinking fails outright on Windows, and on POSIX leaves the handle
    writing to an unlinked inode, which reads as "the log stopped working".
    """
    d = log_directory(create=True)
    active = d / ACTIVE_LOG_NAME
    active.write_text("x" * 100)
    rotated = d / "metatv.2026-08-28_20-01-50.log"
    rotated.write_text("y" * 200)
    keep = d / "notes.txt"
    keep.write_text("not a log")

    removed, freed = clear_log_files()

    assert removed == 2
    assert freed == 300
    assert active.exists(), "the active file was unlinked, not truncated"
    assert active.read_text() == ""
    assert not rotated.exists(), "a rotated copy survived"
    assert keep.exists(), "a non-log file was deleted"


def test_clearing_an_empty_folder_is_not_an_error(tmp_path):
    assert clear_log_files() == (0, 0)


# ── diagnostics ─────────────────────────────────────────────────────────────

def test_diagnostics_carry_no_subscription_details(viewer):
    """Facts about the install, never about the account.

    Log LINES are redacted by the patcher in __main__, but a summary block
    assembled here would bypass that entirely — so it must not gather anything
    that could carry a credential in the first place.
    """
    text = viewer.diagnostics_text().casefold()

    for forbidden in ("username", "password", "http://", "https://", "@"):
        assert forbidden not in text, f"diagnostics leaked {forbidden!r}"


def test_diagnostics_name_the_log_location_and_size(viewer):
    text = viewer.diagnostics_text()
    assert ACTIVE_LOG_NAME in text
    assert "MB" in text


# ── the menu ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("handler", ["show_log_viewer", "clear_log_files"])
def test_the_tools_menu_reaches_both_handlers(handler):
    """Both entries must be wired, and the header's Tools button shares the
    same QMenu object — so one registration covers both surfaces."""
    src = pathlib.Path("metatv/gui/main_window.py").read_text()
    assert f"connect(self.{handler})" in src, f"no Tools entry calls {handler}"
    assert f"def {handler}" in src, f"{handler} is not defined"
