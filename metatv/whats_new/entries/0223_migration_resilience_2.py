from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=223,
    version="0.19.0",
    date="2026-08-01",
    title="Startup maintenance pass survives being interrupted by normal browsing",
    items=(
        "The one-time channel-cleanup pass could still crash on a busy "
        "library if you started browsing (opening details, viewing 'Other "
        "Versions') while it was running — a background TMDb id lookup "
        "triggered by that browsing could collide with the maintenance "
        "pass's own writes. Every write phase of the pass now retries a "
        "momentary lock instead of aborting the whole run, the background "
        "TMDb lookup now waits its turn while a maintenance pass is active, "
        "and fetching a channel's plot/cast/poster for the details pane no "
        "longer holds the database open for the whole network round trip.",
    ),
    test_steps=(
        "Launch the app with pending maintenance work (fresh install or "
        "after a version bump) → while the progress strip is running, click "
        "around the channel list and open a few channels' details panes → "
        "the maintenance pass completes without crashing and the details "
        "panes still populate (plot/cast/poster) normally.",
        "Relaunch → the progress strip does NOT reappear (no repeat of the "
        "same maintenance work).",
    ),
)
