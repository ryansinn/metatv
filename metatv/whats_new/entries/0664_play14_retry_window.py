from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=664,
    version="0.120.0",
    date="2026-09-11",
    title=(
        "Streams wait out a busy source instead of giving up after 11 seconds; a silent "
        "connection times out; a late auto-retry never replaces what you played next"
    ),
    items=(
        "Switching titles, seeking, or moving to the next episode on a one-connection "
        "source used to give up after about 11 seconds and relaunch the player window. "
        "It now keeps trying for close to a minute, which covers how long that kind of "
        "source actually takes to free the previous connection.",
        "A connection that the source accepts but never answers at all used to hang "
        "indefinitely with no message. It now times out and retries like any other "
        "failure.",
        "When a stream failed and the status bar said \"retrying in 20s\", playing a "
        "different title before those 20 seconds passed no longer risks the retry "
        "silently replacing what you just started.",
    ),
    test_steps=(
        "On a one-connection source, play a title, then immediately play another on "
        "the same source — it should start within about a minute in the same player "
        "window while the status bar counts \"Waiting for <source> to free the previous "
        "stream… Ns\", with no window relaunch and no \"retrying in 20s\".",
        "While a movie plays, seek well past the buffered region — it should resume "
        "within about a minute instead of the player closing.",
        "Play a title that fails so the status bar says \"retrying in 20s\", then click "
        "a different title before the 20 seconds pass — the retry must not replace it "
        "(the log records \"retry for … skipped\").",
    ),
)
