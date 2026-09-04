from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=588,
    version="0.95.0",
    date="2026-09-04",
    title="Record from the guide",
    items=(
        "Any guide programme row — Watch Alerts, On Now, or Browse — can now "
        "schedule a recording, not just \"what's on now\".",
        "A new Settings ▸ Recording page sets the default start/end padding "
        "every new recording starts from.",
        "Scheduling one that clashes with another recording on a "
        "one-connection source is caught immediately, with a choice to drop "
        "either one rather than losing both silently later.",
        "If the guide moves a programme's time after you scheduled it, the "
        "recording's window follows and a notice names the new time.",
        "Quitting with a recording scheduled or running asks first — MetaTV "
        "has to stay open to record.",
    ),
    test_steps=(
        "Right-click an upcoming programme in Watch Alerts → \"Record this "
        "programme\" → it appears in the Recordings section with the "
        "configured padding applied.",
        "Schedule a second recording that overlaps the first on the same "
        "source → the conflict dialog offers to drop one.",
        "After an EPG refresh where a scheduled programme's start moved, the "
        "Recordings row shows the new time and a notice names it.",
        "With a recording scheduled, close the app → a confirmation appears "
        "before it quits.",
    ),
)
