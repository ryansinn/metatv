from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=130,
    version="0.9.0",
    date="2026-07-11",
    title="Fewer stalls and more reliable connections",
    items=(
        "Sources whose server labels the channel list with an unusual content-type "
        "header now load correctly instead of showing 0 channels.",
        "Usernames and passwords containing special characters (&, #, +, spaces) now "
        "work for both connecting and playing streams.",
        "A rejected login is no longer mis-reported as a successful connection.",
        "The channel list no longer permanently stops loading more items after a "
        "momentary database hiccup — it recovers on the next scroll.",
        "The Recommendations sidebar section shows a clear 'couldn't load' message "
        "instead of hanging on 'Loading…' forever if a refresh fails.",
        "View ▸ Refresh now actually reloads the channel list (previously it only "
        "refreshed the sidebar sources).",
    ),
    test_steps=(
        "Add a working Xtream source whose password contains an '&' or a space: it "
        "connects, loads channels, and streams play.",
        "Enter deliberately wrong credentials: the connection is reported as failed "
        "(not a false success).",
        "Scroll a long channel list to the bottom repeatedly: it keeps loading more "
        "pages (doesn't dead-end after a transient error).",
        "Use the View ▸ Refresh menu action: the channel list reloads (the status bar "
        "shows 'Refreshing channels...' and the list actually updates).",
    ),
)
