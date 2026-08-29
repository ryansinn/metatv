from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=444,
    version="0.55.0",
    date="2026-08-29",
    title="Saving your settings is six times faster",
    items=(
        "The app writes your settings file often - after a filter change, a "
        "shelf collapse, a selection. Each write took about 75ms and happened "
        "on the same thread that draws the interface.",
        "A startup log showed 13 of those writes in 57 seconds: 1.8 seconds "
        "of the app simply not responding, including five writes inside one "
        "second.",
        "Almost all of that was one step - turning the settings into text. "
        "Using the faster text writer that ships with the app's YAML library "
        "takes it from 75ms to 13ms.",
        "The settings file is unchanged in content. Every one of the 288 "
        "settings was checked to survive a save and reload.",
    ),
    test_steps=(
        "Change several filters in quick succession and confirm the interface "
        "keeps up rather than stuttering between each one.",
        "Restart and confirm every setting, saved recipe and watchlist entry "
        "is exactly as you left it.",
        "Confirm config.yaml.bak is still created alongside config.yaml.",
    ),
)
