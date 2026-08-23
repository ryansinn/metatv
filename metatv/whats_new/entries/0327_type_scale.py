from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=327,
    version="0.40.0",
    date="2026-08-22",
    title="Text is bigger, and size means something again",
    items=(
        "The interface had nine text sizes, but seven of them sat within 6px "
        "of each other — a section heading was only four pixels larger than "
        "the smallest label. Nothing looked bigger than anything else, so "
        "bold text was doing almost all the work of showing what mattered.",
        "The sizes have been rebuilt as a proper scale, with each step "
        "meaningfully larger than the one below it. Body text — channel "
        "names, descriptions, most of what you read — goes from 11px to 13px.",
        "Headings and view titles grew the most, so a title now reads as a "
        "title at a glance instead of as slightly heavier body text.",
        "The tag cloud's size range widened in step, so a heavily-used tag "
        "stands out from a rare one more clearly.",
    ),
    test_steps=(
        "Open the channel list — the channel names and the text under them "
        "are noticeably larger and easier to read than before.",
        "Look at a section heading in the sidebar next to the rows beneath "
        "it — the heading is clearly the larger of the two, not just bolder.",
        "Open the details pane for any title — the title at the top reads as "
        "a heading, distinctly larger than the description below it.",
        "Open Recipe (or the tag cloud) — the difference between a common tag "
        "and a rare one is easier to see at a glance.",
        "Switch between Midnight, Graphite and Daylight in Settings → Style — "
        "text sizes stay identical in all three; only colours change.",
        "Resize the window narrow and check the sidebar and details pane — "
        "the larger text still fits without labels being cut off.",
    ),
)
