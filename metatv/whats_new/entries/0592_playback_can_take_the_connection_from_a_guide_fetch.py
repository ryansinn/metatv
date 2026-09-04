from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=592,
    version="0.95.0",
    date="2026-09-04",
    title="Playback can take the connection from a guide fetch",
    items=(
        "Starting a stream while its source is downloading the guide no "
        "longer waits on the download — the fetch yields the connection.",
        "It keeps every programme it had fully read, replacing the stored "
        "guide only when that is more than it already had.",
        "The fetch finishes on a later scheduled refresh; nothing half-read "
        "is ever stored.",
    ),
    test_steps=(
        "Trigger a guide refresh on a one-connection source and immediately "
        "play a channel on it → playback starts within a few seconds and the "
        "guide notice says the fetch paused for playback.",
        "Wait for the next scheduled refresh → the guide completes normally.",
    ),
)
