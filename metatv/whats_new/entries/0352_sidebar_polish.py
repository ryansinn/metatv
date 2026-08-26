from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=352,
    version="0.41.0",
    date="2026-08-25",
    title="Sidebar polish: smaller type icons, no nested scrollbars",
    items=(
        "The media-type icons are smaller. They were sized against the title's "
        "font size, but a 13px font only draws about 9px of capital — so an "
        "icon nominally the same size read about 44% bigger than the letters "
        "next to it. They now sit just above cap height.",
        "Sections fit one more row. The \"+N more\" tail reserved 24px — the "
        "simple-row height — while a rendered tail draws about 17, so every "
        "budgeted section was quietly giving away a row of content to space it "
        "never used. The tail's cost is measured now, not assumed.",
        "Watch Alerts has no scrollbars inside it. Movies & Series still had a "
        "scroll area of its own, about 35px tall — a window too small to read "
        "through, which is the exact thing the sidebar rework set out to "
        "remove. It and Stream Monitoring now show what fits and end with "
        "\"+N more\", like every other list in the rail.",
        "Watch Alerts' Manage and + sit tight under the section header instead "
        "of floating in a band of empty space.",
    ),
    test_steps=(
        "Look at any sidebar row → the movie / series / live icon reads as the "
        "same visual weight as the title beside it, not larger.",
        "Watch Alerts → expand Movies & Series with more entries than fit: it "
        "shows what fits and ends with \"+ N more →\", and there is NO "
        "scrollbar inside the section.",
        "Watch Alerts → Stream Monitoring has no horizontal scrollbar along "
        "its bottom.",
        "Watch Alerts → Manage and + are directly under the section header, "
        "with no gap of empty space above them.",
        "Drag a section's splitter slowly taller → rows appear one at a time "
        "and the \"+N more\" line stays fully visible at the bottom, never "
        "half-cut.",
        "Drag it shorter → at least one real row always remains above the "
        "\"+N more\" line.",
    ),
)
