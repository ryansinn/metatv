from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=477,
    version="0.64.0",
    date="2026-08-31",
    title="The app no longer freezes while sports are being re-sorted",
    items=(
        "The one-off pass that re-sorts sports and events used to lock the "
        "database in long stretches. Anything else that wanted to save "
        "something during those stretches — a watch-list change, a rating, "
        "a source's connection stats — waited, and after thirty seconds gave "
        "up. The window froze for up to half a minute at a time and the pass "
        "itself eventually died partway through.",
        "The pass now works in small pieces and only writes the channels whose "
        "labels actually change, which is about one in eighty. Measured on a "
        "half-gigabyte library: the longest it holds the database went from "
        "90ms to 6ms, and the total from 2.9 seconds to 0.14.",
        "Removing or adding a watch-list keyword no longer waits on the "
        "database at all — the click is instant, and the list updates "
        "immediately whether or not the save has finished.",
        "If a watch-list change cannot be saved you now get an error saying so. "
        "Before, Remove would quietly do nothing and the rule stayed.",
        "If the re-sorting pass is interrupted it starts again next launch "
        "instead of recording itself as finished, and the second run skips the "
        "channels the first one already fixed.",
    ),
    test_steps=(
        ("Open the EPG watchlist, remove a keyword, and confirm it disappears "
         "at once with no pause.", "view:epg"),
        ("Add a keyword, close the app, reopen it, and confirm the keyword is "
         "still there — the save must survive quitting straight after the "
         "click.", "view:epg"),
        ("Add a watch keyword from the details pane bell and confirm it shows "
         "up in the EPG watchlist tab.", "view:epg"),
        "Set sports_reclassify_version to 2 in config.yaml, relaunch, and "
        "confirm the migration progress runs to completion without the window "
        "becoming unresponsive.",
        "While that pass is running, favourite a channel and rate another one; "
        "both should save with no freeze and no error toast.",
        ("Open the Sports view afterwards and confirm the leagues look right — "
         "no Green Bay stations under the NBA.", "view:sports"),
    ),
)
