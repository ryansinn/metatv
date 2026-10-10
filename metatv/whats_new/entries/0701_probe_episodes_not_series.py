from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=701,
    version="0.141.0",
    date="2026-10-09",
    title="Get stream details works on episodes",
    items=(
        "A series has no stream of its own, so its overview no longer offers "
        "'Get stream details'; select an episode and the button measures that "
        "episode.",
    ),
    test_steps=(
        "Open a series — its overview Details has no 'Get stream details' button.",
        "Select an episode in the tree — the button appears; press it — after a "
        "few seconds that episode's Resolution / Video / Audio rows appear with "
        "'· probed <date>'.",
        "If a probe fails, the log line now ends with mpv's own error message.",
    ),
)
