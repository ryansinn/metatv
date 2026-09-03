from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=548,
    version="0.84.0",
    date="2026-09-02",
    title="A Downloaded scope on the channel list",
    items=(
        "A third scope tab joins the channel list: All | Downloaded | "
        "Hidden. Downloaded lists titles with at least one completed "
        "download.",
        "Downloaded titles show even when their source is disabled or a "
        "Global Exclusion would otherwise hide them — a file already saved "
        "to disk is engaged content, and it stays playable regardless.",
        "The scope survives a restart.",
        "Recordings are not part of this scope — they will join a future "
        "library view.",
    ),
    test_steps=(
        "Download a movie to completion, then click the Downloaded tab: it "
        "lists that title; a queued or running download does not appear.",
        "Disable the provider the download came from and check the "
        "Downloaded tab again: the title is still there.",
        "Restart the app with Downloaded selected: the tab is still "
        "selected and populated.",
    ),
)
