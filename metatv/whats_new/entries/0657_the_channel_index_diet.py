from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=657,
    version="0.115.0",
    date="2026-09-08",
    title="Smaller database, faster filtered lists — a background index cleanup",
    items=(
        "The channel table was carrying 46 indexes, several of them full-size "
        "even though the column they cover is almost always empty (a played-"
        "date index sized for 786,000 rows was doing real work for 25 of "
        "them). Those are now built as partial indexes that only cover rows "
        "with a real value, four redundant/dead indexes are dropped "
        "outright, and stale query statistics — which had been quietly "
        "misleading the query planner on low-cardinality filters like hidden/"
        "visible — are refreshed whenever the catalog has genuinely grown or "
        "shrunk since the last check, not just once ever. None of this "
        "touches the channel table itself or changes what any query returns — "
        "it runs as the existing background index-maintenance task, not a "
        "startup wait, so the size and speed benefit appears gradually after "
        "that task next runs rather than the moment the app updates.",
    ),
    test_steps=(
        "Update and relaunch the app with an existing library — it opens "
        "normally, with no extra startup delay or blocking dialog.",
        "Use the channel list, favorites, and any hidden/rating/watch-status "
        "filter as usual — results and counts are unchanged from before.",
        "Leave the app running for a while (or relaunch once more) to let the "
        "background index-maintenance task complete — no user action is "
        "needed and nothing visible marks its completion.",
    ),
)
