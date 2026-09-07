from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=626,
    version="0.103.0",
    date="2026-09-07",
    title="The \"refresh when Sports opens\" option is gone",
    items=(
        "Settings -> Content -> Live catalog refresh no longer offers "
        "\"Whenever Sports or Events opens\". The Sports and Events views were "
        "retired two releases ago, so nothing was left to open — picking it "
        "did nothing at all.",
        "If you had it selected, it now reads Manual, which is what it had "
        "actually been doing. The change is made once when the app starts and "
        "is written to the log; every other refresh rate is left alone.",
    ),
    test_steps=(
        "Settings -> Content -> Live catalog refresh -> open the dropdown: it "
        "lists Manual and the four intervals (15 minutes, 30 minutes, hourly, "
        "3 hours) and nothing mentioning Sports or Events.",
        "Pick \"Every 30 minutes\", press OK, reopen Settings: it still reads "
        "Every 30 minutes.",
        "Quit, set live_refresh_mode: on_view_open in "
        "~/.config/metatv/config.yaml (and delete the live_refresh_mode_version "
        "line if present), relaunch: Settings shows Manual, and the log carries "
        "a \"Config migration: live_refresh_mode was 'on_view_open'\" line.",
    ),
)
