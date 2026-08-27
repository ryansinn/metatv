from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=397,
    version="0.51.0",
    date="2026-08-27",
    title="Plots, cast and ratings appear without waiting for a lookup",
    items=(
        "Title details were fetched one at a time, only when you opened "
        "something - so after months, 2,100 of 417,000 titles had any. "
        "Everything that reads them in bulk, like the plot line in the channel "
        "list, was blank for almost everything.",
        "Your source already sent most of it. A series record carries the "
        "plot, cast, genre, rating, release date and poster; the app could "
        "always read that, it just never did so in bulk.",
        "A one-time pass now reads it for every title straight off your disk - "
        "no network. On a 417,000-title library that is about five minutes and "
        "produces 73,861 plots where there were 1,823.",
        "Titles are still queued for a full online lookup afterwards, so "
        "director, runtime and cast photos still arrive later. Anything "
        "already fetched is left exactly as it was.",
    ),
    test_steps=(
        "On first launch you will see 'Reading title details already on disk'. "
        "Let it finish - roughly five minutes on a very large library.",
        "Open a series you have never opened before - the details pane should "
        "show a plot, cast and genre immediately, with no spinner.",
        "Switch the channel list to Comfy density and check the plot line now "
        "shows text for most rows rather than being empty.",
        "Open a title you HAD opened before and confirm its details are "
        "unchanged - a previously fetched plot must not be replaced.",
        "Leave the app running and confirm the enrichment queue still works "
        "through titles afterwards; this pass must not stop it.",
        "Restart - 'Reading title details already on disk' must NOT run again.",
    ),
)
