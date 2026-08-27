from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=388,
    version="0.41.0",
    date="2026-08-27",
    title="The playback-health readout responds to a click again",
    items=(
        "Clicking the playback-health readout in the header did nothing. It "
        "is supposed to cycle between open player windows. The click handler "
        "referred to a name the module never imported, so every click raised "
        "an error that Qt discarded without showing anything.",
        "Found by a linter, which this project did not have until now. It "
        "also removed 467 unused imports, 30 duplicate entries in the "
        "stopword and region lookup tables, and 30 leftover placeholder "
        "statements across 233 files - none of which changes behaviour.",
        "Every pull request now runs the linter before the test suite, so "
        "this class of mistake is reported in seconds rather than never.",
    ),
    test_steps=(
        "Play a channel so the playback-health readout appears in the header "
        "(right-hand side, next to Split), then click it - the full readout "
        "should appear rather than nothing happening.",
        "With Split Streams on and two channels playing, click the readout "
        "repeatedly - focus should move between the open player windows.",
        "Right-click the same readout - it must NOT trigger the readout, "
        "which is what proves the left-button test still runs.",
        "Open the sidebar, Watch Alerts, Discover, Recipe and Settings in "
        "turn and confirm each still loads; the import cleanup touched 233 "
        "files and a wrongly removed import would surface as a blank view or "
        "an error on open.",
        "Switch theme (Settings > Style) and confirm the header, sidebar and "
        "details pane all restyle - theme.py was one of the files touched.",
    ),
)
