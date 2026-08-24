from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=341,
    version="0.41.0",
    date="2026-08-24",
    title="Filters are a line of chips, not a column",
    items=(
        "The Includes column is gone by default. What is actually filtering now "
        "reads as a line of removable chips above the results — "
        "Movies ×  4K ×  English × — and the ~250px the column occupied goes "
        "back to the list.",
        "One value says itself (4K); several bring the facet name back "
        "(Subtitles: German, English +2) so the three language axes stay apart.",
        "A chip's × lifts that one constraint. Dropping the last media kind "
        "restores all three rather than emptying the screen.",
        "'+ Add filter' opens the full panel when you want it, and shuts it "
        "again. In chip mode it starts shut every launch.",
        "Chips that do not fit collapse into a counted +N marker rather than "
        "wrapping or being clipped, so the line never changes height.",
        "Layout ▸ Filters as chips turns it off: untick it and the Includes "
        "column is always present, as before.",
    ),
    test_steps=(
        "Launch → the Includes column is gone and a chip line sits directly "
        "above the results; with no filters it reads 'Showing everything'.",
        "Open Layout ▸ Filters as chips → untick → the Includes column returns "
        "and the chip line disappears. Re-tick → back to chips.",
        "Click '+ Add filter' → the Includes column opens at its remembered "
        "width. Tick Media ▸ Movies only → a 'Movies' chip appears in the line.",
        "Click '+ Add filter' again → the column shuts, the chip stays, and the "
        "results are still only movies.",
        "Add a second filter (e.g. Quality ▸ 4K) → two chips. Click the × on "
        "'Movies' → that chip goes, the results widen back to all kinds, and "
        "the 4K chip is untouched.",
        "With at least one chip active, click 'Clear all' → the line empties to "
        "'Showing everything' and every result comes back.",
        "Narrow the window until the chips no longer fit → the extras collapse "
        "into a '+N' marker; no chip is drawn with its label cut off, and the "
        "line stays one row tall. Click '+N' → the full panel opens.",
        "With chips active, switch to EPG and back to Search → the chip line "
        "returns and the Includes column stays shut.",
        "Open the column with '+ Add filter', switch to EPG and back → the "
        "column you opened is still open.",
        "Quit and relaunch → the column is shut again and the chip line shows "
        "whatever filters were still active.",
    ),
)
