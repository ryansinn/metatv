from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=421,
    version="0.53.0",
    date="2026-08-29",
    title="Recommendations stop failing outright on a fresh library",
    items=(
        "On a library with few or no exclusions set up, Recommended showed "
        "\"Couldn't load recommendations\" and nothing else.",
        "It was asking the database about every candidate title in a single "
        "question, and past a certain size the database refuses the question "
        "rather than answering it slowly.",
        "That size is reached easily on a new install, which is exactly when "
        "nothing has been excluded yet.",
        "It now asks in batches, and no longer loads a large block of raw "
        "provider data it never reads - about a fifth off both the time and "
        "the memory.",
    ),
    test_steps=(
        "On a machine with no Global Exclusions configured, open the "
        "Recommended section and confirm it fills rather than showing an "
        "error.",
        "Confirm the recommendations shown are still sensible for your "
        "likes.",
        "On a machine that already had working recommendations, confirm they "
        "are unchanged.",
    ),
)
