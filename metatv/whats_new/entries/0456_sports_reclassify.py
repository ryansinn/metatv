from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=456,
    version="0.58.0",
    date="2026-08-30",
    title="Sports channels are re-sorted, not just sorted better",
    items=(
        "The last update taught the app to match league names as whole words, "
        "so a movie called Conflict would stop being filed under the NFL. You "
        "would not have seen a single change: the sorter only ever looks at "
        "channels it has never seen before, so the fix reached new content and "
        "left everything already in your library exactly as wrong as it was.",
        "This runs the corrected sorter over all 785,163 channels. 9,825 "
        "change. 729 leave Premier League, 467 leave the NBA and 446 leave "
        "the NFL — none of them were ever those sports.",
        "The same bug was hiding in a second place — the check for whether "
        "something is a sports channel AT ALL. So \"Conflict\" lost its NFL "
        "label and stayed in the sports list anyway, just unlabelled. The "
        "sports list goes from 35,181 channels to 28,018.",
        "That second one needed a different fix, not the same one. Matching "
        "\"sport\" as a whole word would have dropped SPORTSNET, SPECTRUM "
        "SPORTS and CBS SPORTS NETWORK — 11,451 real channels, far more "
        "damage than the bug. Descriptive words now match the start of a "
        "word so they can compound; short acronyms match whole.",
        "It also got 12x faster on the way past. The sorter re-read and "
        "re-parsed its keyword file once per channel — 4.3ms each, which was "
        "the entire cost of sorting a channel. Re-sorting your library would "
        "have taken 18 minutes; it now takes about 90 seconds, and every "
        "source refresh gets the same speedup.",
        "Real sports are unaffected — NFL Network, NBA TV, ESPN, beIN, the "
        "Premier League channels and UFC all keep their leagues, and 275 "
        "Formula 1 channels that were being missed are now found. Pay-per-view "
        "events filed as plain sports move to PPV where they belong.",
    ),
    test_steps=(
        "Launch MetaTV and let the startup step \"Re-sorting sports and "
        "events\" finish.",
        ("Filter by NBA. Every result should be basketball — no Green Bay "
         "local stations, no US network affiliates.", "view:browse"),
        "Filter by Formula 1 and confirm TF1 (the French channel) is not there, "
        "and that real F1 channels are.",
        "Filter by NFL and confirm no movies appear — \"Conflict\" in "
        "particular should not be listed as a sports channel at all.",
        "Confirm NHL, Premier League, UFC and beIN/ESPN channels are all still "
        "present and correctly labelled — the pass must not simply delete "
        "everything it touches.",
        "Quit and relaunch: the re-sorting step must not run a second time.",
    ),
)
