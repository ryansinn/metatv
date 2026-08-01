from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=208,
    version="0.18.0",
    date="2026-08-01",
    title="Clear EPG link — fix a channel stuck with wrong guide data",
    items=(
        "Live channels have a new 🧹 \"Clear EPG link\" action — in the channel "
        "menu (channel list, EPG On Now, and EPG Browse) and as a rail button in "
        "the details pane.",
        "Clearing unlinks the channel's guide data AND blocks it from being "
        "re-matched — previously a cleared link would silently come back the "
        "next time the EPG view refreshed.",
        "The same control flips to \"Re-link EPG data\" once a channel is "
        "blocked — one click removes the block and re-matches it immediately.",
    ),
    test_steps=(
        "Right-click a live channel with wrong/mismatched guide data → \"Clear "
        "EPG link\" → its EPG On Now / Browse guide data disappears.",
        "Switch away from the EPG view and back (or reopen it) → the channel "
        "stays unlinked — it does NOT silently reacquire guide data.",
        "Right-click the same channel again → the action now reads \"Re-link "
        "EPG data\" → click it → the channel re-matches guide data on the next "
        "refresh.",
        "Open the details pane for a live channel → the 🧹 rail button (left of "
        "Hide) mirrors the same clear/re-link toggle; open a movie/series → the "
        "button is hidden (live-only).",
    ),
)
