from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=215,
    version="0.18.0",
    date="2026-08-01",
    title="Double-click now browses series / plays movies in Watch Queue & Alerts Matched",
    items=(
        "Double-clicking a series row in the Watch Queue or Alerts Matched "
        "used to behave exactly like a single click — it just loaded the "
        "series info into the details pane. Double-click now actually "
        "browses into it, opening the season/episode tree.",
        "Double-clicking a movie (or other leaf item) in Alerts Matched now "
        "plays it directly, the same as a plain queue row — previously it "
        "only opened details.",
        "Matched rows still get marked as seen on double-click, same as "
        "before — for a matched series, opening its episode tree is itself "
        "the acknowledgment.",
        "Alerts Matched rows — both movie/series keyword matches and "
        "monitored-series-with-new-episodes rows — now have a right-click "
        "menu. Movie/series matches get the standard channel menu (Play, "
        "Favorite, Watch Later, etc.); monitored-series rows get \"Open "
        "series\" and \"Mark seen\".",
        "Hover any Watch Queue or Alerts Matched row to see whether "
        "double-click will play it or browse into it.",
    ),
    test_steps=(
        "Add a series to the Watch Queue → double-click it → the season/"
        "episode tree opens (not just the details pane).",
        "Add a movie to the Watch Queue → double-click it → it plays "
        "immediately.",
        "Trigger a watch-for alert match on a movie → in the Watch Queue's "
        "Alerts Matched section, double-click the row → it plays, and the "
        "green NEW tag clears.",
        "Monitor a series with new episodes → in Alerts Matched, double-click "
        "the 🆕 series row → the season/episode tree opens and the new-episode "
        "count clears.",
        "Right-click a matched movie row in Alerts Matched → the standard "
        "channel context menu appears (Play, Favorite, Watch Later, …).",
        "Right-click a matched series row in Alerts Matched → a menu with "
        "'Open series' and 'Mark seen' appears; 'Mark seen' clears the "
        "new-episode count without navigating away.",
    ),
)
