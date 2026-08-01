from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=195,
    version="0.16.0",
    date="2026-08-01",
    title="Settings: steer how recommendations are scored",
    items=(
        "Settings has a new Recommendations tab exposing the dials the preference "
        "engine used to keep to itself: how much genre, director, cast and plot "
        "keywords each count toward a match.",
        "Tuning controls sit alongside them — how many of your liked titles a "
        "performer must appear in before counting, how hard repeated faces are spread "
        "out within one list, how fast an already-shown item fades, and how many slots "
        "things you have already liked may occupy.",
        "The movie/series mix lives here too, sharing one setting with the "
        "Recommendations dashboard slider — change it in either place and both agree.",
        "Everything ships on the defaults MetaTV already used, so the tab is for "
        "steering rather than setup, and 'Reset to defaults' puts it all back.",
    ),
    test_steps=(
        "Open Settings → Recommendations: every dial shows its default (Genre 1.00, "
        "Director 1.50, Cast 0.35, Keywords 0.40, cast support 2 titles, people "
        "diversity 0.50, impression decay 4% per view, already-liked 3 slots) and "
        "'Automatic' is ticked.",
        "Untick Automatic: the '% movies' spinner enables and shows the resulting "
        "movies : series ratio; tick it again and the spinner greys out.",
        "Set Cast to 0.00 and click Apply, then open the Recommendations dashboard: "
        "recommendation reasons no longer lean on shared cast members.",
        "Set the movie mix to 90% movies, click OK, then open the Recommendations "
        "dashboard: the Mix slider shows 90 and the list is movie-heavy — the two "
        "controls share one setting.",
        "Click 'Reset to defaults', click OK, reopen Settings → Recommendations: every "
        "dial is back at its default and Automatic is ticked again.",
    ),
)
