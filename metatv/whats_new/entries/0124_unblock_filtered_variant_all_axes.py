from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=124,
    version="0.9.0",
    date="2026-06-29",
    title="'Remove filter on … content' now actually un-filters the variant",
    items=(
        "Right-clicking a chip under 'Filtered variants' in the details pane and "
        "choosing 'Remove filter on <X> content' now actually removes the filter, "
        "refreshes the pane, and migrates that variant up into 'Also available as'. "
        "Before, it silently did nothing for some content — no change, no message — and "
        "the variant stayed filtered even after reopening the title.",
        "Cause: a variant is flagged 'filtered' when its prefix is excluded on EITHER "
        "the prefix axis OR the Content-Categories axis, but the un-filter only cleared "
        "the prefix axis. So anything excluded via the category axis couldn't be undone "
        "from the chip. It now clears the token from both axes.",
    ),
    test_steps=(
        "Find a title that shows a chip under 'Filtered variants' in the details pane "
        "(e.g. an FR/France variant).",
        "Right-click that chip and choose 'Remove filter on <X> content'.",
        "Confirm the pane refreshes, a '<X> content visible again' message appears, and "
        "the variant moves up from 'Filtered variants' into 'Also available as'.",
        "Right-click the (now un-filtered) variant again: it should no longer offer "
        "'Remove filter' as a filtered item, and it stays visible after switching to "
        "another title and back.",
    ),
)
