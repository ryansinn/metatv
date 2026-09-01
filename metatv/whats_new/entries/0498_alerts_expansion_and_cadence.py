from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=498,
    version="0.64.0",
    date="2026-09-01",
    title="Watch Alerts rows that would not stay shut, and a watchlist check in the way",
    items=(
        "In Watch Alerts, a programme showing on several sources at once drew a "
        "closed arrow over its already-open list of airings — and collapsing "
        "one never stuck, because the next refresh opened it again.",
        "The arrow now reports what the row is actually doing, and a group you "
        "collapse or expand stays that way. The automatic tidy-up that keeps a "
        "long watchlist compact can still fold groups it folded itself, but it "
        "will not overrule you.",
        "Separately, the watchlist check no longer runs the instant the app "
        "opens — which was exactly when you were trying to play something, and "
        "on a source that allows one connection those competed. It waits a few "
        "minutes, and the repeat check is now once a day instead of hourly.",
    ),
    test_steps=(
        ("In Watch Alerts, find a programme listed on more than one source and "
         "confirm its arrow matches whether the airings are showing.",
         "view:list"),
        ("Collapse one of those groups, wait for the list to refresh, and "
         "confirm it is still collapsed.", "view:list"),
        ("Expand a group while the list is long, and confirm it stays open.",
         "view:list"),
        "Open the app and play something straight away — it should not be "
        "competing with a watchlist check.",
    ),
)
