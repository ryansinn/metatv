"""Migration toast must grow per progress row — no clipped second row.

PR #304 was the first time two migrations ran concurrently on launch
(``detected_title_reparse`` v5 + ``tag_backfill`` v8). QA found that with a
SECOND row, the panel does not grow: both rows are squeezed into the
one-row frame height and the row labels are clipped (about half the text
height visible).

Root cause: ``on_task_started`` resized the frame via ``adjustSize()``
(delegating to the nested ``_rows_container`` QVBoxLayout's ``sizeHint()``),
but that nested layout's cached size hint does not reliably refresh the
moment a row is added to an already-visible panel — a Qt quirk for a bare
sub-layout (added via ``addLayout``, not a widget's own top-level layout).
``MigrationProgressWidget._content_height()`` sidesteps the stale cache by
summing each row's own ``sizeHint()`` (always accurate immediately) instead
of trusting the nested layout's aggregate.

These tests drive the widget the same way ``MigrationManager`` does in the
real app: each ``on_task_started`` call is followed by a settle point
(``qtbot.wait``) before the next one arrives, mirroring the actual signal
flow — ``_run_all`` runs on a worker thread and does real migration work
(``task.run()``) between each ``_task_started`` emission, so the main
thread always gets to fully process one row's layout before the next row's
cross-thread signal is even emitted.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QWidget


def _make_widget(qtbot) -> tuple[QWidget, "MigrationProgressWidget"]:
    from metatv.gui.migration_progress_widget import MigrationProgressWidget

    parent = QWidget()
    parent.resize(1200, 800)
    qtbot.addWidget(parent)
    parent.show()
    qtbot.waitExposed(parent)

    widget = MigrationProgressWidget(parent)
    qtbot.addWidget(widget)
    return parent, widget


def test_second_row_grows_frame_and_is_not_clipped(qtbot):
    """Adding a second progress row grows the frame; no row is squeezed/clipped."""
    _parent, widget = _make_widget(qtbot)

    widget.on_task_started("t1", "detected_title_reparse v5 backfill")
    qtbot.wait(50)
    height_after_one_row = widget.height()
    row1 = widget._rows["t1"]

    widget.on_task_started("t2", "tag_backfill v8 rescan of all channel tags")
    qtbot.wait(50)
    height_after_two_rows = widget.height()
    row2 = widget._rows["t2"]

    second_row_min_height = row2.sizeHint().height()
    grown_by = height_after_two_rows - height_after_one_row
    assert grown_by >= second_row_min_height, (
        f"frame only grew by {grown_by}px after the second row, but the row "
        f"itself needs {second_row_min_height}px — the panel is squeezing "
        f"rows into a stale (one-row) height instead of growing to fit them"
    )

    # Every row must be positioned (not stuck at the widget-default (0, 0) /
    # 100x30 geometry a never-laid-out child gets) and fully sized —
    # in particular its label must not be clipped.
    for row in (row1, row2):
        assert row.width() > 100, f"row {row.task_id} was never positioned/sized"
        label = row._label
        assert label.height() >= label.fontMetrics().height(), (
            f"row {row.task_id}'s label is clipped: label height "
            f"{label.height()}px < font metrics height "
            f"{label.fontMetrics().height()}px"
        )


def test_third_row_also_grows_frame_without_clipping(qtbot):
    """A realistic 3-migration burst (the stated ceiling) keeps growing cleanly."""
    _parent, widget = _make_widget(qtbot)

    heights = []
    labels = [
        "detected_title_reparse v5 backfill",
        "tag_backfill v8 rescan of all channel tags",
        "content_key v3 recompute",
    ]
    for i, label in enumerate(labels, start=1):
        widget.on_task_started(f"t{i}", label)
        qtbot.wait(50)
        heights.append(widget.height())

    # Height must grow monotonically — one row per addition, never squeezed.
    assert heights[1] > heights[0]
    assert heights[2] > heights[1]

    for task_id, row in widget._rows.items():
        assert row.width() > 100, f"row {task_id} was never positioned/sized"
        label = row._label
        assert label.height() >= label.fontMetrics().height(), (
            f"row {task_id}'s label is clipped"
        )


def test_frame_height_matches_computed_content_height(qtbot):
    """The frame's actual height always matches the deterministic content sum."""
    _parent, widget = _make_widget(qtbot)

    widget.on_task_started("t1", "detected_title_reparse v5 backfill")
    qtbot.wait(50)
    assert widget.height() == widget._content_height()

    widget.on_task_started("t2", "tag_backfill v8 rescan of all channel tags")
    qtbot.wait(50)
    assert widget.height() == widget._content_height()
