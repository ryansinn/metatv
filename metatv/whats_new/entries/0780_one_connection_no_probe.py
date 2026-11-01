from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=780,
    version="0.216.0",
    date="2026-11-01",
    title="One-connection sources start plays without being turned away",
    items=("Before playing, MetaTV used to check the stream with a quick connection of its own. "
           "On a source that allows one connection at a time, that check held the only slot "
           "just as the player tried to connect, and the source refused the play (on TREX, "
           "about one fresh play in seven). MetaTV now skips the check on those sources and "
           "plays straight from the best-ranked server address.",),
    test_steps=("With nothing playing, play a channel from TREX (one connection) — it starts "
                "without a \"connections in use\" refusal; the log says \"one-connection source: "
                "probe skipped\".",
                "Play from a source that allows several connections — the stream is still checked "
                "first (no \"probe skipped\" line).",),
)
