from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=769,
    version="0.206.0",
    date="2026-10-31",
    title="Sources Analytics now shows how playback from each source goes",
    items=("MetaTV now remembers how each play went — started, never loaded, refused because "
           "the source's connections were in use, or dropped partway — and how long it took "
           "the picture to appear. The Sources editor's Analytics tab has a new Playback section "
           "that sums this up per source.",
           "Counting starts with this version; plays from before it were never recorded. "
           "Plays older than 90 days are kept as weekly totals.",
           "The Analytics sections now follow the agreed order: Only here, Shared, Playback, "
           "Server addresses, Catalogue & guide, Unrecognized prefixes.",),
    test_steps=("Open Sources → a source → Analytics before playing anything — Playback says "
                "\"Nothing recorded yet\".",
                "Play a few titles from that source and let each run for a few seconds; open "
                "Analytics again — Playback shows \"Plays started N of N\" and a typical time to "
                "picture in seconds, with \"since\" today's date.",
                "Play something on a one-connection source while another stream from it is "
                "already open, so it is refused — Analytics counts one under \"Refused — "
                "connections in use\".",
                "Check the section order on the Analytics tab: Only here, Shared, Playback, "
                "Server addresses, Catalogue & guide, Unrecognized prefixes.",),
)
