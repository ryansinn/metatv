from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=373,
    version="0.41.0",
    date="2026-08-26",
    title="Watch Alerts: one left edge, one count column, no clipped letters",
    items=(
        "EPG titles started further right than the Movies and Series ones "
        "below them, so the section had two left edges. They all line up now, "
        "and a programme's disclosure arrow sits in the same left column as "
        "the play and new markers instead of its own.",
        "Descenders were being clipped - the tail of the g in \"Stargate\" - "
        "because a row was sized to its contents rather than to the font.",
        "Group headings have room above them, so the gap belongs to the group "
        "that follows rather than being split around the heading.",
        "Section counts line up in a column down the sidebar. Watch Queue's "
        "count sat further inboard than the others because its search button "
        "pushed it along; the count now sits beside the arrow in every "
        "section, and that search button lost its heavy outline.",
        "The Watch Alerts badge reads \"+2\" like the rest of the counts, and "
        "the busy indicator sits to its left so starting or finishing a check "
        "no longer shifts it.",
    ),
    test_steps=(
        "Open Watch Alerts - EPG, Movies and Series titles all start at the "
        "same left edge; a programme's sources indent under it.",
        "Find a title with a descender like \"Stargate SG-1\" - the g is not "
        "clipped.",
        "Click a programme's arrow - it opens and the arrow flips, in the same "
        "column the play triangle appears in on hover.",
        "Look down the sidebar - Recommended, Watch Queue and Favorites counts "
        "form a straight column beside their arrows.",
        "Watch a series check start and finish - the +N badge does not move.",
    ),
)
