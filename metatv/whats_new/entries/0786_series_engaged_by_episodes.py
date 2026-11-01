from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=786,
    version="0.222.0",
    date="2026-11-01",
    title="Removing a source keeps the series you watched episode by episode",
    items=("When you delete or prune a source, MetaTV keeps what you've engaged with — "
           "favourites, plays, the queue, ratings. A series you only watched episode by episode "
           "didn't count, so it was removed and its watched episodes were left behind. It now "
           "counts, and stays with its episodes.",),
    test_steps=("Watch an episode of a series without favouriting the series, then delete that "
                "series' source — the series stays in History and Reconnect with its watched "
                "episode.",),
)
