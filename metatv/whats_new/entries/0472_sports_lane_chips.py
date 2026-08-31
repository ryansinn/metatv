from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=472,
    version="0.61.0",
    date="2026-08-31",
    title="Sports splits into lanes you can switch between",
    items=(
        "Sports now has five lanes across the top — On now, Upcoming, "
        "Channels, Finished and No event — and each carries its own count, so "
        "the standalone \"183 channels\" line is gone.",
        "Finished fixtures no longer sit among the upcoming ones. They have "
        "their own lane, so what is about to start is what you see first.",
        "Always-on sports channels are their own lane too. They have no "
        "schedule, and mixing them into a list of fixtures made both harder "
        "to read.",
        "The \"No event\" lane holds the empty slots providers publish to keep "
        "their feed numbers stable — 5,565 of them in a typical library, all "
        "literally named \"NO EVENT STREAMING NOW\". They are counted and one "
        "click away rather than filling the list.",
        "The lane you pick is remembered between sessions.",
    ),
    test_steps=(
        ("Open Sports. It should open on Upcoming, with a count on each lane "
         "chip.", "view:sports"),
        "Click through the five lanes and confirm each chip's number matches "
        "the number of rows it shows.",
        "Open \"No event\" and confirm it holds the empty provider slots, and "
        "that none of them appear in the other four lanes.",
        "Pick a sport in the Sport filter and confirm every lane count "
        "updates to match that filter.",
        "Switch to another view and back, then restart the app — Sports "
        "should reopen on the lane you left it on.",
    ),
)
