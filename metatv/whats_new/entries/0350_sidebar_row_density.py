from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=350,
    version="0.41.0",
    date="2026-08-25",
    title="The compact sidebar row is back, and it's the default",
    items=(
        "Sidebar rows are one line again: the media-type icon, the title, then "
        "small chips for quality, year and language. Twice the entries in the "
        "same space — a compact row is 20px against the two-line row's 37px.",
        "The media type is an ICON, not the word. The last release spelled out "
        "\"Movie · \" and \"Series · \" on every row, which is the repetition "
        "the icon column exists to prevent, paid for in the width the title "
        "needed.",
        "The two-line row is still there if you prefer it — "
        "Settings → Interface → Sidebar → Row density, and it applies without "
        "a restart.",
        "The chips are sized as indicators rather than badges: they now sit "
        "inside the title's line height instead of setting the row's, which is "
        "where the extra 7px per row came from. All three (quality, year, "
        "language) share one geometry, so they can no longer drift apart.",
        "A row with news carries a small green ring instead of a blue \"NEW\" "
        "pill. The pill was a second word competing with the title it sat in "
        "front of, and the count beside it already says what is new.",
        "History rows carry what tells them apart — the episode you were on (or "
        "the year), and a terse age at the right edge (2h, 1d, 3d). A language "
        "chip would have said the same thing on every row of your own history.",
    ),
    test_steps=(
        "Open the sidebar → each row is a single line: an icon for movie / "
        "series / live, the title, then chips. No row says the words \"Movie\" "
        "or \"Series\" anywhere.",
        "Watch Queue → an Alerts Matched row shows a small green ring before "
        "the title and its count (+12 eps) at the right edge — no \"NEW\" pill.",
        "Compare a year chip against a quality chip in the same row → they are "
        "the same height and the same padding.",
        "Compare a section against the last build → roughly twice as many "
        "entries fit in the same section height.",
        "Watch Queue → a series you are part-way through shows its episode "
        "(S05E03) where a film shows its year; 4K titles show a gold 4K chip.",
        "History → each row ends with a terse age (2h / 1d / 3d / 2w) and shows "
        "the episode code or year in a chip, with no language chip.",
        "Settings → Interface → Sidebar → Row density → Comfortable → OK → the "
        "sidebar rebuilds into two-line rows immediately, no restart, and the "
        "icon is still an icon on the first line.",
        "Switch back to Compact → OK → the rows return to one line.",
        "Hover a title that is too long to fit → the tooltip shows it in full.",
        "Switch themes (Midnight, Graphite, Daylight, Gruvbox, Gruvbox Light) → "
        "the chips stay legible and the year chip keeps its outline in each.",
    ),
)
