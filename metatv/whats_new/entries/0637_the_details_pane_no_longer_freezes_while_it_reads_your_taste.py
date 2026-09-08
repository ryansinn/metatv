from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=637,
    version="0.103.0",
    date="2026-09-08",
    title="The details pane no longer freezes while it reads your taste",
    items=(
        "Opening a title used to compute your whole taste profile — every "
        "rating, every favourite and its metadata — before it would draw "
        "anything. On a large library that is seconds of database work with "
        "the window held frozen; the worst one measured was 28.7 seconds.",
        "The pane now paints immediately and reads your taste in the "
        "background. The ▲/▼ preference markers beside cast and director "
        "appear a moment later, on top of a pane you can already read, "
        "scroll and click.",
        "Nothing about the markers themselves changed — same actors, same "
        "directors, same thresholds. If you have no ratings or favourites "
        "yet there were never any markers to show, and there still aren't.",
        "Moving to another title while the read is still running discards "
        "the late answer instead of stamping the previous title's markers "
        "onto the new one.",
    ),
    test_steps=(
        "On a library with ratings and favourites, click a movie with a cast "
        "→ the details pane paints straight away; the ▲/▼ markers beside "
        "the cast names fill in a moment later.",
        "Click through five titles quickly → the window never freezes, and "
        "each pane ends up showing markers for the title actually on screen "
        "(no markers left over from a title you clicked past).",
        "With no ratings and no favourites, open a title → the cast and "
        "director render normally with no ▲/▼ markers, and nothing blanks "
        "out or disappears afterwards.",
        "Open a title on a source that is offline or mid-refresh → the pane "
        "still shows cast and director, just without markers.",
    ),
)
