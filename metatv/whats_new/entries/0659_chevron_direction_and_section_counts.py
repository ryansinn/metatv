from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=659,
    version="0.117.0",
    date="2026-09-09",
    title="Disclosure chevrons point the right way, and more sections say how much they hold",
    items=(
        "Every collapsible section that used the vector chevron icon (the "
        "details pane, Filter groups, Discover shelves, Preferences, "
        "Categories) had its 'expand' and 'collapse' icons swapped: a closed "
        "section showed a down-pointing chevron and an open one showed a "
        "right-pointing chevron, backwards from the usual convention. "
        "Collapsed now points right, expanded now points down, everywhere.",
        "The Cast and Tags sections in the details pane now state a count "
        "next to their title, the way Similar Titles and Also Available "
        "already did — e.g. Cast shows how many people are listed, Tags "
        "shows how many tags are shown.",
    ),
    test_steps=(
        "Open a movie or series in the details pane — a COLLAPSED section "
        "(e.g. Technical Details, if closed) shows a right-pointing chevron; "
        "click it open and the chevron now points down.",
        "Open a title with cast credits — the Cast section header shows a "
        "number next to 'Cast' matching how many people are listed.",
        "Open a title with tags — the Tags section header shows a number "
        "matching how many tags are shown below it.",
        "Open Preferences and toggle the attribute breakdown / Version "
        "Preferences / Excluded panels — each closed panel's chevron points "
        "right, each open one points down.",
    ),
)
