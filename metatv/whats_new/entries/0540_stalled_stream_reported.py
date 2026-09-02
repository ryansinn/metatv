from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=540,
    version="0.79.0",
    date="2026-09-02",
    title="A stream that loads but never plays now says why",
    items=(
        "The last two releases caught streams that opened and stayed empty "
        "(nothing loaded in the first place) and players that closed without "
        "playing (nothing to probe). They could not catch the third case — a "
        "file that opened, video output configured, but playback never "
        "advanced. The user saw a black window and silence, and nothing was "
        "reported.",
        "That case is now reported too, with its own message. It means the "
        "stream accepted the file but could not deliver video — rare locally, "
        "common on stalled connections.",
        "A player paused within the first 16 seconds will not trigger the "
        "report; the counter holds while you're holding play.",
        "Closing the player yourself stays silent, and a failed play is still "
        "reported only once however it failed.",
    ),
    test_steps=(
        ("Play a stream that opens a player window but never shows video "
         "(e.g. a sports fixture before its start time), then wait about 20 "
         "seconds.",
         "A 'Stream did not start' warning names the channel and the status "
         "bar says 'Nothing is playing' — no more silent black window"),
        ("Play a working stream and pause it within the first few seconds; "
         "leave it paused for 30 seconds.",
         "No failure warning appears"),
        ("Play a channel you know is dead or stalled. Within 20 seconds you "
         "should get one \"Stream did not start\" notification — exactly one, "
         "not two.",
         "view:list"),
        ("Confirm a stalled play appears in the stream retry list.",
         "view:list"),
    ),
)
