"""What's New entry: the Watch Queue showed its oldest items first, and mixed
unplayable ones in among the rest."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=289,
    title="The Watch Queue shows what you just added, not what you forgot",
    items=(
        "\"Never Watched\" listed items in the order they were added — oldest "
        "first, always. On a queue that has been filling up for months, that "
        "meant the top was permanently the things you added first and no longer "
        "remember, while anything you queued today sat hundreds of rows down "
        "where you would never see it.",
        "It now lists newest first, matching \"Continue Watching\" directly "
        "above it. The two groups used to sort in opposite directions.",
        "Items whose source has been removed are now grouped together at the "
        "bottom under \"Unavailable\", instead of scattered through the list. "
        "Mixed in, they read as though the queue had broken; \"Clear "
        "Unavailable\" in the right-click menu removes them all.",
        "Both group headers now show a count, so the queue's size is visible "
        "rather than something you have to scroll to discover.",
        "Nothing was added to or removed from your queue — this only changes "
        "the order things are shown in.",
    ),
    version="0.26.0",
    date="2026-08-03",
    test_steps=(
        "Open the Watch Queue in the sidebar. The \"Never Watched\" header "
        "shows a count of watchable items.",
        "Queue something new from the channel list. It appears at the TOP of "
        "Never Watched, not the bottom.",
        "Scroll to the end of Never Watched — the oldest additions are there, "
        "and they are still present (nothing was dropped).",
        "If you have items from a deleted or disabled source, they are grouped "
        "under an \"Unavailable (N)\" header at the bottom, dimmed, and not "
        "mixed in with watchable items.",
        "Confirm an unavailable item that you have played does NOT appear in "
        "Continue Watching.",
        "Right-click and choose \"Clear Unavailable\" — those entries go and the "
        "Unavailable header disappears; watchable items are untouched.",
        "With no unavailable items, confirm no \"Unavailable\" header is shown.",
    ),
)
