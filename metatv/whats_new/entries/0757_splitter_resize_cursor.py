from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=757,
    version="0.194.0",
    date="2026-10-20",
    title="Column dividers show the resize cursor everywhere",
    items=("Hovering the divider beside the sidebar or the details pane shows the "
           "left-and-right resize arrows on every platform, not a pointing hand.",),
    test_steps=("Hover the divider between the sidebar and the channel list, then the one "
                "before the details pane — the cursor becomes the left-right resize arrows.",),
)
