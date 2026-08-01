from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=214,
    version="0.18.0",
    date="2026-08-01",
    title="Title cleanup now recovers from interrupted runs",
    items=(
        "The one-time library re-parse (which fixes titles like '. Spider-Man: "
        "Far from Home') could be marked complete even if it crashed partway — "
        "for example on a transient 'database is locked' — so the cleanup never "
        "retried and affected titles stayed wrong. Interrupted maintenance "
        "passes now correctly retry on the next launch, and the title re-parse "
        "runs again once to finish the job.",
    ),
    test_steps=(
        "Launch the app after updating → the migration progress strip runs the "
        "'Cleaning channel title qualifiers' pass once.",
        "Search for the previously affected title (e.g. Spider-Man: Far from "
        "Home on the MULTI prefix) → it now displays without the leading '. '.",
        "Relaunch → the pass does NOT run again (version sticks only after a "
        "clean completion).",
    ),
)
