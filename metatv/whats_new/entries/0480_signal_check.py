from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=480,
    version="0.64.0",
    date="2026-08-31",
    title="MetaTV checks whether an event is actually streaming",
    items=(
        "Event channels often say a fight or a match is on and show a black "
        "screen. MetaTV now samples them quietly in the background and records "
        "what it found — a moving picture, a black screen, a frozen slate, or "
        "nothing at all.",
        "Settings has a Signal checking tab, and an option to hide events whose "
        "last few checks found no picture. It is off to begin with, so you can "
        "see how widespread the problem is before anything disappears.",
        "Checking never gets in your way. It uses the source's connection only "
        "while nothing else needs it, and the moment you press Play it drops "
        "the check and gives the connection straight back.",
        "Giving the connection back is never counted against a channel. Only a "
        "check that actually saw the picture can mark one dead — otherwise "
        "simply watching a lot would make good channels look broken.",
        "A channel nobody has checked yet is always shown. Unknown is not the "
        "same as dead.",
    ),
    test_steps=(
        ("Open Events and leave it a few minutes, then reopen. Nothing should "
         "visibly change yet — checking is quiet by design.", "view:events"),
        "Open Settings and find the Signal checking tab; confirm the options "
        "are there and that hiding is off by default.",
        "Turn on 'Hide events with no signal' and confirm events you have "
        "never checked are still listed.",
        "Start playing something, and confirm playback starts immediately "
        "rather than waiting for a check to finish.",
    ),
)
