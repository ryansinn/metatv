from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=486,
    version="0.64.0",
    date="2026-09-01",
    title="A warning about streams that play perfectly",
    items=(
        "Opening something could raise a warning that the stream looked "
        "unavailable — and choosing Play Anyway played it without trouble.",
        "Before opening a stream the app fetches its first few bytes as a "
        "check. Any error at all was treated as proof the stream was bad.",
        "But that check is a second connection, and most accounts allow only "
        "one. When something is already playing or the watchlist is checking, "
        "the source answers the check with an error precisely because it is "
        "busy serving — not because anything is wrong with the stream.",
        "Server-side errors no longer block playback; mpv tries, and it "
        "reconnects on its own. Errors that mean you were actually turned away "
        "— wrong credentials, or content that is gone — are still reported, "
        "with Play Anyway still offered.",
    ),
    test_steps=(
        ("Play a film while something else is already playing, and confirm no "
         "spurious 'stream unavailable' warning appears.", "view:list"),
        "Play a channel from a source whose subscription has expired and "
        "confirm you still get a warning with a Play Anyway option.",
        ("Play several things in a row and confirm none of them are blocked "
         "by a warning for a stream that then plays fine.", "view:favorites"),
    ),
)
