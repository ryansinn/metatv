from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=630,
    version="0.103.0",
    date="2026-09-07",
    title="Similar Titles tooltips lead with the whole title",
    items=(
        "In the details pane's Similar Titles rows, a long title is elided to fit "
        "the column and the tooltip was where you had to read it — but it showed "
        "only the actions (\"Click: preview in lightbox …\", \"Play: …\"), so the "
        "title stayed cut off. The tooltip now puts the full title on its first "
        "line and the actions on the second.",
    ),
    test_steps=(
        "Open a title with Similar Titles whose names are long enough to be cut "
        "off in the row → hover a title → the tooltip's first line is the whole "
        "title, the second line says Click: preview in lightbox · Right-click: "
        "open in details pane.",
        "Hover that row's play button → first line is the title, second line "
        "is Play.",
    ),
)
