from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=418,
    version="0.53.0",
    date="2026-08-29",
    title="The log stops drowning itself",
    items=(
        "Two debug lines, written once for every title in your library, were "
        "90% of everything in the log folder - 330 MB.",
        "That meant seven days of retention held about eight days of noise "
        "where it could have held seventy-six days of useful history.",
        "Those lines are gone, and the log now records normal activity rather "
        "than debug detail by default.",
        "Set METATV_LOG_LEVEL=DEBUG to turn the detail back on for a support "
        "session, without needing a new build.",
    ),
    test_steps=(
        "Run the app normally for a few minutes, then check the log folder - "
        "it should grow far more slowly than before.",
        "Confirm errors and warnings still appear in the log.",
        "Start with METATV_LOG_LEVEL=DEBUG and confirm the detailed lines "
        "come back.",
    ),
)
