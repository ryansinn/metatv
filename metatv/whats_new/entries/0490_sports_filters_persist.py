from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=490,
    version="0.64.0",
    date="2026-09-01",
    title="Sports forgot which sport you were watching",
    items=(
        "Picking a sport, a league or typing a fixture search in Sports was "
        "forgotten every time the app restarted — back to everything, every "
        "launch.",
        "The lane you were on (On Now, Upcoming, Channels) was remembered, "
        "which made it look like only half the view forgot itself.",
        "Your selection is now restored on launch, including the fixture "
        "search box.",
    ),
    test_steps=(
        ("In Sports, pick a sport and a league, quit, relaunch: the same "
         "selection should be showing.", "view:sports"),
        ("Type something in the fixture search, restart, and confirm the text "
         "and its results come back.", "view:sports"),
        "Change the selection several times and confirm the app stays "
        "responsive — it must not rewrite settings on every keystroke.",
    ),
)
