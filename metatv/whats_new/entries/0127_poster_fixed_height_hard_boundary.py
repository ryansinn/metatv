from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=127,
    version="0.9.0",
    date="2026-06-29",
    title="Details poster has a fixed height — the Play buttons no longer move",
    items=(
        "The poster area is now a HARD FIXED height, so the Play / Watch Later buttons "
        "below it stay put when you move between titles (before, the box height changed "
        "with each poster and the buttons jumped around).",
        "The poster is fit INSIDE that fixed box, so it can never push past the right "
        "edge of the panel — its width is capped to the card (some side padding is fine; "
        "overflow is not).",
        "Added a hard right gutter so the poster and text can never slide under the "
        "vertical scrollbar, and the default details-panel width is set to 452 (where a "
        "standard portrait poster fills the card cleanly).",
    ),
    test_steps=(
        "Open a title with a poster, then arrow up/down through several titles: the Play "
        "and Watch Later buttons stay at the exact same position the whole time (the "
        "poster box height never changes).",
        "Open a title whose poster is portrait (e.g. Cowboy Bebop): the poster stays "
        "inside the panel — it never runs off the right edge or under the scrollbar.",
        "Drag the details panel wider and narrower: the poster height stays fixed; at "
        "wider widths it just gains a little side padding rather than growing taller.",
        "Open a LIVE channel with a logo: the logo still sits centered in the same fixed "
        "poster area.",
    ),
)
