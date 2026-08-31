from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=464,
    version="0.60.0",
    date="2026-08-31",
    title="Four things that were quietly wrong",
    items=(
        "Watch alerts could pop for a channel on a source you had switched "
        "off. The alert check filtered by which guide supplied the programme "
        "but not by which channel it was matched to, and those can be "
        "different sources — 418 of your programme rows are matched that way.",
        "The Preferences dashboard showed recommendations under the "
        "provider's raw channel name — \"EN| MOVIES: The Matrix (1999) FHD\" "
        "— while the sidebar showed \"The Matrix\" for the very same item. "
        "94.9% of your titles have a cleaned name that differs from the raw "
        "one.",
        "The \"Excluded\" and \"Version Preferences\" sections in Preferences "
        "forgot whether you had opened them. They now remember, like every "
        "other section does.",
        "The Sports filter bar had a \"Clear\" button beside a \"Clear All\" "
        "button — two names for the same thing, on one bar.",
    ),
    test_steps=(
        ("Open Preferences and check a recommendation's title reads like the "
         "sidebar's — a clean title, not the provider's raw string.",
         "view:preferences"),
        "Expand \"Excluded\" and \"Version Preferences\", restart the app, and "
        "confirm both are still open with the correct chevron.",
        "Collapse them, restart again, and confirm they stay collapsed.",
        ("Open Sports and check the Sport and League dropdowns — both footers "
         "should say \"Select All\" and \"Clear\".", "view:browse"),
        "Switch a source off in Sources. Confirm no watch alert fires for any "
        "of its channels, even ones whose guide data came from another source.",
    ),
)
