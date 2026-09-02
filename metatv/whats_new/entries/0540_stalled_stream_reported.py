from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=540,
    version="0.80.0",
    date="2026-09-02",
    title="A stream that loads but never plays now says why",
    items=(
        "The last two releases caught streams that opened and stayed empty "
        "(nothing loaded in the first place) and players that closed without "
        "playing (nothing to probe). They could not catch the third case — a "
        "file that opened, video output configured, but playback never "
        "advanced. The user saw a black window and silence, and nothing was "
        "reported.",
        "That case is now reported too, with its own message: the source "
        "accepted the file but never delivered playable video.",
        "Pausing the player yourself never triggers the report — the counter "
        "holds while the player is paused.",
        "Closing the player yourself stays silent, and a failed play is still "
        "reported only once however it failed.",
    ),
    test_steps=(
        "Play a stream that opens a player window but never shows video (a "
        "sports fixture before its start time reproduces this), then wait "
        "about 20 seconds: one 'Stream did not start' warning names the "
        "channel — exactly one, not two — and the status bar says 'Nothing "
        "is playing'. No more silent black window.",
        "Play a working stream and pause it within the first few seconds; "
        "leave it paused for 30 seconds: no failure warning appears.",
    ),
)
