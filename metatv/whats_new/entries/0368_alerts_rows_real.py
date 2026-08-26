from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=368,
    version="0.41.0",
    date="2026-08-26",
    title="Watch Alerts rows stop overlapping, and actually show their chips",
    items=(
        "Rows in Watch Alerts could draw on top of each other — a group "
        "heading landing over the row above it. Each list was measured for "
        "height before it had been laid out, so it locked in a size smaller "
        "than its contents.",
        "The chips, dots and spacing added in the last update were not "
        "reaching the screen: the rows were still being built the old way. "
        "Counts are chips now, new items show their dot, and the leading "
        "emoji is gone — the group heading above already says what these are.",
        "A count reads \"+5\" rather than \"5 of 20\" or \"· 17\". Inside a "
        "chip the dot read as part of the number, and how many are NEW is the "
        "fact worth a narrow chip. The total stays in the tooltip.",
    ),
    test_steps=(
        "Open Watch Alerts with monitored series and keyword rules → no row "
        "or heading is drawn over another, at any section height.",
        "Drag the section taller and shorter → rows re-fit cleanly each time "
        "with no overlap.",
        "Check a series with new episodes → a green dot at the far left and a "
        "filled green +N chip at the right; hover it for the full count.",
        "Check no row starts with a 🎬 / 📺 / 🆕 emoji.",
    ),
)
