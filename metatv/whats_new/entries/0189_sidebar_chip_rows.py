from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=189,
    version="0.15.0",
    date="2026-07-31",
    title="Watch Queue, Favorites and History rows match Recommended",
    items=(
        "The Watch Queue, Favorites and History sidebar lists now render each row "
        "as a clean title on the left with the quality badge hugging it, and a "
        "right-aligned year and audio-language chip — exactly like the Recommended "
        "list.",
        "The language chip shows the honest audio language (e.g. EN), not the "
        "source region, and the year is no longer jammed into the title text.",
        "History rows keep their episode code (e.g. → S01E02) as a visible suffix "
        "on the title.",
    ),
    test_steps=(
        "Open the Watch Queue section in the sidebar. Confirm each queued title "
        "renders as [icon] clean-title [4K, if any] … with the year and language "
        "chips aligned to the right edge — the same style as the Recommended list "
        "— and that no source region code appears jammed into the title.",
        "Open the Favorites section. Confirm favorite rows render the same chip "
        "row (clean title, right-aligned year/language chips) and that an "
        "unavailable favorite (on a disabled/expired source) is still dimmed.",
        "Open the History section. Confirm rows render the same chip row, and that "
        "a series entry still shows its episode code (e.g. → S01E02) next to the "
        "title.",
    ),
)
