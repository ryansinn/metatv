from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=437,
    version="0.54.0",
    date="2026-08-29",
    title="Help - About now opens something",
    items=(
        "The About item has been in the Help menu for a long time and did "
        "nothing at all when clicked.",
        "It now shows the MetaTV version and build, the Python, Qt and PyQt "
        "versions, the platform, and which mpv it is using - including where "
        "that mpv was found, which has been a real support question.",
        "A Copy details button puts all of it on the clipboard in one press, "
        "for pasting into a message or a bug report.",
        "If mpv is missing or will not answer, it says so rather than leaving "
        "the line blank - that is exactly when you need to know.",
        "It also carries the open-source notice for mpv, which the packaged "
        "app redistributes, with a link to its source.",
    ),
    test_steps=(
        "Open Help then About and confirm a window appears with the version "
        "block filled in.",
        "Confirm the mpv line names a version and a path.",
        "Press Copy details, paste elsewhere, and confirm the text matches "
        "what the window shows.",
        "Confirm the mpv licence notice and its source link are shown.",
    ),
)
