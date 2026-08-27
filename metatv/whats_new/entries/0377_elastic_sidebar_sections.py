from metatv.whats_new import WhatsNewEntry

# Four of this entry's original claims described groups folding to their
# headings under pressure and re-opening by themselves. That behaviour was
# removed later in the SAME unreleased 0.41.0 batch (see 0380) because it kept
# closing groups the user had opened, so the claims are dropped rather than
# left to fail the dev-QA checklist they exist to drive.
ENTRY = WhatsNewEntry(
    id=377,
    version="0.41.0",
    date="2026-08-26",
    title="Sidebar sections shrink all the way down",
    items=(
        "Any sidebar section can now be dragged down to just its header. "
        "Watch Alerts used to refuse to go below about 367px, which meant it "
        "took up a large fixed share of the sidebar whether you wanted it to "
        "or not.",
        "A section that is too short for its contents scrolls rather than "
        "clipping them, so every row stays reachable at any height.",
        "How much room each section asks for by default is unchanged; it is "
        "now a preference rather than a wall, so growing one section still "
        "never squeezes a neighbour below what it needs.",
    ),
    test_steps=(
        "Drag the handle under Watch Alerts upward - it now shrinks past the "
        "point it used to stop at, all the way down to just its header row.",
        "With the section short, scroll inside it - every group's rows are "
        "still reachable, nothing is clipped away.",
        "Grow Watch Alerts to fill the sidebar - the other sections shrink but "
        "none is squashed below the few rows it needs.",
        "Drag Watch Alerts down to its header - the title, the +N badge and "
        "the header buttons are all still fully drawn, not clipped.",
        "Restart the app - the section sizes you left are restored.",
    ),
)
