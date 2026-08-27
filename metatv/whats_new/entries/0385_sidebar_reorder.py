from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=385,
    version="0.41.0",
    date="2026-08-26",
    title="Sidebar headers are just their names",
    items=(
        "The icons beside the sidebar section names are gone. They repeated "
        "what the name already said - the row beside 'Watch Queue' said "
        "'Watch Queue' - and the one job left for them, being a drag handle "
        "for reordering, is not something the sidebar does yet.",
        "Watch Alerts' status dot went with them. The filled +N chip in the "
        "same header says the same thing, with a number in it.",
        "On History rows, the play-next-episode button now sits inside the "
        "time rather than outside it, so the times line up down the list.",
    ),
    test_steps=(
        "Check every sidebar section header - the name only, no icon beside "
        "it, and all five names starting at the same left edge.",
        "Trigger a new watch alert - Watch Alerts must still show its +N chip "
        "in the header, and must NOT show a coloured dot beside its name.",
        "Collapse Watch Alerts with something new - the +N chip stays visible "
        "on the collapsed header.",
        "Find a series episode in History with a play-next button - the time "
        "must be the rightmost thing on the row, and the times should form a "
        "straight column down the list including on rows without a button.",
        "Switch themes - the section titles recolour with the palette.",
    ),
)
