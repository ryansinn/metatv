from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=775,
    version="0.211.0",
    date="2026-10-31",
    title="Source Analytics: failures by time of day",
    items=("The Playback section of a source's Analytics tab shows when plays fail: one column "
           "per hour of your day, as tall as that hour's failure rate, with a line naming the "
           "worst stretch (\"struggles 8 PM–11 PM\"). Hover a column for its figures.",
           "It appears once 30 plays from the source are recorded; until then the section says "
           "how many it has so far.",),
    test_steps=("Open Sources → a source you have played from fewer than 30 times → Analytics — "
                "Playback ends with \"Failures by time of day: shown once 30 plays are recorded "
                "(N so far).\"",
                "On a source with 30 or more recorded plays — Playback shows a 24-column strip "
                "with hour labels underneath; hours with failed plays have orange columns.",
                "Hover a column — the tooltip gives that hour's failed and total plays.",),
)
