from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=363,
    version="0.41.0",
    date="2026-08-26",
    title="Sidebar sections grow as you scroll, then scroll normally",
    items=(
        "Scrolling a sidebar section makes it taller, taking room from "
        "neighbours that have some to spare. Once it is as tall as it can get, "
        "the list itself starts scrolling instead — so a section never stops "
        "responding with entries still hidden.",
        "History now loads 300 entries rather than 30. The old number was a "
        "cap from when a section could only ever show a handful of rows, and "
        "it had quietly become the ceiling you hit while scrolling.",
        "Favorites and Watch Queue already loaded everything. "
        "Recommendations still stops at 20 on purpose — it is a ranked "
        "shelf, and the four-hundredth suggestion is not a recommendation.",
    ),
    test_steps=(
        "Scroll down a sidebar section with more entries than fit → it grows "
        "and reveals more; neighbouring sections shrink but none collapses.",
        "Keep scrolling until the section stops growing → the list starts "
        "scrolling within it and the remaining entries are reachable. It "
        "should never stop responding with entries still hidden.",
        "Open History with a long viewing history → scroll all the way down. "
        "You can reach far more than the 30 entries it used to stop at.",
        "Play something so History rebuilds → the section returns to its "
        "normal height rather than staying expanded from an earlier scroll.",
    ),
)
