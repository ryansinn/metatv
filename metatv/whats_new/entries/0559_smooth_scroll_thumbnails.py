from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=559,
    version="0.86.0",
    date="2026-09-03",
    title="Smoother scrolling through poster-heavy lists",
    items=(
        "Scrolling the channel list no longer stalls the app while a poster "
        "thumbnail is loaded — painting a row now only ever reads an "
        "in-memory cache; anything not already resident loads in the "
        "background and the row updates once it lands, instead of the app "
        "freezing on a disk read mid-scroll (measured: a 567ms stall, worst "
        "case 2,705ms, in one launch).",
    ),
    test_steps=(
        "Scroll fast through a poster-heavy list right after launch (before "
        "posters have loaded) → no hitching or freezing; placeholder tiles "
        "fill in with real posters as they load.",
        "Scroll back up over rows you already passed → their posters appear "
        "instantly (already in memory), with no re-fetch stall.",
    ),
)
