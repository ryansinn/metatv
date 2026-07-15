from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=133,
    version="0.9.0",
    date="2026-07-14",
    title="EPG no longer re-fetches a lagging guide on every launch",
    items=(
        "Some providers serve an EPG guide whose newest programme is already in the "
        "past (the feed lags real time). MetaTV treated that as \"guide ran out — "
        "refresh now,\" so it re-fetched that source's guide on every single launch, "
        "even right after a successful refresh, and never converged.",
        "Now, when a guide comes back already-expired at fetch time, MetaTV recognizes "
        "the feed itself is behind — re-fetching would just pull the same stale data — "
        "and stops hammering it. It re-checks on a sensible interval instead (at least "
        "every 6 hours) so a feed that catches up is still picked up.",
        "Guides that were valid when fetched and have since genuinely run out still "
        "refresh immediately, so \"On Now\" is never left empty for a healthy source.",
    ),
    test_steps=(
        "Launch with a source whose EPG feed is lagging (its latest programme ends "
        "before now, e.g. ProSat/BiggyJuke). Let its EPG refresh finish, then quit and "
        "relaunch: the EPG does NOT re-fetch for that source again immediately (check "
        "the log — no back-to-back fetch for the same provider each launch).",
        "For a normal source whose guide has legitimately run out (last fetched a day "
        "or two ago, data now expired), relaunch: it DOES refresh so On Now repopulates.",
    ),
)
