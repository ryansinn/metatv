"""What's New entry for #546: keep rows visible during background refreshes."""

from metatv.whats_new.entry import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=546,
    slug="keep_rows_during_refresh",
    version="0.82.0",
    date="2026-09-02",
    title="Channel list stays visible during background refreshes",
    description=(
        "After metadata enrichment settles, after provider changes, or when applying "
        "Global Exclusions, the channel list no longer blanks for several seconds "
        "while the new results are being fetched. The old rows stay visible until "
        "the updated set arrives, eliminating the jarring flash of emptiness."
    ),
    test_steps=(
        "Apply Global Exclusions while the channel list is showing results: the list "
        "keeps its rows until the refreshed set appears — no multi-second blank flash.",
        "Type a new search: the list still clears to 'Loading channels…' immediately, "
        "as before.",
    ),
)
