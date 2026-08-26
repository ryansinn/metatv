from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=357,
    version="0.41.0",
    date="2026-08-26",
    title="Watch Alerts groups all look and behave the same",
    items=(
        "Watch Alerts drew its group headings three different ways in one "
        "section, and two headings that looked identical did not behave the "
        "same: clicking \"Series\" collapsed it, clicking \"Watching for\" did "
        "nothing at all.",
        "All four groups — Watch now, Upcoming, Watching for, Series — now use "
        "one heading, and every one of them collapses when you click its "
        "title. No carets: the heading itself is the control, as the section "
        "headers already were.",
        "Each heading carries its count, sized and weighted to stand out from "
        "the label. With a group collapsed that number is the only thing "
        "describing what is hidden, so it is the part worth reading.",
        "The em-dash rules around the old dividers are gone.",
    ),
    test_steps=(
        "Open Watch Alerts with both keyword rules and monitored series → the "
        "\"Watching for\" and \"Series\" headings look identical to each other "
        "and to the EPG's \"Watch now\" / \"Upcoming\".",
        "Click the \"Watching for\" heading → its rules collapse. This did "
        "nothing before.",
        "Click \"Series\" → its rows collapse, same as before, and the heading "
        "still shows its count while collapsed.",
        "Check every heading shows a count that is clearly bolder and larger "
        "than the label beside it, and that no heading has \"────\" around it.",
        "Right-click a heading → no context menu appears (it is a label, not a "
        "row), and clicking one never selects it.",
    ),
)
