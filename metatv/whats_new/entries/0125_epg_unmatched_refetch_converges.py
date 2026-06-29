from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=125,
    version="0.9.0",
    date="2026-06-29",
    title="EPG: sources with unmatchable guide data no longer re-fetch on every launch",
    items=(
        "A source whose EPG guide can never be matched to its channels (e.g. a "
        "provider serving placeholder or foreign EPG, like TREX) was triggering a "
        "background guide re-fetch on EVERY app start — wasting a network request each "
        "launch and never converging.",
        "Cause: the once-per-session 'rebuild unmatched links' re-fetch fired for any "
        "guide whose rows weren't matched to channels. For a permanently-unmatchable "
        "guide that condition is always true, and the per-session guard resets each "
        "launch, so it ran forever.",
        "Now the re-fetch only runs for the case it can actually fix — legacy guide rows "
        "that lack a stored channel name (one fetch populates the names, then it stops). "
        "The merely 'unmatched but named' case is already handled in-app by the cheap "
        "relink that runs each time you open EPG, with no network fetch.",
    ),
    test_steps=(
        "With a source that has no usable EPG (its guide doesn't match its channels), "
        "open the app and then open the EPG view.",
        "Confirm that source does NOT kick off a guide refresh on this and every "
        "subsequent launch (watch the logs / the EPG refresh indicator) — it should be "
        "quiet unless its guide is genuinely stale on the normal interval.",
        "Confirm a source WITH real, matchable EPG still shows its guide and refreshes "
        "normally on its interval.",
    ),
)
