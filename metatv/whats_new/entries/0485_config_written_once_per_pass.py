from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=485,
    version="0.64.0",
    date="2026-08-31",
    title="The app freezing for seconds at a time",
    items=(
        "The window would lock up for several seconds at a stretch — long "
        "enough that clicks and scrolling were simply lost. One session "
        "recorded 29 of these, the worst lasting over ten seconds.",
        "Every time the watchlist finished checking a series it rewrote your "
        "entire settings file, including making a backup copy of it first. "
        "With a dozen monitored series that is a dozen full rewrites per "
        "check, and all of it happened on the thread that draws the window.",
        "The same thing happened when the app filled in region and language "
        "for your monitored series — once per row.",
        "Both now write once when the work finishes instead of once per item.",
        "Worth knowing: settings files grow. A large part of yours is not "
        "settings at all but saved QA results, cached lists rebuilt from your "
        "catalogue anyway, and a record of every shelf you have ever "
        "collapsed. Trimming that is separate work, still to come.",
    ),
    test_steps=(
        ("Leave the app on the channel list for a few minutes while the "
         "watchlist checks run, and confirm the window stays responsive to "
         "scrolling and clicks throughout.", "view:list"),
        ("Open Watch Alerts and confirm episode counts and 'new episode' "
         "badges still update after a check completes.", "view:browse"),
        "Quit and relaunch, then confirm the watchlist did not forget its "
        "episode baselines — nothing should be reported as newly added that "
        "you had already seen.",
    ),
)
