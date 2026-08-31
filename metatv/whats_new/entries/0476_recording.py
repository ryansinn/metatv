from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=476,
    version="0.64.0",
    date="2026-08-31",
    title="Record what's on",
    items=(
        "Right-click a live channel and choose Record what's on. It records "
        "until the programme ends, using the guide to know when that is — and "
        "keeps a minute before and five minutes after, because matches run "
        "over and guide clocks are not the stream's clock.",
        "A channel with no guide data records for two hours instead, which you "
        "can see and cancel rather than guess at.",
        "A recording does not stop when you start watching something else. "
        "Downloads pause for you because a paused download loses nothing; a "
        "paused recording loses the minutes it missed, and those do not come "
        "back.",
        "If the source is busy when a recording is due, it waits and keeps "
        "trying for the whole programme rather than giving up. Stop watching "
        "twenty minutes in and the last forty minutes are recorded. You are "
        "told once when this happens, so a recording never silently fails.",
    ),
    test_steps=(
        ("Right-click a live channel with guide data and choose Record what's "
         "on; the notification should name the time it will stop.", "view:epg"),
        "Right-click a movie and confirm Record is not offered — only Download.",
        "Start a recording, then play a different channel on the SAME source. "
        "The recording should keep going and the download queue should pause "
        "instead.",
        "Start a recording while already watching that source. You should get "
        "a notice that it is waiting, and it should start once you stop "
        "watching.",
        "Let a short programme record to the end and confirm the file is in "
        "your library folder and plays.",
        "Choose Record what's on twice for the same programme and confirm the "
        "second one is refused rather than recording it twice.",
    ),
)
