from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=536,
    version="0.76.0",
    date="2026-09-02",
    title="Clicking OK in Settings no longer re-filters your whole library twice",
    items=(
        "OK froze the app for 27 seconds. Eleven things run when settings are "
        "applied, and two of them each rebuilt the entire channel list from "
        "scratch — so one OK re-filtered 785,551 rows twice, whether or not "
        "you had changed anything that affects the list.",
        "The list is now rebuilt once, after everything else has been applied, "
        "and only if something actually asked for it. Change a setting that "
        "does not affect which rows are shown and the list is not requeried at "
        "all.",
        "One misbehaving setting can no longer stop the others being applied — "
        "each is now applied independently.",
        "For diagnosing the rest: the app now logs how long each part of "
        "applying settings took, so a slow OK can be attributed instead of "
        "guessed at.",
    ),
    test_steps=(
        ("Open Settings, change the theme, click OK. It should apply promptly "
         "and the channel list should NOT flicker through a reload.",
         "view:list"),
        ("Change the adult-content mode and click OK. The list must reload "
         "exactly once and show the right rows.", "view:list"),
        ("Change 'collapse variants' and click OK — again exactly one reload, "
         "with the setting visibly applied.", "view:list"),
        ("Change both of those in one visit and click OK: still one reload.",
         "view:list"),
        ("Change several unrelated settings (density, menu bar, sidebar "
         "sections) and confirm each takes effect and OK returns quickly.",
         "view:list"),
    ),
)
