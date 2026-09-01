from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=497,
    version="0.64.0",
    date="2026-09-01",
    title="Pressing play repeatedly and never getting a picture",
    items=(
        "On a source that allows only one connection at a time, playback "
        "could fail over and over — the player window opening and closing "
        "while the stream itself was perfectly fine.",
        "Background checks release their connection as soon as they finish, "
        "but the source does not: it goes on counting a closed connection for "
        "up to a minute afterwards. So a watchlist check that ended seconds "
        "before you pressed play was still using up your only slot, and every "
        "retry landed inside the same window.",
        "Pressing play now claims the source before anything else touches it "
        "— including the few seconds spent checking the stream first — and "
        "keeps background work off it while you retry.",
    ),
    test_steps=(
        ("Play something immediately after launch, while watchlist checks are "
         "still running, and confirm it plays on the first press.",
         "view:list"),
        ("If a play does fail, press play again straight away and confirm the "
         "second attempt is not fighting background work.", "view:list"),
        "Leave the app idle for two minutes with nothing playing, and confirm "
        "watchlist and artwork checks still run (source toasts still appear).",
        "Start a recording and confirm it is never held back.",
    ),
)
