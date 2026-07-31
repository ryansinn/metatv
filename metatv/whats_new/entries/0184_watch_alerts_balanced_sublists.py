from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=184,
    version="0.14.2",
    date="2026-07-31",
    title="Watch Alerts: the EPG list no longer balloons and starves the others",
    items=(
        "In the sidebar Watch Alerts section, the live/upcoming EPG list is now "
        "sized to its own rows instead of stretching to fill every spare pixel. "
        "It previously absorbed all the section's leftover space, pushing "
        "'Movies & Series' and 'Stream Monitoring' into a thin sliver.",
        "Surplus vertical space now collects at the bottom of the section, so the "
        "three sub-lists sit at their natural sizes. A long EPG list scrolls within "
        "a sensible cap rather than growing the section without bound.",
    ),
    test_steps=(
        "Open the sidebar Watch Alerts section with both an EPG alert (a live or "
        "upcoming watchlist programme) and a Movies & Series alert present → the "
        "EPG list is sized to its rows and no longer balloons into empty space, "
        "and Movies & Series is visible below it (not starved).",
        "Drag the section's splitter handle to give it more height → the extra "
        "space collects as empty room at the bottom; the EPG list stays sized to "
        "its content instead of swallowing the new space.",
        "Add many watchlist matches so the EPG list exceeds its cap → the list "
        "scrolls internally rather than growing the section unboundedly tall.",
    ),
)
