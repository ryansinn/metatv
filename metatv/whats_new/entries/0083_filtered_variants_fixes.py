from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=83,
    version="0.9.0",
    date="2026-06-28",
    title="Filtered Variants section: chips populate, header clickable, hidden when empty",
    items=(
        "Expanding the FILTERED VARIANTS section now shows the greyed variant chips "
        "(layout height was computed as zero while collapsed due to an ancestor-visibility bug).",
        "Clicking the FILTERED VARIANTS text label now toggles the section, same as the chevron.",
        "The FILTERED VARIANTS header no longer appears when there are zero filtered variants.",
    ),
    test_steps=(
        "Open a title that has content-category-filtered variants (e.g. a prefix that is "
        "deselected in Content Categories). The 'FILTERED VARIANTS' header should appear "
        "below the active chips. Click the '>' chevron — the greyed chips should expand "
        "and be visible.",
        "Click the 'FILTERED VARIANTS' text label (not the chevron) — the section should "
        "collapse/expand just like clicking the chevron does.",
        "Open a title whose all variants are active (none filtered). Confirm the 'FILTERED "
        "VARIANTS' header does not appear at all.",
        "Switch from a title with filtered variants to a title with none — confirm the "
        "FILTERED VARIANTS header disappears on the second title.",
    ),
)
