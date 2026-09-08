from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=642,
    version="0.105.0",
    date="2026-09-08",
    title="One slow connect no longer hides posters for hours",
    items=(
        "A single slow connection to an image host (e.g. TMDb) no longer blacklists that whole "
        "host for 3 hours — it now takes 3 consecutive connect failures before a host is skipped.",
        "A host that serves an image successfully is immediately treated as alive again, even if "
        "it had just been marked as failing.",
        "Stale host blacklists left over from before this fix are discarded on the next launch, "
        "instead of continuing to hide posters until their old timer runs out.",
        "The connect timeout was widened slightly (3.05s to 6.05s) to give a marginal connection "
        "more room before it counts as a failure at all.",
    ),
    test_steps=(
        "Open Discover with a flaky/slow network — posters still load for hosts that eventually "
        "respond, instead of the whole shelf going blank after one slow request.",
        "Restart the app after a network hiccup — posters that come from the same host as an "
        "earlier failed image still load normally rather than staying stuck as failed for hours.",
    ),
)
