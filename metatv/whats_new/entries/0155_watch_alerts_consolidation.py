from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=155,
    version="0.10.0",
    date="2026-07-26",
    title="Watch Alerts: one home for keyword rules AND monitored series",
    items=(
        "The sidebar \"Alerts\" section is now \"Watch Alerts\" and gathers "
        "everything you watch for in one always-visible place. A \"Manage\" button "
        "sits in the header so it is reachable even when the section is otherwise "
        "empty — no more hunting for a management screen buried in a hidden section.",
        "The body now has clearly-labelled sub-sections that each appear only when "
        "they have something to show: EPG (live/upcoming programmes from your "
        "watchlist), Movies & Series (your keyword watch-for rules plus the series "
        "you're monitoring for new episodes), and Stream Monitoring.",
        "Monitored series live under a collapsible \"──── Series ────\" divider "
        "inside Movies & Series. Series with new episodes are pinned to the top and "
        "highlighted with a green \"+N eps\" badge; the rest sit below. Everything is "
        "shown and sorted by the cleaned title (e.g. \"Rick and Morty\", not "
        "\"EN - Rick And Morty (2013)\"). Right-click a series to open it, mark it "
        "seen, or stop alerts.",
        "The \"Manage\" dialog now has two sections — your keyword rules and a new "
        "\"Series — new-episode alerts\" list where you can Stop monitoring any "
        "series. The old separate \"New Episodes\" section and its \"Episode Alerts\" "
        "dialog have been retired; their job moved here.",
    ),
    test_steps=(
        "With no rules and no monitored series, open the sidebar: the Watch Alerts "
        "section shows a single tidy line — title + Manage + \"+\". Click Manage: "
        "the dialog opens (both sections show their empty hints).",
        "Click \"+\" and add a keyword rule (e.g. \"Dune\"): a Movies & Series "
        "sub-section appears with the rule row.",
        "Right-click a series in the channel list → \"Alert me to new episodes\". "
        "It appears under the \"──── Series ────\" divider in Movies & Series, shown "
        "by its cleaned title and sorted A–Z among any other 0-new series.",
        "For a series that has new episodes, confirm its row is pinned to the top of "
        "the series block and shows a green \"+N eps\" badge.",
        "Open Manage: the dialog lists the keyword rule under \"Movies & Series — "
        "keyword rules\" and the series under \"Series — new-episode alerts\"; click "
        "a series' Stop and it disappears from both the dialog and the sidebar.",
        "Confirm there is no separate \"New Episodes\" sidebar section and no "
        "\"Episode Alerts\" dialog anymore.",
    ),
)
