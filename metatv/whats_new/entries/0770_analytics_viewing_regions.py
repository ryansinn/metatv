from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=770,
    version="0.208.0",
    date="2026-10-31",
    title="Sources Analytics shows what you watch from each source, and its regions",
    items=("A new \"What you watch here\" section on the Sources editor's Analytics tab: how many "
           "titles you've played from the source (split into films, series and live), how many "
           "plays, when you last played something, your three most-played titles, and time "
           "watched since play recording began.",
           "Catalogue & guide now shows the source's titles per region — the largest six as bars, "
           "with how many more regions there are and how many titles have no region.",),
    test_steps=("Open Sources → a source you have watched things from → Analytics — \"What you "
                "watch here\" sits second, under Only on, and shows titles played, plays and "
                "\"Most played\" with three titles; the subtitle says when you last played.",
                "Open Analytics on a source you have never played from — that section says "
                "\"Nothing played from this source yet.\"",
                "Scroll to Catalogue & guide — up to six region bars (e.g. \"France (FR)\") with a "
                "percentage and title count each, then a line with how many more regions and "
                "titles with no region.",
                "Play something from the source for a minute, stop it, reopen Analytics — Time "
                "watched shows hours since today's date.",),
)
