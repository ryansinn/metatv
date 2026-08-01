from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=184,
    version="0.15.0",
    date="2026-07-31",
    title="Watch Alerts: the sub-lists now share the space evenly",
    items=(
        "In the sidebar Watch Alerts section, the live/upcoming EPG list, "
        "'Movies & Series' and 'Stream Monitoring' now share the section's height "
        "evenly. The EPG list previously absorbed all the leftover space and pushed "
        "the other two into a thin sliver.",
        "When the section is taller than its contents, the spare room is split across "
        "the visible lists so the section looks filled and tidy — no single list "
        "balloons and there is no longer a big blank gap at the bottom.",
        "A long list scrolls within its share of the space instead of growing the "
        "section without bound.",
    ),
    test_steps=(
        "Open the sidebar Watch Alerts section with both an EPG alert (a live or "
        "upcoming watchlist programme) and a Movies & Series alert present → the two "
        "lists share the section's height; the EPG list no longer balloons and "
        "Movies & Series is not starved to a sliver.",
        "Drag the section's splitter handle to give it more height → the extra space "
        "is shared by the visible lists so the section stays filled/tidy — there is "
        "no big blank gap at the bottom.",
        "Add many watchlist matches so a list has more rows than its share → that "
        "list scrolls internally rather than growing the section unboundedly tall.",
    ),
)
