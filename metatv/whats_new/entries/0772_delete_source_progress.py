from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=772,
    version="0.208.0",
    date="2026-10-31",
    title="Deleting a source shows its progress",
    items=("Deleting a large source can take a minute. The \"Deleting source…\" notification now "
           "lists each stage — tags, guide entries, episodes, metadata, channels and so on — and "
           "ticks them off as they finish, so you can see it's still working.",),
    test_steps=("Delete a source you no longer need (Sources → the source → Delete) — the "
                "\"Deleting source…\" notification lists the stages, starting with Tags.",
                "Watch it — each stage turns done in order and the next one starts; the "
                "notification closes and \"Source deleted.\" shows when the last one finishes.",),
)
