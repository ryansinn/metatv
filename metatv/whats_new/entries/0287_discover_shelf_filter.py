"""What's New entry: a filter box for Discover's shelves."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=287,
    title="Find a Discover shelf by typing its name",
    items=(
        "A large library produces a lot of shelves — nearly 1,900 on the test "
        "library — which made scrolling to a particular one impractical.",
        "Discover's header now has a filter box. Type any part of a shelf's "
        "name to show just the shelves that match, and clear it to bring "
        "everything back.",
        "It covers every kind of shelf, not only collections, so genres and "
        "decades are reachable the same way.",
        "Filtering only changes what is shown. Pinned and expanded shelves stay "
        "exactly as you left them, and the box starts empty on each launch — a "
        "filter restored at startup would look like an empty Discover.",
        "The obvious alternative — only showing collections above some size — "
        "was measured and rejected: it barely reduces the count and hides real "
        "collections for no benefit.",
    ),
    version="0.26.0",
    date="2026-08-03",
    test_steps=(
        "Open Discover. There is a \"Filter shelves…\" box in the header bar.",
        "Type part of a collection name. Only matching shelves remain visible; "
        "everything else disappears, including the section dividers that no "
        "longer have anything under them.",
        "Type something that matches nothing — the shelf area empties without "
        "any error.",
        "Clear the box with its ✕. Every shelf returns, in its original "
        "section.",
        "Pin a shelf, filter it out of view, then clear the filter — it is "
        "still pinned and still at the top.",
        "Type part of a genre or decade name and confirm those shelves match "
        "too.",
        "Switch to another view and back: the box is empty again, showing all "
        "shelves.",
    ),
)
