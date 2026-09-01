from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=494,
    version="0.64.0",
    date="2026-09-01",
    title="Having to press play three or four times",
    items=(
        "Starting something could fail silently and need several attempts "
        "before it played.",
        "Most accounts allow one connection at a time. The background job that "
        "fills in missing genres and posters was quietly using it — so the "
        "check the app runs before opening a stream got an error, and the "
        "player was handed a connection the source had already refused.",
        "It now steps aside for anything you asked for, the same way the "
        "watchlist check already does. Enrichment resumes as soon as the "
        "connection is free.",
    ),
    test_steps=(
        ("Play several things in a row and confirm each starts on the first "
         "attempt.", "view:list"),
        "Play something immediately after launch, while genre backfill is "
        "still running, and confirm it starts first time.",
        ("Confirm posters and genres still fill in over time when nothing is "
         "playing.", "view:discover"),
    ),
)
