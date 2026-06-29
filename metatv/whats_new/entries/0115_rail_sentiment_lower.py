from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=115,
    version="0.9.0",
    date="2026-06-28",
    title="Details rail: sentiment trio drops lower",
    items=(
        "The Like / Not Interested / Dislike trio in the left action rail now sits LOW "
        "— down near the Play / Resume buttons — instead of bunching right under Hide.",
        "A much larger gap separates Hide from the sentiment trio, filling the dead "
        "space that used to sit empty below it; the top group (Favorite, Alert/Monitor "
        "or Watchlist, Hide) and the tight trio cluster are otherwise unchanged.",
    ),
    test_steps=(
        "Open a MOVIE's details pane and look at the left action rail: the Like / Not "
        "Interested / Dislike sentiment trio sits LOW, near the Play/Resume buttons, "
        "clearly separated from Hide above it (a big gap between Hide and the trio).",
        "Confirm the top group (Favorite, Alert/Monitor or Watchlist, Hide) is still a "
        "tight cluster and the three sentiment icons are still tight together.",
    ),
)
