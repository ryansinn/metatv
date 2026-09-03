from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=575,
    version="0.91.0",
    date="2026-09-03",
    title="Discover no longer loads itself in the background — and builds without freezing",
    items=(
        "Discover's reload() had no guard on whether the view was actually "
        "on screen: every provider mutation (a source toggle, an add/edit/"
        "delete) called it unconditionally, so the view rebuilt its shelves "
        "in the background even while you were looking at something else — "
        "the root cause of the multi-second freezes reported this morning "
        "(worst sampled: 6,016ms), which happened with Discover closed. "
        "Discover now tracks whether it's the active view and only marks "
        "itself dirty while inactive; the real load happens the next time "
        "you open it.",
        "When you DO have Discover open, each shelf's cards now build in "
        "small batches instead of all at once — the first screenful appears "
        "immediately and the rest fills in strip by strip as the app stays "
        "responsive, using the same chunked-build mechanism the Watch Queue "
        "uses for its long lists.",
        "Switching away from Discover, hiding a shelf, or rebuilding one "
        "mid-build (e.g. a zoom change) now cleanly stops any in-progress "
        "card build instead of letting it keep working in the background.",
    ),
    test_steps=(
        "Toggle a source off and back on while Discover is CLOSED (e.g. on "
        "the channel list) → no stall, no visible delay; open Discover "
        "afterwards and it loads fresh, correctly scoped to the change.",
        "Open Discover with many shelves → the view stays responsive while "
        "cards fill in strip by strip; switching away mid-load doesn't "
        "stutter or leave background work running.",
    ),
)
