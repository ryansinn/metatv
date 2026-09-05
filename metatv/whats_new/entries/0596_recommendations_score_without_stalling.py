from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=596,
    version="0.97.0",
    date="2026-09-05",
    title="Recommendations score without stalling the interface",
    items=(
        "Recommendations are scored from plain rows instead of full database "
        "objects, so a Preferences refresh no longer freezes the interface "
        "for seconds on a large library.",
    ),
    test_steps=(
        "On a large library, open Preferences and refresh — the window "
        "stays responsive, and the watchdog logs no multi-second stall "
        "naming score_candidates.",
        "The recommendations shown are the same as before the update.",
    ),
)
