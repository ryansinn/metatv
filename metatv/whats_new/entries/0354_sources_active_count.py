from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=354,
    version="0.41.0",
    date="2026-08-25",
    title="Sources counted an expiring source as not active",
    items=(
        "The Sources footer said \"No active sources\" on an install with two "
        "working sources. \"Active\" and \"expiring\" were counted as exclusive "
        "categories, so an enabled source whose subscription was near renewal "
        "was counted only as expiring — and if all of them were near renewal, "
        "the count of active ones came out zero.",
        "They are separate questions now: is this source enabled and serving, "
        "and is its subscription running out. A source can be both.",
    ),
    test_steps=(
        "With two enabled sources whose subscriptions are near renewal → the "
        "Sources footer reads \"2 expiring\", never \"No active sources\".",
        "With enabled sources and no subscription warnings → it reads "
        "\"N active\".",
        "Disable every source → NOW it reads \"No active sources\", because "
        "that is true.",
        "With no sources configured at all → \"No sources yet\".",
    ),
)
