from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=440,
    version="0.55.0",
    date="2026-08-29",
    title="Watch Alerts says when a pinned channel can never fire",
    items=(
        "A pinned channel with nothing on now showed 'No EPG data' - the same "
        "thing a perfectly healthy channel shows when the guide has not "
        "reached it yet.",
        "So a channel on a source you had switched off, and one whose source "
        "you had removed entirely, looked exactly like a channel that was "
        "briefly quiet. Neither could ever produce an alert and nothing said "
        "so.",
        "Those two cases now say which it is, and what to do: turn the source "
        "back on, or remove the channel from Watch Alerts.",
        "A channel that simply has no guide data right now still reads the "
        "same as before - that one does fix itself.",
    ),
    test_steps=(
        "Pin a channel from a source, turn that source off, and open Watch "
        "Alerts. Confirm the card says the source is turned off rather than "
        "'No EPG data'.",
        "Hover that line and confirm it suggests turning the source back on.",
        "Turn the source back on and confirm the card returns to normal.",
        "Confirm a pinned channel on an active source with no current "
        "programme still reads 'No EPG data' and is not flagged as broken.",
    ),
)
