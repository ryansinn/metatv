from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=358,
    version="0.41.0",
    date="2026-08-26",
    title="Watch Alerts shows how far through a programme is",
    items=(
        "A currently-airing programme in Watch Alerts now shows a progress bar "
        "instead of the words \"23m left\". Twenty minutes left on a half-hour "
        "show is not twenty minutes left on a three-hour one, and only a bar "
        "can say which you are looking at. The exact time is in the tooltip.",
        "The bar turns amber once a programme is nearly over, so \"about to "
        "end\" reads at a glance while you are scanning rather than reading.",
        "Rows that have nothing to measure keep their words — an upcoming "
        "programme has not started, and some providers give no start time.",
        "The EPG's own progress bars and this one are now literally the same "
        "bar. There were two, drawn differently, in colours the theme could "
        "not reach; they follow your palette now.",
    ),
    test_steps=(
        "Find a currently-airing Watch Alerts entry → it shows a small bar "
        "rather than \"Nm left\" text. Hover it → the tooltip gives the time.",
        "Compare a short programme with a long one that have similar time "
        "remaining → the bars are visibly different lengths.",
        "Watch a programme approaching its end → the bar fills and turns amber "
        "in its last stretch, updating on its own without a refresh.",
        "Look at an UPCOMING row → it still reads \"in Nm\" as words, with no "
        "bar.",
        "Open the EPG tab's On Now view → its progress bars look the same as "
        "the sidebar's, and both follow the current theme.",
    ),
)
