from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=602,
    version="0.99.0",
    date="2026-09-05",
    title="The details pane stops re-rendering the title it already shows",
    items=(
        "Clicking a title that the details pane already shows no longer "
        "rebuilds it and re-fetches its metadata — two surfaces reaching the "
        "pane for one gesture used to spawn a second render and a second "
        "metadata fetch thread.",
        "The pane's provider-URL failover lookup now runs off the interface "
        "thread instead of blocking a click on a database read.",
    ),
    test_steps=(
        "Click a title, then click the same row again within a second — the "
        "log shows one render and no second metadata fetch.",
        "Click a different row — it renders as before.",
    ),
)
