from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=515,
    version="0.67.0",
    date="2026-09-02",
    title="Watch rules get real controls",
    items=(
        "Every rule in the watchlist now has a Rule panel — click \"Rule\" on "
        "any card to open it. Nothing is hidden behind it that used to be "
        "elsewhere; these are new controls.",
        "Include several terms at once, separated by commas, and choose how "
        "they combine: Phrase (the words together, in order), All words "
        "(every term somewhere in the programme) or Any word.",
        "Exclude terms are the other half. \"Denver\" without \"news\" and "
        "\"pregame\" is finally a usable rule, and the line under the controls "
        "tells you how many programmes matched AND how many your exclusions "
        "removed — so you can tell \"my exclusions are working\" from \"my "
        "rule stopped matching\".",
        "The whole-word switch from the last update is here too, so you can "
        "turn it off for a single rule that needs it.",
        "You can also search programme descriptions, not just titles. It is "
        "off for every rule, old and new — it finds a lot more, and more of "
        "what it finds is loose.",
    ),
    test_steps=(
        ("Open EPG ▸ Watchlist, click \"Rule\" on a card and confirm the panel "
         "opens below it with Match, Include, Exclude and Options.",
         "view:epg"),
        ("Set Match to \"Any word\" and put two comma-separated terms in "
         "Include; confirm the list picks up programmes matching either.",
         "view:epg"),
        ("Add an exclude term that appears in one of the matches and confirm "
         "the summary line's \"suppressed by excludes\" count goes up and that "
         "programme leaves the list.", "view:epg"),
        ("Tick \"Also search descriptions\" and confirm more programmes match; "
         "untick it and confirm they go away.", "view:epg"),
        ("Restart the app and confirm every rule setting you changed is still "
         "there, and that rules you never opened still match as before."),
    ),
)
