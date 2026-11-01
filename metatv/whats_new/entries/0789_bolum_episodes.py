from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=789,
    version="0.225.0",
    date="2026-11-01",
    title="Turkish series filed as movies collapse into one card per show",
    items=("Some sources list a Turkish series as one \"movie\" per episode — \"Kızılcık Şerbeti 136. "
           "Bölüm @showtv\". MetaTV now reads the episode number out of the name, so a show's episodes "
           "group into one card instead of hundreds (on your library, 4,634 rows become 305 shows). "
           "Existing titles are updated on the next launch.",),
    test_steps=("Launch MetaTV, then search for \"Kızılcık Şerbeti\" in Movies — one card for the show, "
                "with its episodes as versions, instead of one per episode.",),
)
