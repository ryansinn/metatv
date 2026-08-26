from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=367,
    version="0.41.0",
    date="2026-08-26",
    title="Watch Alerts rows look like the design",
    items=(
        "Rows carry chips now: the quality of a source sits beside its "
        "channel name, an episode code beside its series, and every trailing "
        "count is a chip rather than loose text.",
        "New items show a green dot in the same left column as the play "
        "button, so \"new\" reads the same wherever it appears.",
        "A programme row shows its time as a chip and its airings carry the "
        "progress bars underneath — two bars measuring the same thing was one "
        "too many. The \"·\" separator is gone.",
        "Rows breathe: they were about two-thirds the intended height.",
    ),
    test_steps=(
        "Open Watch Alerts with EPG entries → an expandable programme shows "
        "its title and a time chip, with its sources indented underneath, each "
        "showing a quality chip and a progress bar or its own time chip.",
        "Check no row contains a \"·\" separator or a bare bracketed token "
        "like [RAW] inside its title text.",
        "Find a series with new episodes → a green dot at the far left and a "
        "filled green +N chip at the right.",
        "Compare the section against the rest of the sidebar → one continuous "
        "surface, no boxes around the groups, no gap between them.",
    ),
)
