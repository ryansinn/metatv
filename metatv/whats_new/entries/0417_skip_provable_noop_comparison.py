from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=417,
    version="0.53.0",
    date="2026-08-29",
    title="The channel list stops running a query that can only return zero",
    items=(
        "To tell you how many channels it hid for repeated playback failures, "
        "the list ran the whole query a second time with that filter lifted "
        "and compared the results.",
        "It did that even when nothing had ever failed - which is the normal "
        "case, and is true of a fresh install.",
        "The second query is not cheap: with variant grouping on it costs "
        "about as much as the first one.",
        "It now checks whether anything is actually in that state before "
        "measuring. The number you see is unchanged.",
    ),
    test_steps=(
        "Browse the channel list and confirm it appears faster than before.",
        "Confirm the hidden-content bar still reports exclusions and search "
        "correctly.",
        "If you have a channel that has failed to play repeatedly, confirm the "
        "'hidden by dead streams' count still appears and still reveals them.",
    ),
)
