from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=176,
    version="0.14.1",
    date="2026-07-31",
    title="Explore: a trail-map that lets you wander sideways through similar titles",
    items=(
        "The preview lightbox has a new 🧭 Explore button. It opens a cascading-columns "
        "'trail-map': the first column is the trail of titles you dived through, and "
        "expanding any stop fans out its similar titles in the next column. Keep "
        "clicking to drill sideways as far as you like — a title already on your path "
        "never shows up again, so you never loop.",
        "Each row shows a poster thumbnail, title, year and the same badges as the rest "
        "of the app (language/rating + liked / in-Watch-Later / favorited / watched "
        "icons). Hover a row for quick 👍 / 👎 / 🙅 / 📋 actions — like/dislike/"
        "not-interested are mutually exclusive; Watch Later is independent.",
        "A detail strip along the bottom tracks whatever row you select: poster (click "
        "to enlarge), a favourite title-star, ★rating · runtime · language, and the "
        "overview / cast / director when we have them. One big Play button reads "
        "'Play', 'Resume 12:34' or 'Play again' depending on where you left off, and a "
        "green watched badge on the poster marks it watched or unwatched.",
        "From the strip you can also jump straight to the full details pane (↗ Open in "
        "details) or start a recipe from the title (✦ Make recipe).",
    ),
    test_steps=(
        "Right-click a Similar Titles row to open the preview lightbox, then click the "
        "🧭 Explore button in its header: a columns view opens with a 'Your Trail' "
        "column on the left listing the titles you dived through (the last one tagged "
        "'here').",
        "Click a stop in the trail column: a new 'SIMILAR TO <title>' column appears to "
        "the right with its similar titles; click one of those and a further column "
        "cascades — confirm the title you came from is NOT repeated in the new column "
        "(no loops).",
        "Select any row and check the bottom detail strip updates to that title: poster, "
        "title/year, a ★ favourite star, and a big Play button whose label is 'Play', "
        "'Resume M:SS' (for a partly-watched title) or 'Play again' (for a completed "
        "one). Click the green circle badge on the poster to mark it watched, and click "
        "it again to unmark.",
        "Hover a row and click 👍, then 👎: the like clears and dislike turns on (they "
        "are mutually exclusive); click 📋 and confirm it toggles Watch Later "
        "independently. Click the ★ star in the detail strip and confirm the title is "
        "added to / removed from Favorites.",
        "In the detail strip click '↗ Open in details': the Explore view closes and the "
        "main details pane jumps to that title.",
    ),
)
