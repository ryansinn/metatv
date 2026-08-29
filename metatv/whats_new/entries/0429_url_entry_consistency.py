from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=429,
    version="0.54.0",
    date="2026-08-29",
    title="Adding source URLs works the same in both places",
    items=(
        "Pressing Enter in the URL field now adds the URL when setting up a "
        "new source. It already did that when editing an existing one, so the "
        "same keystroke used to do two different things.",
        "After adding, the cursor stays in the now-empty field, so several "
        "fallback URLs can be typed one after another without reaching for "
        "the mouse.",
        "The URL box now sits above the list in both places. It was above in "
        "one and below in the other.",
    ),
    test_steps=(
        "Add a new source, type a URL, press Enter, and confirm it lands in "
        "the list.",
        "Type a second and third URL, pressing Enter each time, without "
        "clicking anything.",
        "Confirm the URL box appears above the list, matching the source "
        "editor.",
        "Do the same in an existing source's settings and confirm it behaves "
        "identically.",
    ),
)
