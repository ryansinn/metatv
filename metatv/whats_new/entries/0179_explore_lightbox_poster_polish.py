from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=179,
    version="0.15.0",
    date="2026-07-31",
    title="Explore & lightbox polish — fewer clicks, cleaner columns, poster peeks",
    items=(
        "Explore now opens ready to browse: when the trail you launched it from "
        "has a single stop (the common case from a title's Similar Titles), that "
        "stop is expanded for you straight away — its similar titles are already "
        "fanned out in the next column, no extra click. A longer trail (e.g. Full "
        "Watch History) still waits for you to pick which stop to expand.",
        "In the Similar Titles preview, clicking the big poster now enlarges it "
        "(the same full-screen peek as the details pane) instead of starting "
        "playback — use the dedicated Play button below the poster to play. The "
        "old hover play-orb on the poster is gone.",
        "In Explore (and Full Watch History), clicking a row's poster thumbnail "
        "enlarges that poster too, matching the details pane. Clicking the rest of "
        "the row still selects it and drills into its similar titles as before.",
        "Explore columns now highlight your actual trail: each column lights up the "
        "step you drilled through toward the next column (a breadcrumb), so the path "
        "you walked is clear and a title no longer lights up in every column it "
        "happens to be a suggestion in.",
        "Explore rows read cleaner: the title and year sit on one baseline, the year "
        "is no longer shown twice, long titles now wrap to two lines and truncate "
        "with an ellipsis instead of running off the edge (hover for the full title), "
        "and the language/region badge is now the same bordered chip everywhere it "
        "appears (the trail rows, the lightbox strip and the Explore detail panel).",
    ),
    test_steps=(
        "Open a movie/series details pane, right-click a Similar Titles row (or use "
        "its preview) to open the lightbox, then click 'Explore': the trail-map "
        "opens with the origin already expanded — a 'SIMILAR TO <title>' column is "
        "visible without a second click, and the bottom detail strip shows the title.",
        "In the Similar Titles lightbox, click the large poster: the enlarged-poster "
        "overlay opens (no playback). Close it, then click the 'Play' button below "
        "the poster and confirm playback starts. Confirm the poster has no play-orb "
        "overlay on hover.",
        "In Explore (or open History → 'See all →'), click a row's small poster "
        "thumbnail: the enlarged poster opens and the row's selection/drill does NOT "
        "change. Then click the row body (not the poster) and confirm it selects and "
        "expands into a similar-titles column.",
        "Drill three levels deep in Explore (root → similar → similar): confirm each "
        "column highlights the one step you took through it (the breadcrumb), the "
        "deepest title is highlighted only in its own column, and no title is lit up "
        "in two columns at once.",
        "Look at any Explore row: the title and year share one baseline with the year "
        "shown once, a very long title wraps to two lines and ends in '…' (staying "
        "inside the column, full title on hover), and the language badge is a bordered "
        "chip that matches the lightbox strip cards and the Explore detail panel.",
    ),
)
