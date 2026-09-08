from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=636,
    version="0.105.0",
    date="2026-09-08",
    title="Manage shelves groups them by family",
    items=(
        "Discover ▸ Manage shelves was one flat list per zone, so eighteen "
        "collections stood between you and the shelf you came to move. Every "
        "section now groups its rows under a family heading — Discover, "
        "Platforms, Collections, Genres, Decades, Featuring, your own "
        "categories and saved recipes — in that order, with the count on each.",
        "Click a heading to fold its rows away. The fold sticks: it is "
        "remembered per family and restored the next time you open the dialog, "
        "and it applies to every section at once so a family you are not "
        "working on stays out of the way.",
        "Pin, Hide, Collapse and Restore land the shelf under its family "
        "heading in the section it moves to, opening that heading if it is the "
        "first one there and clearing it away when the last one leaves. Move "
        "up and down now step within the family you can see, instead of "
        "appearing to do nothing when the next row belongs to another one.",
        "The Discover strip itself is unchanged — a platform shelf browses "
        "exactly like every other shelf, in the same zones, in the same order.",
    ),
    test_steps=(
        "Open Discover → Manage shelves → the rows in each section are grouped "
        "under headings (Platforms, Collections, Genres, Decades …) in that "
        "order, each stating its count.",
        "Click the Collections heading → its rows fold away and the heading "
        "keeps its count; close the dialog and reopen it → Collections is "
        "still folded.",
        "Find a platform shelf under Collapsed ▸ Platforms and press Hide → it "
        "appears under Hidden ▸ Platforms, and the Collapsed section's "
        "Platforms heading disappears if that was its last row.",
        "Press ↑ Up on a genre shelf that has another genre above it → it moves "
        "up one row inside Genres.",
        "Close the dialog and look at the Discover strip → it looks exactly as "
        "it did before: no family headings, shelves in their usual zones.",
    ),
)
