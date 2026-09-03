from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=577,
    version="0.92.0",
    date="2026-09-03",
    title="Sports events are labeled by what they are now, not what the slot once carried",
    items=(
        "Event-slot channels that rotate their title in place (e.g. FLO Network's FLSP "
        "slots) used to keep the sport they were first seen with — wrestling events were "
        "listed under the Tennis chip. A renamed slot now drops its old classification "
        "and is re-classified from its new title in the same refresh.",
        "A one-time repair pass at next launch re-classifies slots that went stale "
        "before this fix.",
    ),
    test_steps=(
        "Open Sports → Tennis chip: FLO wrestling slots ('(FLSP …) | wrestling: …') "
        "are no longer listed under Tennis (the one-time repair runs at launch).",
        "After a live refresh rotates an event slot's title to a different sport, "
        "the row appears under the new sport's chip on that same refresh.",
    ),
)
