from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=511,
    version="0.66.0",
    date="2026-09-01",
    title="Fixes an upgrade that left the app unable to read its own library",
    items=(
        "Two recent changes added new fields to the database but never told "
        "MetaTV how to add them to a library that already existed. On upgrade "
        "the app asked for columns that were not there, so the channel list, "
        "Favourites, Discover and the signal checker all failed — while a "
        "brand-new install worked perfectly, which is why it was not caught "
        "sooner.",
        "Upgrading now adds the missing fields on the next launch. Nothing is "
        "lost and no re-download is needed.",
    ),
    test_steps=(
        ("Launch MetaTV on an existing library and confirm the channel list "
         "loads.", "view:browse"),
        ("Confirm Favourites in the sidebar populates."),
        ("Open Discover and confirm shelves load.", "view:discover"),
        ("Check the log for 'Migration: added column' lines on the first "
         "launch after upgrading, and for the absence of 'no such column'."),
    ),
)
