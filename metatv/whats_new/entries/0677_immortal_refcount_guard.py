from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=677,
    version="0.125.0",
    date="2026-09-29",
    title="The app no longer crashes after running for days",
    items=(
        "After several days open, the app could abort all at once with "
        "\"__init__() should return None\" errors from every background task. "
        "The cause was a reference-count leak in PyQt6 on Python 3.14 that "
        "slowly broke Python's own None; MetaTV now repairs the count every "
        "minute, long before it can do harm.",
    ),
    test_steps=(
        "Launch the app — it starts normally and the log shows no "
        "\"Immortal refcount guard\" warning.",
        "Leave it running overnight with a stream playing — it is still "
        "responsive in the morning; any \"Immortal refcount guard: reset None\" "
        "log line reports the drift rate instead of a crash.",
    ),
)
