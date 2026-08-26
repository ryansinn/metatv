from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=362,
    version="0.41.0",
    date="2026-08-26",
    title="Scroll a sidebar section to see more of it",
    items=(
        "Sidebar sections show the entries that fit and hide the rest. "
        "Scrolling one now reveals more, a few rows at a time, by making that "
        "section taller — space comes from whichever neighbours have the most "
        "to spare, and none of them is squeezed below its useful minimum.",
        "The \"Show N more\" row is gone by default. Scrolling already does "
        "the job, so the row was mostly a standing distraction. It is now a "
        "setting — Settings → Interface → Sidebar — for pointing devices that "
        "cannot scroll.",
        "When it is switched on and a section has no room left to grow, the "
        "row says \"See all N more →\" and opens the full view, instead of "
        "promising to show more and then doing something else.",
        "The main results list is unaffected — it has a real scrollbar.",
    ),
    test_steps=(
        "Find a sidebar section with more entries than fit → scroll down over "
        "it. The section grows and more entries appear; neighbouring sections "
        "give up space but none collapses.",
        "Scroll up over the same section → nothing grows.",
        "Scroll over a section that is showing everything → nothing happens, "
        "and the page behaves normally.",
        "Settings → Interface → Sidebar → tick \"Show a 'Show N more' row\" → "
        "OK. The row appears at the foot of truncated sections; clicking it "
        "grows the section just like scrolling.",
        "With the row on, shrink every other section to its minimum, then "
        "click the row → it reads \"See all N more →\" and opens the full view.",
        "Untick the setting → the row disappears and scrolling still works.",
    ),
)
