from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=656,
    version="0.115.0",
    date="2026-09-08",
    title="The tag store shrinks by hundreds of MB, and facet counts run faster",
    items=(
        "content_tags — the table linking every channel to its genre/region/"
        "platform/quality tags — used to key each row on the channel's full "
        "43-byte id string. It now uses a small internal integer instead, which "
        "shrinks the table (and lets a whole redundant index disappear) and "
        "makes every facet count, filter-panel value, and recipe result faster "
        "to compute — measured ~4x on the busiest facet-count query. This "
        "requires a one-time rebuild of the tag store, which runs automatically "
        "the first time you launch this build: expect a launch pause (tens of "
        "seconds) while it happens, after which every future launch is normal "
        "speed. Nothing about which tags exist, what they mean, or how filters "
        "behave changes — this is purely internal storage.",
    ),
    test_steps=(
        "Launch the app once after updating — it may pause noticeably longer "
        "than usual before the window appears (a one-time tag-store rebuild); "
        "check ~/.config/metatv/logs/ for a 'DB-9: content_tags rebuild "
        "complete' line confirming it ran and how long it took.",
        "After that launch, open the filter panel and a few genre/platform "
        "shelves — facet counts and shelf contents look exactly as before.",
        "Launch the app again — no rebuild pause this time, and everything "
        "still works.",
    ),
)
