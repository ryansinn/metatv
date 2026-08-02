from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=239,
    version="0.21.0",
    date="2026-08-02",
    title="Real theme system: Midnight, Graphite, and Daylight palettes",
    items=(
        "Settings → Interface → Appearance has a new Theme picker with three "
        "palettes: Midnight (the familiar default dark theme, unchanged), "
        "Graphite (a flatter neutral-dark variant), and Daylight (a genuine "
        "light theme).",
        "Switching themes applies immediately on OK or Apply — no restart "
        "needed for the main window, sidebar sections, details pane, and "
        "channel list. A few less-visited dialogs/views pick up the new "
        "palette the next time they're opened rather than repainting live.",
    ),
    test_steps=(
        "Open Settings → Interface → Appearance → Theme, pick 'Daylight', "
        "click Apply → the app immediately switches to a light background "
        "with dark text; the sidebar section headers and details pane also "
        "re-theme without closing the dialog.",
        "With Settings still open, switch back to 'Midnight', click OK → the "
        "app returns to the original dark look immediately.",
        "Pick 'Graphite', click OK, then quit and relaunch the app → it "
        "reopens already in Graphite (the choice persisted).",
    ),
)
