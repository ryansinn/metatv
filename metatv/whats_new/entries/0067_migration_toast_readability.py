from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=67,
    version="0.9.0",
    date="2026-06-24",
    title="Migration progress panel is readable again",
    items=(
        "The background-migration progress panel no longer clips or overlaps its "
        "step labels. Each step now puts its description on its own full-width line "
        "with the progress bar and percentage on the line below, so long labels like "
        "'Cleaning channel title qualifiers' are fully legible.",
        "The progress bar now stretches to fill the panel width, making progress "
        "easier to read at a glance.",
    ),
    test_steps=(
        "Trigger a migration (e.g. launch after an update that bumps a migration "
        "version) and watch the bottom-right 'Migration in progress' panel.",
        "Confirm each task's label is shown in full on its own line — not clipped, "
        "truncated, or overlapping the progress bar or the row below it.",
        "Confirm the progress bar spans the panel width and the percentage reads "
        "clearly (e.g. 100%) to its right.",
    ),
)
