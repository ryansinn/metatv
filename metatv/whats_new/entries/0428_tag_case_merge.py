from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=428,
    version="0.54.0",
    date="2026-08-29",
    title="Drama and DRAMA are one genre again",
    items=(
        "A genre written in different capitalisations became several separate "
        "tags, so you could see an empty DRAMA shelf sitting beside a full "
        "Drama one.",
        "Capitalisation and stray spaces no longer create a new tag - the "
        "spelling you saw first is the one shown.",
        "Existing duplicates are merged on next launch, and every channel is "
        "moved onto the surviving tag.",
        "Tags that no longer apply to anything are cleared out - there were "
        "288 of them.",
    ),
    test_steps=(
        "Open Discover and confirm there is one Drama shelf rather than "
        "several, and that it still has its content.",
        "Check other genres you have seen duplicated - Comedy, Kids, "
        "Documentary, Reality.",
        "Confirm genre filtering still selects the right channels.",
    ),
)
