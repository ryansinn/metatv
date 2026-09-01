from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=481,
    version="0.64.0",
    date="2026-08-31",
    title="The channel list stops loading data it never shows",
    items=(
        "Every list, search and filter was fetching the provider's original "
        "record for each channel — about a third of the whole database — and "
        "then not using any of it. The list shows names, titles and posters; "
        "none of that comes from the part being loaded.",
        "Measured on this library: a page of 2,000 channels went from 923 "
        "milliseconds to 52. That is the query behind every list render, every "
        "search, and every filter change.",
        "Nothing is missing as a result. The details pane still reads the "
        "provider's record when you open a title — it is only the list that "
        "stops carrying it.",
    ),
    test_steps=(
        ("Scroll the channel list and change filters — it should feel faster, "
         "and every row should still show its name, quality and poster.",
         "view:list"),
        "Search for something and confirm results still look right.",
        "Open a title's details and confirm the plot, cast and rating are all "
        "still there.",
        "Switch to the Comfy+ density and confirm posters and plot lines still "
        "render in the list.",
    ),
)
