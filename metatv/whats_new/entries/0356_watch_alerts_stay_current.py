from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=356,
    version="0.41.0",
    date="2026-08-26",
    title="Watch Alerts keeps up with the clock",
    items=(
        "Watch Alerts was a snapshot of whenever it last loaded. A programme "
        "that had finished stayed in the list, and a row saying \"in 13m\" "
        "could already be playing — every relative time was computed once, at "
        "load, and nothing recomputed it.",
        "Times and progress now refresh every 30 seconds from data already in "
        "memory, so nothing is looked up and the numbers simply stay true. "
        "Nothing repaints while the section is collapsed.",
        "Because a programme's start and end are already known, the list "
        "refreshes itself exactly when one of them arrives, rather than "
        "polling on a fixed interval and being wrong in between.",
        "Quality chips read their tier again — RAW amber, HD cyan, 4K purple, "
        "LIVE orange, instead of every one of them the same yellow — and they "
        "now share the thin grey outline the year chip uses, so a chip "
        "annotates a title instead of shouting over it.",
    ),
    test_steps=(
        "Open the sidebar with a Watch Alerts EPG entry currently airing. "
        "Leave it visible for a minute without touching anything → the "
        "\"Nm left\" text counts down on its own.",
        "Find an upcoming row a few minutes out and wait past its start time "
        "→ it moves into Watch Now by itself, with no manual refresh.",
        "Collapse Watch Alerts, leave it shut for a minute, then expand it → "
        "the times are correct immediately.",
        "Look at a row with a quality chip → RAW is amber, HD cyan, 4K "
        "purple, LIVE orange, each on the same thin grey outline as the year "
        "chip rather than a bright coloured ring.",
    ),
)
