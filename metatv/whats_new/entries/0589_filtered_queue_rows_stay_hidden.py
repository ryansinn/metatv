from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=589,
    version="0.95.0",
    date="2026-09-04",
    title="Filtered sidebar rows stay hidden",
    items=(
        "Rows hidden by the Watch Queue's find-in-queue filter (or a folded "
        "Watch Alerts group) no longer reappear when the sidebar is resized "
        "or refreshed — a leftover row-sizing pass used to silently un-hide "
        "them, dropping the filter on a mere splitter drag.",
        "Row visibility now belongs to exactly one thing: whichever filter "
        "or fold hid the row. The sidebar's row-fitting pass only ever sizes "
        "views, never un-hides them.",
    ),
    test_steps=(
        "Type in the Watch Queue's find-in-queue filter so some rows hide → "
        "drag the sidebar splitter → the hidden rows stay hidden and the "
        "header still reads \"(N of M)\".",
        "Clear the filter → every row returns.",
    ),
)
