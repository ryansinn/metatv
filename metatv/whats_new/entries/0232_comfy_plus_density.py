from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=232,
    version="0.20.0",
    date="2026-08-02",
    title="Channel list: a third density, 'Comfy+', with a description line",
    items=(
        "Settings → Interface → Channel List → Row density has a new option: "
        "'Comfy+ (with description)'. It's Comfy's two lines plus a middle "
        "line showing the title's plot/description (elided to fit), when one "
        "is available. Titles with no description render exactly like Comfy — "
        "no empty gap.",
        "Applies immediately when you click OK or Apply — no restart needed.",
    ),
    test_steps=(
        "Open Settings → Interface → Channel List, switch 'Row density' to "
        "'Comfy+ (with description)', click OK → rows for titles with a "
        "description grow a third, muted line under the title showing that "
        "description, elided if it's long.",
        "Scroll to a title with NO description (e.g. most Live channels) → "
        "confirm that row is the SAME two-line height as Comfy, not a taller "
        "row with a blank middle line.",
        "Switch back to 'Comfy (two lines)', click Apply → the description "
        "line disappears and every row returns to two lines.",
        "Restart the app → the density you left it on ('Comfy+') is still "
        "selected in Settings and the list still renders that way.",
    ),
)
