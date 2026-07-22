from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=152,
    version="0.10.0",
    date="2026-07-22",
    title="What's New entries no longer clip their own text",
    items=(
        "Long entries in this very dialog used to cut a bullet off mid-sentence "
        "after about three lines, with a lot of empty space left below it. The "
        "title and bullet labels were being measured at the wrong width during "
        "layout, so Qt handed them a box shorter than the wrapped text actually "
        "needed and clipped the rest.",
        "Every entry now expands to whatever height its full text needs — the "
        "dialog body is the only scrollable surface, and there is no per-item "
        "scrollbar or height cap hiding content anymore.",
    ),
    test_steps=(
        "Open Help → What's New (or trigger it via an app update): the newest "
        "entry's title and every bullet are fully readable end-to-end, with no "
        "bullet cut off partway through a sentence.",
        "Step through older entries with the ‹ / › arrows, including ones with "
        "long multi-sentence bullets: each entry's card grows to fit its own "
        "text and only the dialog body scrolls — never a smaller scrollbar "
        "trapped inside the card itself.",
    ),
)
