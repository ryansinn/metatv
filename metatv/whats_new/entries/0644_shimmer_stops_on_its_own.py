from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=644,
    version="0.108.0",
    date="2026-09-08",
    title="A stuck Discover card's shimmer no longer runs forever",
    items=(
        "A Discover card's loading shimmer animation used to run indefinitely until its "
        "poster arrived or failed to load. If a future bug ever left a card un-notified "
        "again — the same shape as #815's resident-poster bug — hundreds of infinite "
        "animations could still peg the main thread with repaints.",
        "The shimmer now caps itself at about 18 seconds of animation, far longer than any "
        "healthy poster load, and settles to the static placeholder icon on its own if "
        "nothing ever arrives — independent of whatever bug caused the silence.",
        "Also added a contract test that checks every way a poster request can resolve "
        "(already in memory, already on disk, a fresh download, a failed download, a "
        "cooled-down host, an empty url, a duplicate in-flight request, and a direct "
        "paint-time request) notifies both the card's own callback and the shared "
        "broadcast — so the next delivery-path gap like #815 shows up as a failing test "
        "instead of a blank shelf.",
    ),
    test_steps=(
        "Open Discover, scroll through several shelves so many cards load posters — every "
        "card ends up showing either its poster or the placeholder icon, none left "
        "shimmering indefinitely.",
        "With network access disabled or a provider unreachable, open Discover — cards "
        "whose posters can't load settle to the placeholder icon within a few seconds "
        "rather than shimmering forever.",
    ),
)
