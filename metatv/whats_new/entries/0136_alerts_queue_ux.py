from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=136,
    version="0.9.0",
    date="2026-07-21",
    title="Cleaner Alerts header and Watch Queue footer",
    items=(
        "The Alerts header is now a single status dot: gray when quiet, green with "
        "an \"Alerts (N)\" count when there are new matches — no more double siren.",
        "A \"Clear all\" link appears in the Alerts header while there are new "
        "matches, so acknowledging everything lives with the alerts themselves.",
        "\"Watching for\" rows are tidier: the type icon has breathing room, the "
        "name stays fully legible, and the match count sits right-aligned as "
        "\"N of M\" (green only when some are new).",
        "Right-click a \"Watching for\" row with new matches to \"Clear this alert\" "
        "— acknowledging just that one rule.",
        "The Watch Queue footer shows only \"Clear Watched\"; the destructive "
        "\"Clear All\" moved into a compact ⋯ overflow menu.",
    ),
    test_steps=(
        "Open the Alerts section with no new matches: the header dot is gray, the "
        "title reads \"Alerts\" (no count), and there is no \"Clear all\" link.",
        "Trigger a watch-for match: the header dot turns green, the title reads "
        "\"Alerts (N)\" in green, and a \"Clear all\" link appears.",
        "Check a \"Watching for\" row with new matches: the name is legible (not "
        "green-tinted), and the count reads e.g. \"5 of 20\" right-aligned in green.",
        "Right-click that green row → \"Clear this alert\": only that row's count "
        "loses its green; other rules with new matches stay green.",
        "Click the header \"Clear all\": the remaining rows' green clears and the "
        "header dot returns to gray.",
        "Open the Watch Queue footer: only \"Clear Watched\" is visible next to a "
        "⋯ button; clicking ⋯ opens a menu whose single \"Clear All\" empties the queue.",
    ),
)
