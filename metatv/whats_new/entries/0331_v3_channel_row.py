from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=331,
    version="0.41.0",
    date="2026-08-23",
    title="The channel row, redrawn",
    items=(
        "Every row now leads with a media-kind mark — film, series or live — "
        "and a piece of artwork shaped to match: a poster for movies and "
        "series, a square tile for live channels, whose logos are square.",
        "Underneath the title is a single readable line of facts instead of a "
        "scatter of coloured chips: '2000 · Thriller / Drama · Anime'. The "
        "kind is not spelled out there — the mark at the left already says "
        "it, and a list of films read 'Movie' down every single row.",
        "The quality badge sits right after the title, and the language badge "
        "has its own fixed column at the right. That pairing is deliberate: "
        "quality is on about one row in fifteen, so if the two shared a "
        "right-aligned group the language badge would jump left and right "
        "down the list depending on which rows happened to have a 4K tag.",
        "Selecting a row no longer moves anything in it. The '…' actions "
        "button has a permanently reserved slot at the right edge and is "
        "simply painted in when you hover or select — click it for the same "
        "menu right-click gives you.",
        "A selected row is now a soft accent tint with a bright bar down its "
        "left edge, rather than a solid block of colour. Its text keeps the "
        "normal colours, so the row you picked is the one you can still read.",
        "Star ratings have left the row. They were never comparable between "
        "sources, and near the top of the range almost everything scored the "
        "same 10.0.",
        "Compact, Comfy and Comfy+ all still work, and now differ only in how "
        "much stacks up: Compact is the title line on its own, Comfy adds the "
        "facts line, Comfy+ adds the plot.",
    ),
    test_steps=(
        "Open Search and look at the channel list — every row should show a "
        "kind mark at the far left, then artwork, then the title with a "
        "facts line beneath it, and NO 'Movie'/'Series'/'Live' word in that "
        "facts line.",
        "Scroll a list where only some rows have a 4K/HD badge → the language "
        "badge stays in exactly the same column on every row, and the quality "
        "badge sits immediately after each title.",
        "Find a live channel and a movie in the same list → the live "
        "channel's tile is SQUARE and its mark is accent-coloured; the "
        "movie's artwork is a tall poster and its mark is grey.",
        "Click a row to select it, then click a different one → nothing in "
        "either row shifts sideways; the selected row gets a tinted "
        "background and a bright bar on its left edge.",
        "Hover a row without selecting it → a '…' button appears at the "
        "right; move the pointer away → it disappears, and the row's contents "
        "have not moved.",
        "Click that '…' button → the channel context menu opens, matching "
        "what right-clicking the row gives.",
        "Find a row with a quality badge (4K/HD) and one without → the badge "
        "sits in the same column on every row that has one, and the row "
        "without it gives that space to its title.",
        "Click a genre or collection on the facts line → the channel list "
        "filters to it, as the chips used to.",
        "Settings → Interface → Channel List: switch between Compact, Comfy "
        "and Comfy+ → Compact shows the title line only, Comfy adds the facts "
        "line, Comfy+ adds a plot line on titles that have one.",
        "Switch theme (Style menu) through Midnight, Graphite and Daylight → "
        "the rows stay readable in all three, selected rows included.",
    ),
)
