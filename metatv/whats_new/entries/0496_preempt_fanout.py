from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=496,
    version="0.64.0",
    date="2026-09-01",
    title="Streams that opened, buffered, and closed a few seconds later",
    items=(
        "Playing anything could fail in a particular way: the player window "
        "opened, showed a buffering message, and then closed by itself after "
        "a few seconds. Pressing play again usually did the same thing.",
        "Your source allows only a small number of connections at once, so "
        "the app makes background work — artwork and genre lookups, watchlist "
        "checks — hand its connection back the moment you press play. The "
        "handing-back was only ever delivered to downloads. The lookups were "
        "told nothing, kept their requests running, and the player was refused "
        "the connection it needed.",
        "Every kind of background work now hears that it has been bumped, and "
        "stops immediately. The genre backfill also stops re-queueing itself "
        "while you are watching, instead of retrying several times a second.",
    ),
    test_steps=(
        ("Play a title straight after launch, while background lookups are "
         "still running, and confirm it starts and keeps playing rather than "
         "closing after a few seconds.", "view:list"),
        ("Play a second title immediately after the first and confirm it also "
         "starts on the first press.", "view:list"),
        "Start a download, then press play on something from the same source: "
        "the download should pause and playback should start.",
        "Leave the app idle for a minute with nothing playing and confirm "
        "background enrichment still runs (source toasts still appear).",
    ),
)
