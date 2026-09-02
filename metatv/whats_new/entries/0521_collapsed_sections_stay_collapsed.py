from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=521,
    version="0.70.0",
    date="2026-09-02",
    title="A collapsed sidebar section stays the size of its header",
    items=(
        "Collapsing a section and then resizing another one made the collapsed "
        "section swell to fill the space instead of leaving it for the "
        "sections that could use it. A collapsed Watch Alerts or Favorites "
        "could end up several hundred pixels tall with nothing in it.",
        "The space a collapsed section releases now goes to its neighbours, "
        "which is what collapsing it was for.",
        "Expanding it again returns it to normal, including any height you had "
        "dragged it to.",
    ),
    test_steps=(
        ("Click the header of a section with content — Favorites or Watch "
         "Alerts — to collapse it. It should shrink to just the header.",
         "view:list"),
        ("Now drag a splitter handle to make a different section smaller. The "
         "collapsed section must stay header-height; the freed space should go "
         "to the other sections.", "view:list"),
        ("Click the collapsed header again and confirm it opens to a normal "
         "height and can still be dragged taller.", "view:list"),
        ("Collapse two sections at once and confirm neither grows as you "
         "resize around them.", "view:list"),
    ),
)
