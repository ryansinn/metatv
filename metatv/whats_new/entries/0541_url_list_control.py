from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=541,
    version="0.81.0",
    date="2026-09-02",
    title="Source URL list: try-first, click-to-copy, undoable remove, fills the pane",
    items=(
        "The up/down reorder arrows on a source's URL list are gone — they "
        "never actually worked, since the saved order was only the LAST "
        "tiebreak behind cooldown/health/latency, so real-world evidence "
        "always overrode a manual reorder. In their place: ⤒ arms a URL to "
        "be tried first on the very next connection attempt — a one-shot "
        "override for when you know something the stats don't. It clears "
        "itself automatically as soon as that next attempt is recorded, so "
        "evidence takes back over.",
        "Click a URL's text to copy it — no separate copy button needed.",
        "Removing a URL no longer asks for confirmation or deletes it "
        "outright: the row dims with a strikethrough and an undo button in "
        "place of ×. The URL is only actually removed when you click Save; "
        "undo any time before that to keep it.",
        "The URL list now fills the available height of the Connection tab "
        "instead of capping at a small scrolling box a few rows tall.",
    ),
    test_steps=(
        "In a source's Connection tab, click ⤒ on a lower URL: it jumps to "
        "#1 with the button highlighted, and after Save the next connection "
        "tries it first.",
        "Click a URL's text: a 'Copied ✓' tip appears and the URL is on the "
        "clipboard.",
        "Click × on a URL: the row dims with strike-through and an undo "
        "button instead of disappearing; undo restores it; Save deletes it.",
        "Open a source with several URLs in a tall window: the URL list "
        "fills the pane instead of scrolling inside a ~4-row box.",
    ),
)
