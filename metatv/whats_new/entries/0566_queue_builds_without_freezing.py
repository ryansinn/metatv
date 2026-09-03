from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=566,
    version="0.88.0",
    date="2026-09-03",
    title="The Watch Queue builds without freezing (PERF-17)",
    items=(
        "The Watch Queue built one row widget per entry synchronously — on "
        "the owner's real 666-entry queue that froze the whole app on every "
        "refresh, sampled 4x in one launch, worst 3,753ms. It now builds a "
        "screen's worth of rows immediately and streams the rest in over "
        "small batches, so the UI stays responsive the whole time.",
        "A refresh that arrives mid-build (marking something watched, "
        "clearing a row) cancels the in-progress build first, so it can "
        "never leave duplicate rows behind.",
        "The find-in-queue filter now applies to every row AS it is built, "
        "not only once the whole list has finished streaming in — so typing "
        "a filter while a large queue is still filling never flashes "
        "unfiltered rows.",
        "The underlying chunked-build mechanism is shared infrastructure — "
        "the filter panel and Discover shelves are the next two surfaces "
        "planned to adopt it.",
    ),
    test_steps=(
        "With a large Watch Queue (100+ entries), launch the app or trigger "
        "a queue refresh → the UI stays responsive while the queue fills in; "
        "scrolling and clicking work immediately, before the whole list has "
        "finished rendering.",
        "Type in the queue filter (🔍) while a large queue is still filling "
        "in → only matching rows appear on screen, including in the rows "
        "that arrive after you typed.",
        "Mark an item watched (or otherwise trigger a queue refresh) while a "
        "previous refresh's rows are still streaming in → no duplicate rows "
        "appear afterward.",
    ),
)
