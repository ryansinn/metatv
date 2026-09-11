from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=665,
    version="0.120.0",
    date="2026-09-11",
    title="A title counts as played only once it actually plays",
    items=(
        "Play count, last-played, and History no longer move for a stream "
        "that never started. Retrying a failing title used to inflate its "
        "play count once per attempt — six failed tries logged as six plays, "
        "even though nothing ever showed a frame.",
        "The moment the first seconds of video actually play, it is recorded "
        "exactly as before — History gets its entry, resume tracking is "
        "armed, and the play count goes up by one.",
        "Play-All still records each item the instant it reaches the "
        "player, since queuing the next item IS that item's own confirmation "
        "that it started.",
    ),
    test_steps=(
        "Play a title that will not start (the status bar reports "
        "\"Nothing is playing\"). History must not gain an entry and the "
        "details pane's play count must not rise, even after retrying.",
        "Play a title that works. Within a few seconds of video it appears "
        "in History with its play count up by one.",
        "Run Play-All on a series with several episodes — each episode "
        "still records as it reaches the player, in order.",
    ),
)
