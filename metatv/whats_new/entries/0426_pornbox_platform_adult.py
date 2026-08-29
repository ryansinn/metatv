from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=426,
    version="0.54.0",
    date="2026-08-29",
    title="Adult content from an unrecognised source is now caught",
    items=(
        "Channels from one adult provider were being shown as though PORNBOX "
        "were a country or a language, and were not marked adult at all - 30 "
        "channels, only 2 flagged.",
        "PORNBOX is now treated as the streaming platform it is, and as adult.",
        "More usefully, the provider's own collection is now a signal: a "
        "channel filed under a known adult collection is marked adult even if "
        "nobody recognised its source code.",
        "Titles are still never judged on their own. A film with XXX in its "
        "name is not adult content - the xXx franchise and A's to XXX are "
        "both ordinary films - so only the source and its collection count.",
    ),
    test_steps=(
        "Set adult content to hidden, then confirm PORNBOX channels no longer "
        "appear in Browse, Discover or recommendations.",
        "Confirm PORNBOX shows as a platform chip rather than a country or "
        "language chip.",
        "Confirm a film with XXX in its title is still visible.",
        "Confirm the 'For Adults' collection's channels are all marked adult.",
    ),
)
