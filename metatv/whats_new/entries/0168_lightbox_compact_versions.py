from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=168,
    version="0.11.0",
    date="2026-07-30",
    title="Similar Titles lightbox — compact Other-Versions chips in the hero's upper-right",
    items=(
        "\"Other Versions\" no longer repeats the same title, year and source on a "
        "full-width pill for every version. Each version is now a small chip showing "
        "only what makes it different — its quality/region token (4K, LAT, DE…) — "
        "with the source's icon and colour as a badge.",
        "The chips moved into the previously-empty upper-right of the preview, beside "
        "the title and buttons, and flow-wrap there. That reclaims the wasted space "
        "and makes the whole card shorter.",
        "Hover any chip to see its full name and source; click it to jump straight to "
        "that version — same as before.",
    ),
    test_steps=(
        "Open the Similar Titles preview lightbox on a movie/series that has several "
        "versions across sources (e.g. one with an \"×N versions\" badge on the meta "
        "line): the \"Other Versions\" chips appear in the card's upper-right, each a "
        "compact token (4K/region code) with a small source icon/colour badge — NOT a "
        "stack of full-width pills repeating the same title/source.",
        "Hover one chip: a tooltip shows the full version name and its source.",
        "Click a chip: the preview navigates to that version (a Back step appears).",
    ),
)
