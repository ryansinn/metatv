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
        "Selected rows are readable again: lists with coloured text (new-match "
        "green, the count, green channel rows) now use a soft translucent highlight "
        "with a left accent bar instead of a solid blue fill that hid the text.",
        "The Alerts header count is the number of alerts firing (e.g. \"Alerts "
        "(2)\"), not the total matched-item count; the \"Watching for\" toggle also "
        "shows \" · N new\", and the header tooltip spells out both numbers.",
        "Clicking a \"Watching for\" rule now shows that alert's actual matched "
        "titles (its stored matches) instead of a fresh keyword search — so a rule "
        "that matched 17 titles shows 17, never a mismatched or empty result, with "
        "the normal \"N filtered — click to show\" bar when filters hide some.",
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
        "Select a green new-match row in the channel list (and a \"Watching for\" "
        "row): the selection is an obvious soft tint with a left accent bar and the "
        "coloured text stays readable — not a saturated blue block that hides it.",
        "With 2 of 3 rules having new matches, the Alerts header reads \"Alerts "
        "(2)\" (not the item total), the toggle reads \"Watching for (3) · 2 new\", "
        "and hovering the header shows \"2 alerts have new matches (N new items)\".",
        "Click a \"Watching for\" rule that matched several titles: the channel "
        "list shows exactly those matched titles (\"Showing K of M\"); if active "
        "filters exclude some, the gold \"N filtered — click to show\" bar appears; "
        "typing in search or changing a filter clears the alert view.",
        "In alert-matches mode with some matches soft-hidden (media-type / "
        "exclusions / hide-watched), the gold bar shows the hidden count; clicking "
        "it reveals those matches and the bar clears.",
        "Content from disabled/expired sources never appears in alert matches or the "
        "count — not even via 'show all'; the per-rule \"N of M\", the header "
        "\"Alerts (N)\", and the Watch Queue banner all reflect only currently-"
        "available matches (re-enable the source to see its content).",
    ),
)
