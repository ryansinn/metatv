from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=651,
    version="0.111.0",
    date="2026-09-08",
    title="Hiding, favoriting, or queuing a multi-selection updates every view at once",
    items=(
        "Multi-select 'Hide', 'Add to Favorites', and 'Add to Queue' wrote every "
        "selected channel's state but never told the rest of the app about it — the "
        "same bug #311 fixed for single-channel actions, reopened for the bulk path. "
        "Bulk-hiding a title while its details pane was open left the pane's buttons "
        "showing the old state, exactly like the single-channel bug used to. Each "
        "channel in a bulk selection now announces its own change the same way a "
        "single click does, so every view — not just the one the action was performed "
        "from — updates immediately.",
        "The three bulk actions' writes also moved off the UI thread (matching every "
        "other favorite/hide/queue toggle already there), so a large multi-selection "
        "no longer risks a visible freeze while it commits.",
    ),
    test_steps=(
        "Select several channels in the channel list, open one of them in the details "
        "pane, then multi-select 'Add to Favorites' on the group including that "
        "channel — the details pane's Favorite button updates to favorited without "
        "reselecting the channel.",
        "Same as above with multi-select 'Hide' — the details pane's state reflects "
        "hidden immediately, and the channel disappears from the list.",
        "Same as above with multi-select 'Add to Queue' — the details pane's Watch "
        "Later button updates to queued immediately, and the Watch Queue sidebar "
        "section shows the new entries.",
    ),
)
