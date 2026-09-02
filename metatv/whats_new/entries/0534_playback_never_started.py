from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=534,
    version="0.74.0",
    date="2026-09-02",
    title="A stream that never starts now says so instead of pretending",
    items=(
        "\"It's just hanging.\" When a source accepted the request but sent no "
        "video, the app had no idea: the status bar announced \"Playing…\" on "
        "a two-second timer whatever happened, the play was counted in your "
        "history, and no error ever appeared. You were left watching an empty "
        "window with nothing to tell you it had failed.",
        "The player is now actually checked. If no file has loaded about ten "
        "seconds after you pressed play, you get a plain message saying the "
        "stream did not start, and it goes into the same retry list as any "
        "other dead stream.",
        "\"Playing\" is only said when it is true — it now comes from the "
        "player reporting a loaded file, not from a timer.",
        "Closing the player yourself is unchanged and silent. The check only "
        "fires for a play that never began, not for one you ended.",
    ),
    test_steps=(
        ("Play something that works. The status bar must say \"Playing: …\" "
         "once video starts — and it must NOT say it before that.",
         "view:list"),
        ("Close the player window yourself part-way through. No error, no "
         "notification — this is the case that must stay silent.", "view:list"),
        ("Play a channel you know is dead (or pull the network right after "
         "pressing play). Within ~10 seconds you should get a \"Stream did "
         "not start\" notification naming the channel.", "view:list"),
        ("Check that channel then appears in the stream retry list rather "
         "than vanishing without trace.", "view:list"),
        ("Play a series episode and confirm normal playback is unaffected.",
         "view:list"),
    ),
)
