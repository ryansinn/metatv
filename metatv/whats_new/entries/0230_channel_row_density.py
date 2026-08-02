from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=230,
    version="0.20.0",
    date="2026-08-02",
    title="Channel list row density: Compact or Comfy",
    items=(
        "The channel/search list row now has two densities, picked in Settings "
        "→ Interface → Channel List. 'Comfy' (default, unchanged look) shows the "
        "title on its own line plus a badge row of language/quality/category "
        "underneath. 'Compact' fits everything — media icon, title, quality, "
        "year, language, and your rating — on a single line so more rows fit "
        "on screen at once.",
        "The change applies immediately when you click OK or Apply — no "
        "restart needed.",
    ),
    test_steps=(
        "Open Settings → Interface → Channel List, switch 'Row density' to "
        "'Compact (one line)', click OK → the channel list rows collapse to "
        "one line each with quality/year/language/rating shown inline on the right.",
        "Reopen Settings → switch back to 'Comfy (two lines)', click Apply → "
        "rows expand back to two lines (title + badge row) without closing "
        "the dialog.",
        "Turn on 'Group by type' → confirm the Movies/Series/Live section "
        "headers still render as a single bold line in both densities (not "
        "affected by the row-height change).",
        "Restart the app → the density you left it on is still selected in "
        "Settings and the list still renders that way.",
    ),
)
