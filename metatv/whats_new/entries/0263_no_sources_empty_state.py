"""What's New entry for the honest zero-sources channel-list empty state."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=263,
    title="A fresh install now tells you plainly that you need to add a source",
    items=(
        "On a brand-new install (or after removing every source), the "
        "channel list used to say \"No channels match — try a different "
        "search or check filter settings\" — blaming search/filters for a "
        "problem that was actually \"you have no source yet\".",
        "It now shows an honest \"No sources configured yet\" message above "
        "the empty list, with a clear Add Source button that opens the same "
        "source editor as the existing '+' buttons.",
        "Every other zero-results case (search, filters, Global Exclusions) "
        "is unchanged — this new message only appears when there is truly "
        "no source configured.",
    ),
    version="0.24.0",
    date="2026-08-02",
    test_steps=(
        "Remove every configured source (Sources → delete each one) so none "
        "remain — the channel list shows \"No sources configured yet — add "
        "one to start browsing channels.\" with a visible, enabled Add "
        "Source button, not the old \"try a different search\" message.",
        "Click the Add Source button — the same source-editor dialog the "
        "sidebar Sources '+' button opens appears.",
        "Add a source, then in the channel list search for gibberish that "
        "matches nothing — the ORIGINAL \"No channels match — try a "
        "different search or check filter settings\" message shows, and no "
        "Add Source button appears.",
    ),
)
