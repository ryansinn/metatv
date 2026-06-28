from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=100,
    version="0.9.0",
    date="2026-06-28",
    title="Fix: consistent collapse carets across details-pane sections",
    items=(
        "The 'Similar Titles' and 'Filtered Variants' collapse caret buttons in "
        "the details pane looked different from the other sections — Similar "
        "Titles was frameless and Filtered Variants was both smaller (16×16) and "
        "frameless. They now match the Tags / Technical Details / Cast & Crew "
        "carets exactly: a framed 20×20 button.",
    ),
    test_steps=(
        "Open a VOD title's details and expand the Tags, Technical Details, and "
        "Cast & Crew sections; note their caret/toggle buttons (framed, 20×20).",
        "Confirm the 'Similar Titles' caret looks identical to those reference "
        "carets — same size and same button frame, not frameless.",
        "Open a title with filtered (blocked-prefix) source variants so the "
        "'FILTERED VARIANTS' sub-header appears; confirm its caret also matches "
        "the reference carets (framed, 20×20), not smaller or frameless.",
    ),
)
