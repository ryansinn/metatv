from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=584,
    version="0.94.0",
    date="2026-09-03",
    title="The Sports and Events views are retired",
    items=(
        "Both views are removed from the navigation — the provider data "
        "behind them (dead feeds behind true labels, slots relaying other "
        "content, junk timestamps) could not support an honest live-sports "
        "surface, and a view that cannot verify its claims spends trust.",
        "Live sports channels remain in search and browse, wearing the live "
        "flag.",
        "The classification data layer stays and keeps improving in the "
        "background, should the surface return.",
    ),
    test_steps=(
        "Launch: the nav strip shows no Sports or Events entries; the app "
        "opens normally.",
        "Search 'ESPN' → the channel appears with the live badge and plays.",
    ),
)
