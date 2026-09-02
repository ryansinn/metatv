from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=539,
    version="0.79.0",
    date="2026-09-02",
    title="A player that closes without playing anything now says why",
    items=(
        "The last release caught streams that opened and stayed empty. It "
        "could not catch the other kind — the player closing again straight "
        "away, with nothing to show. There was no player left to ask, so "
        "nothing was reported at all.",
        "That case is now reported too, and it names the likely reason. "
        "Resuming a part-watched title at a position past the end of the "
        "file ends it instantly, so the message tells you where it was "
        "resuming from and that playing from the start will work.",
        "Closing the player yourself is still silent, and a failed play is "
        "still only reported once however it failed.",
    ),
    test_steps=(
        ("Play something part-way through, close the player yourself. There "
         "must be NO error — this is the case that must stay quiet.",
         "view:list"),
        ("Play a movie you have a resume position for and confirm it resumes "
         "normally.", "view:list"),
        ("Play a channel you know is dead. Within a few seconds you should "
         "get one \"Stream did not start\" notification — exactly one, not "
         "two.", "view:list"),
        ("Confirm a failed play appears in the stream retry list.",
         "view:list"),
    ),
)
