"""What's New entry: ChannelStateBus phase 2 — the favorite star now actually
repaints via the bus (a #311 claim that didn't work), and the hidden/queue
axes now publish too, so the details pane never stalls after any of those
actions from another view."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=312,
    title="Favorite star, Watch Queue, and Hide now sync live in the details pane",
    items=(
        "The previous release (#311) claimed the details pane's favorite star "
        "would update live from other views, but the wiring was incomplete: "
        "the async re-read fetched the right favorite state, and the details "
        "pane's action bar simply never applied it. Favoriting a title from "
        "the channel list while its details pane was open still left the star "
        "unfilled. Fixed — the star now applies on every re-read, same as "
        "rating/suppressed/hidden already did.",
        "Adding to or removing from the Watch Queue, and hiding a title (from "
        "History, Watch Alerts, or Recommendations), now also announce the "
        "change on the same publish point — so the details pane's Watch Later "
        "and Hide buttons stay live too, not just rating/favorite/suppressed.",
    ),
    version="0.29.0",
    date="2026-08-15",
    test_steps=(
        "Open a movie's details pane, then favorite the SAME title from the "
        "channel list (right-click → Favorite) without re-selecting it in the "
        "pane — the pane's favorite star fills in on its own. (This is a "
        "repair: the prior release's What's New claimed this already worked; "
        "it did not.)",
        "With a title open in the details pane, right-click it in the channel "
        "list and add it to the Watch Queue — the pane's Watch Later button "
        "becomes checked without re-selecting the title.",
        "With a title open in the details pane, right-click it in History and "
        "choose Hide — the pane's Hide button flips to its \"unhide\" state "
        "without re-selecting the title.",
    ),
)
