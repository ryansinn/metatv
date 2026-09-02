from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=514,
    version="0.67.0",
    date="2026-09-02",
    title="Watch rules match whole words",
    items=(
        "A watch rule for \"NFL\" was matching Inflammation and Börsenflash. "
        "One for \"Dragon\" was matching Dragonfly. The term is not really in "
        "those titles — it just happens to be spelled inside a longer word — "
        "so the rule was not so much imprecise as wrong.",
        "Rules now match whole words. If you want the old behaviour for a "
        "particular rule there is a \"contains, anywhere\" switch on it, and "
        "every rule you already had has been marked whole-word explicitly "
        "rather than silently inheriting the new setting.",
        "Rules can also carry exclude terms — \"Denver\" without \"news\" or "
        "\"pregame\" — which is the half that makes a broad term usable.",
        "Under the hood the guide list, the highlight on Browse and On Now, "
        "and the notification all now ask the same question. They used to ask "
        "it seven different ways, so a programme could appear in your "
        "watchlist and not be highlighted, or raise an alert for something "
        "the list never showed.",
    ),
    test_steps=(
        ("Add a watch rule for a short term that appears inside longer words "
         "(for example NFL) and confirm the Watch Alerts list no longer shows "
         "unrelated programmes.", "view:epg"),
        ("Open EPG Browse and confirm the highlighted rows are exactly the "
         "ones the watchlist lists — no highlighted row that is not a match.",
         "view:browse"),
        ("Open On Now and confirm the same highlighting agrees with the "
         "watchlist.", "view:epg"),
        ("Confirm an existing rule you had before this update still matches "
         "the programmes you expect."),
        ("Restart the app and confirm the log shows no migration error for "
         "alert_patterns, and your rules are all still present."),
    ),
)
