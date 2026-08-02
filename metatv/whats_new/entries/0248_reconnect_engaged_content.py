"""What's New entry for Reconnect Engaged Content (Tools view)."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=248,
    title="Reconnect Engaged Content",
    items=(
        "When a source is removed or expires, your favorited/watched/queued "
        "content from it used to just sit there, stranded and pointing at a "
        "gone source. Tools → 'Reconnect Engaged Content' now lists every one "
        "of those orphaned rows next to a proposed same-title match on one of "
        "your active sources, and lets you move the favorite, watch history, "
        "resume position, rating, and queue membership onto the live copy — "
        "one row at a time, or all matched rows at once. Nothing moves "
        "automatically; unmatched rows are listed too, plainly marked as such.",
    ),
    version="0.23.0",
    date="2026-08-03",
    test_steps=(
        "Favorite a movie/series, then delete or deactivate its source (while "
        "an identical title exists on another active source) → open Tools → "
        "'Reconnect Engaged Content' → the orphaned row appears with a proposed "
        "live match and a 'Reconnect' button.",
        "Click 'Reconnect' on a matched row → a success toast appears, the row "
        "disappears from the list, and the item now shows as favorited on the "
        "live source (check the sidebar Favorites section).",
        "With multiple matched rows present, click 'Reconnect All' → every "
        "matched row is reconnected in one action and a summary toast reports "
        "how many succeeded.",
        "A row with no live match on any active source is still listed, "
        "clearly marked 'No live match found' with no Reconnect button.",
    ),
)
