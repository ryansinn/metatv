from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=491,
    version="0.64.0",
    date="2026-09-01",
    title="Live games were being filed as Finished",
    items=(
        "Sports fixtures were read as though their times were UTC. They are "
        "not — they are local. A game you were watching live could therefore "
        "show up under Finished, and refuse to be treated as on now.",
        "That was worse than the empty On Now lane it replaced: a wrong answer "
        "reads as a real one.",
        "Times are now read as local. Your fixtures are recomputed on the next "
        "launch, so nothing needs refreshing.",
    ),
    test_steps=(
        ("With a game actually in progress, open Sports and confirm it appears "
         "under On Now and not Finished.", "view:sports"),
        ("Check that a fixture which really has finished still appears under "
         "Finished.", "view:sports"),
        "Confirm a fixture starting later today appears under Upcoming.",
    ),
)
