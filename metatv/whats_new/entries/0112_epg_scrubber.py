from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=112,
    version="0.9.0",
    date="2026-06-28",
    title="EPG Browse: drag the new timeline scrubber to seek the schedule",
    items=(
        "Browse now has a timeline scrubber across the top of the list. Drag the "
        "handle to seek the schedule to any point in time — the list jumps to that "
        "moment and keeps loading forward from there.",
        "It is two-way: scrolling the list slides the handle to track the topmost "
        "visible programme, and dragging the handle reloads the list at that time. "
        "The handle opens at NOW each time you open Browse.",
        "With a 'Hide EPG older than' window set you can scrub back into the recent "
        "past (bounded by that window); with it at 0 the list stays strictly forward.",
        "New setting (Settings → Metadata & API Keys → EPG → 'Scrubber snap'): choose "
        "how coarsely dragging snaps — 15, 30 (default), or 60 minutes.",
    ),
    test_steps=(
        "Open EPG → Browse. Confirm a horizontal scrubber appears above the list with "
        "the handle at 'Now' and a centred label showing the current local time/day.",
        "Drag the handle to the right and release. Confirm the list reloads and the "
        "first row's time matches the handle position (snapped to your interval).",
        "Scroll the list down a few screens. Confirm the handle slides right to follow "
        "the topmost visible programme (and does not bounce / re-seek on its own).",
        "Open Settings → Metadata & API Keys → EPG, set 'Scrubber snap' to 60 minutes, "
        "click OK, reopen Settings, and confirm it persisted; back in Browse, dragging "
        "now snaps to whole hours.",
    ),
)
