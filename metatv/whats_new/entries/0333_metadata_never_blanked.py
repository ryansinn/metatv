from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=333,
    version="0.41.0",
    date="2026-08-23",
    title="Opening a title no longer erases the artwork it already had",
    items=(
        "A title whose poster was visibly rendering in the results list could "
        "report 'No poster available' in the details pane right beside it.",
        "Cached metadata expires after 30 days (90 for older titles). When it "
        "did, opening that title's details refetched it — and if the fetch "
        "came back with less than the first one had (a provider switched off, "
        "an API key removed, a title no longer matched, a rate limit), the "
        "thin result was written straight over the stored record. Poster, "
        "plot, cast and crew were replaced with nothing.",
        "That was silent, permanent, and needed nothing more than browsing "
        "your own library: each title you opened whose cache had aged out "
        "could lose whatever the providers no longer returned.",
        "A refetch now only ever FILLS IN. New values still replace old ones, "
        "so metadata can still be corrected and improved — but a field the "
        "refetch did not return leaves what is stored alone.",
        "And if a refetch returns nothing at all, the details pane now shows "
        "the stored record instead of showing you an empty pane for a title "
        "the database still has everything about.",
    ),
    test_steps=(
        "Open a movie or series with a poster and a plot in the details pane "
        "and note them.",
        "Settings → Metadata & API Keys → turn OFF every metadata provider.",
        "Select a different title, then select the first one again → the "
        "poster and plot are still there, not 'No poster available'.",
        "Restart the app and open that title again → the poster and plot are "
        "still stored, not blank.",
        "Turn the providers back on and use the manual 'Refresh metadata' "
        "action on a title → genuinely new values still replace the old ones.",
        "Check the results list for the same title → its row poster and plot "
        "line agree with what the details pane shows.",
    ),
)
