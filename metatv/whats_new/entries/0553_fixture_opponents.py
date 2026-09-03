from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=553,
    version="0.85.0",
    date="2026-09-02",
    title="Sports fixtures now know who's playing",
    items=(
        "Sports fixture names are now parsed into their two opponents and "
        "stored at ingestion — the 'vs'/'@'/'x' forms and the uppercase "
        "dash matchup form ('ESBJERG - FREDERIKSHAVN') are all recognised; "
        "a racing 'Series at Venue' event correctly stores no opponents, "
        "since it has none.",
        "This is backfilled automatically for existing fixtures at next "
        "launch, and is the data layer the Team facet, team identity on "
        "rows, and reliable live-status features build on next.",
    ),
    test_steps=(
        "After one restart (the migration runs at launch), inspect a "
        "fixture row's stored data in the dev tools or logs: "
        "event_team_a/event_team_b carry the two teams for a 'vs' fixture.",
        "A racing 'Series at Venue' event stores no opponents — by "
        "design, it has none.",
    ),
)
