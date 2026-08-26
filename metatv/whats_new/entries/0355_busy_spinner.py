from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=355,
    version="0.41.0",
    date="2026-08-25",
    title="The busy hint actually spins now",
    items=(
        "Watch Alerts showed \"⟳ checking…\" on the Movies & Series header — a "
        "static glyph and a word, in a header already carrying a title, a "
        "count and a news total. It is a small spinning indicator now, with "
        "the words in its tooltip.",
    ),
    test_steps=(
        "Start the app with monitored series → a small indicator appears on "
        "the Movies & Series header while the check runs, and it is visibly "
        "ROTATING, not a static symbol.",
        "Hover it → the tooltip says it is checking monitored series for new "
        "episodes.",
        "Wait for the check to finish → the indicator disappears and the "
        "header no longer contains the word \"checking\".",
        "If it keeps spinning for minutes, that is a stuck provider call — "
        "report it; the indicator is doing its job by making that visible.",
    ),
)
