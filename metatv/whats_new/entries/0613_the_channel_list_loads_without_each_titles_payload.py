from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=613,
    version="0.101.0",
    date="2026-09-06",
    title="The channel list loads without each title's provider payload",
    items=(
        "Opening or filtering the channel list no longer reads every title's "
        "raw provider record from the database — that data was never used on "
        "this path, and skipping it makes the list faster to load and filter.",
    ),
    test_steps=(
        "Open a large source's channel list and apply a filter — same rows "
        "come back, faster.",
        "Open a title's details pane — cast, genre and trailer (everything "
        "that used the payload) still show.",
    ),
)
