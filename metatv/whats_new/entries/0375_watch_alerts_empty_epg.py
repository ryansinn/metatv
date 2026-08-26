from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=375,
    version="0.41.0",
    date="2026-08-26",
    title="Watch Alerts says when a guide has run out instead of going blank",
    items=(
        "The EPG group in Watch Alerts no longer disappears when none of your "
        "alerts is on. It keeps its heading and tells you which nothing you "
        "are looking at - either \"Nothing airing from N alerts\", or \"Guide "
        "data has run out\" when the source has no programmes left to start.",
        "Before, a working watchlist with nothing currently airing looked "
        "exactly like a broken one: the group would flash into view while "
        "loading and vanish a moment later.",
        "Both messages explain themselves on hover.",
        "The group still stays hidden when you have no alerts set up, or no "
        "source with a guide - there is nothing to hold a place for.",
    ),
    test_steps=(
        "Open the sidebar with at least one EPG watch alert set up, at a time "
        "when none of them is airing. The EPG heading is still there, with a "
        "line reading \"Nothing airing from N alerts\" - not an empty gap.",
        "Hover that line - a tooltip explains your alerts are loaded and "
        "nothing matches in the next 24 hours.",
        "The EPG heading shows NO count chip beside it - the notice is a "
        "sentence, not a programme.",
        "Click the EPG heading to collapse it and click again to expand - "
        "still no count chip appears.",
        "Add or remove an alert in Manage. The group stays put through the "
        "reload instead of flashing away.",
        "Remove every EPG watch alert - now the EPG heading disappears "
        "entirely, since there is nothing to report on.",
        "With alerts that ARE currently airing, the group lists them as "
        "before with its count chip.",
    ),
)
