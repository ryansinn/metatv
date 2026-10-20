from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=758,
    version="0.195.0",
    date="2026-10-20",
    title="Fresh start, from the Tools menu",
    items=("Tools → Fresh start deletes the library, watch history, favourites, ratings, "
           "settings and cached images, then restarts MetaTV as a new install.",
           "Tools → Fresh start, keep sources does the same but keeps your sources: "
           "MetaTV restarts and loads them again as if you had just added them.",
           "Logs and recordings/downloads are never touched. Both ask before doing anything."),
    test_steps=("Tools → Fresh start, keep sources… → Yes — MetaTV closes, restarts empty, "
                "and your sources reappear and start loading their channels.",
                "Tools → Fresh start… → Yes — MetaTV restarts on the Add Source form with "
                "no sources, default settings and no history."),
)
