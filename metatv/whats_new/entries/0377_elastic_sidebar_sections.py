from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=377,
    version="0.41.0",
    date="2026-08-26",
    title="Sidebar sections shrink all the way down, and open back up on their own",
    items=(
        "Any sidebar section can now be dragged down to just its header. "
        "Watch Alerts used to refuse to go below about 367px, which meant it "
        "took up a large fixed share of the sidebar whether you wanted it to "
        "or not.",
        "On the way down a section folds its groups to their headings instead "
        "of clipping them - so you keep seeing EPG, Movies, Series and Stream "
        "Monitoring with their counts even when the section is short. The most "
        "important group stays open and scrolls.",
        "When you give the space back - by shrinking another section, or "
        "dragging the handle - the folded groups open again by themselves.",
        "A group YOU collapsed stays collapsed. Freeing up space never undoes "
        "a collapse you chose.",
        "How much room each section asks for by default is unchanged; it is "
        "now a preference rather than a wall, so growing one section still "
        "never squeezes a neighbour below what it needs.",
    ),
    test_steps=(
        "Drag the handle under Watch Alerts upward - it now shrinks past the "
        "point it used to stop at, all the way down to just its header row.",
        "As it shrinks, watch the groups: Stream Monitoring folds first, then "
        "EPG, then Movies. Each keeps its heading and count.",
        "Keep shrinking - Series stays open and scrolls rather than folding, "
        "so you always see rows of something.",
        "Drag the handle back down - the folded groups re-open by themselves, "
        "in reverse order, as room becomes available.",
        "Now click the SERIES heading to collapse it yourself, shrink the "
        "section, then grow it back. Series must still be collapsed - your "
        "choice was not undone.",
        "Grow Watch Alerts to fill the sidebar - the other sections shrink but "
        "none is squashed below the few rows it needs.",
        "Drag Watch Alerts down to its header - the title, the +N badge and "
        "the header buttons are all still fully drawn, not clipped.",
        "Restart the app - the section sizes you left are restored.",
    ),
)
