from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=337,
    version="0.41.0",
    date="2026-08-23",
    title="Chips and buttons space consistently",
    items=(
        "Eighteen different padding values shipped across the interface — "
        "every whole number from 0 to 14, plus 16, 18 and 20 — so two chips "
        "doing the same job could sit at noticeably different widths.",
        "Side padding now comes from a four-step grid, so controls of the "
        "same kind are the same shape wherever they appear.",
        "Heights are untouched, deliberately. Several round badges are exactly "
        "as tall as twice their corner radius, and Qt turns a corner square "
        "the moment a radius passes half the height — so nothing that could "
        "change a control's height was altered.",
    ),
    test_steps=(
        "Open Search and look along a row of filter chips and the bottom nav "
        "bar → padding either side of each label looks even and consistent.",
        "Compare a chip in Discover with one in Recipe and one in the details "
        "pane → the same kind of control has the same breathing room.",
        "Check the round badges — the Watched tick on a poster, the trail-map "
        "status badges, the EN language chip → still fully round, not squared.",
        "Confirm no control got taller or shorter: the bottom nav bar, the "
        "filter bar and the details buttons sit where they did.",
        "Switch theme through Midnight, Graphite and Daylight → spacing is "
        "identical in all three.",
    ),
)
