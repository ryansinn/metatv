from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=614,
    version="0.100.0",
    date="2026-09-06",
    title="A stream that dies while opening is reported and retried once",
    items=(
        "When the player quits on its own before any video arrives — a "
        "one-connection source still counting a guide download or the "
        "pre-play check — MetaTV now says so and replays the title once, "
        "twenty seconds later, without the extra connection the check costs. "
        "Before, that first attempt vanished silently and a second click "
        "was needed.",
        "Closing a player you opened yourself stays silent, as before.",
        "The log records how each player process ended (mpv's own exit "
        "reason, return code and lifetime).",
    ),
    test_steps=(
        "Right after a guide refresh on a one-connection source, play a title "
        "from it: if the first player closes without video, a notice says the "
        "stream did not start and that it is retrying, and the title plays on "
        "the retry with no second click.",
        "Open a title and close the player window yourself within a few "
        "seconds — no notice, no retry.",
    ),
)
