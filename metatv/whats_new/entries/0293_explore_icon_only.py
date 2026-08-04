"""What's New entry: the sidebar said "Explore" four times."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=293,
    title="Less repetition in the sidebar headers",
    items=(
        "History, Favorites, Watch Queue and Recommended each carried an "
        "\"Explore →\" link, so the same word appeared four times down one "
        "narrow column — at which point it stops being read and is just "
        "crowding.",
        "The link is now the ⤢ icon alone, with \"Explore your Watch Queue\" "
        "(and so on) as its tooltip. It is the same glyph that used to open the "
        "cascading columns from a Similar title, so it already means \"open "
        "this out\".",
        "Deliberately not the ⌄ / > caret: the collapse toggle sits in the same "
        "header and uses those, and two identical glyphs meaning different "
        "things is worse than the crowding this removes.",
    ),
    version="0.26.0",
    date="2026-08-04",
    test_steps=(
        "Look at the sidebar: no section header says the word \"Explore\" any "
        "more — each shows a small ⤢ button instead.",
        "Hover the ⤢ on the Watch Queue. The tooltip names it: \"Explore your "
        "Watch Queue (cascading columns)\".",
        "Click it. The Explore view opens seeded with the Watch Queue, exactly "
        "as the text link did.",
        "Confirm the ⤢ is visually distinct from the ⌄ / > collapse toggle on "
        "the left of the same header, and that clicking the header (not the "
        "buttons) still collapses the section.",
        "Check all four sections — History, Favorites, Watch Queue, "
        "Recommended — carry the same icon.",
    ),
)
