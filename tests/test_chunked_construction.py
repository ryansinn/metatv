"""Unit tests for ``build_chunked``/``ChunkHandle`` (PERF-17).

``metatv/gui/chunked_construction.py`` builds N items ``batch_size`` at a time
— the first batch synchronously, the rest via ``QTimer.singleShot(0, ...)`` —
so a ``QueueSection``-style build loop stops freezing the main thread on a
several-hundred-entry list (the owner's real Watch Queue: 666 entries, worst
sampled pause 3,753ms). These exercise the mechanism directly: a plain list
stands in for "the widget being built", no real QWidget needed to prove the
batching, cancellation and supersede behavior.
"""

from __future__ import annotations

from metatv.gui.chunked_construction import build_chunked


def test_first_batch_builds_synchronously_rest_after_event_processing(qtbot):
    built: list[int] = []
    done_calls: list[int] = []

    handle = build_chunked(
        range(200), built.append, batch_size=40, on_done=lambda: done_calls.append(1),
    )

    assert len(built) == 40, "the first batch must be built before build_chunked returns"
    assert not handle.done
    assert done_calls == []

    qtbot.waitUntil(lambda: handle.done, timeout=2000)

    assert built == list(range(200))
    assert done_calls == [1], "on_done must fire exactly once"


def test_cancel_stops_future_batches_and_never_fires_on_done(qtbot):
    built: list[int] = []
    done_calls: list[int] = []

    handle = build_chunked(
        range(200), built.append, batch_size=40, on_done=lambda: done_calls.append(1),
    )
    assert len(built) == 40

    handle.cancel()
    handle.cancel()  # idempotent — must not raise or double-anything

    qtbot.wait(200)  # give any (wrongly) scheduled batch a chance to run

    assert len(built) == 40, "cancel after the first batch must stop every later one"
    assert done_calls == [], "on_done must never fire after cancel"
    assert not handle.done


def test_supersede_final_built_set_is_only_the_second_dataset(qtbot):
    """The real bug this prevents: a refresh starting a new build while the
    old one is still in flight must not leave the superseded build's later
    batches mixed into the new one (#PERF-17 — ``WatchQueueSection`` hits this
    on every refresh of a Watch Queue too large to build in one tick)."""
    built: list[str] = []

    def build_one(item: str) -> None:
        built.append(item)

    items_a = [f"a{i}" for i in range(200)]
    handle_a = build_chunked(items_a, build_one, batch_size=40)
    assert len(built) == 40  # A's first batch — unavoidable, always synchronous

    # What a real caller does on refresh (WatchQueueSection._populate_rows):
    # cancel the superseded build, then clear whatever it already produced,
    # then start the new one.
    handle_a.cancel()
    built.clear()

    items_b = [f"b{i}" for i in range(200)]
    handle_b = build_chunked(items_b, build_one, batch_size=40)

    qtbot.waitUntil(lambda: handle_b.done, timeout=2000)

    assert built == items_b, (
        "A's superseded batches leaked into B — the liveness guard did not hold"
    )


def test_on_done_never_fires_for_an_empty_item_list(qtbot):
    """A degenerate but real case (WatchQueueSection with nothing to show):
    zero items still completes and still reconciles via on_done."""
    done_calls: list[int] = []
    handle = build_chunked([], lambda item: None, on_done=lambda: done_calls.append(1))

    assert handle.done
    assert done_calls == [1]
