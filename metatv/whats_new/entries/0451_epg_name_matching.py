from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=451,
    version="0.56.0",
    date="2026-08-30",
    title="Your guide now reaches the sources that had none",
    items=(
        "ProSat had no programme guide at all, and TREX had almost none - so "
        "On Now, Watch Alerts and anything scheduled only really worked on one "
        "of your three sources.",
        "The guide data was already downloaded. Nothing was reaching those "
        "channels because the app compares names to decide which guide entry "
        "belongs to which channel, and the two sides never produced the same "
        "text.",
        "One source writes a channel as \"OD| ESPN 4\" with the HD in tiny "
        "raised letters; the other writes \"|NL| ESPN 4 HD\". The old "
        "comparison kept the source's own prefix and could not see the raised "
        "letters as quality, so the same channel never matched itself.",
        "It now uses the same name parser the rest of the app already uses at "
        "import time, and drops the decorative lettering.",
        "ProSat went from 27 matched channels to 2,946, and TREX from 6 to "
        "8,870. Channels that only share a name by coincidence - a UK channel "
        "and an Italian guide entry - are still kept apart.",
    ),
    test_steps=(
        "Open EPG > On Now and confirm ProSat channels now show programme "
        "titles rather than being blank.",
        "Confirm a channel's guide matches the channel - a UK channel should "
        "not be showing an Italian schedule.",
        "Open Watch Alerts and confirm EPG matches appear from more than one "
        "source.",
        "Confirm channels that already had correct guide data still do.",
    ),
)
