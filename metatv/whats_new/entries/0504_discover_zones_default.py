from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=504,
    version="0.64.0",
    date="2026-09-01",
    title="Discover was recording every shelf it had ever shown you",
    items=(
        "Collapsed is what a shelf is unless you pin, expand or hide it — and "
        "MetaTV was writing down every shelf that was collapsed, which is "
        "every shelf it had ever displayed. That list only ever grew.",
        "It now records only the shelves you have actually done something "
        "with. Your pinned, expanded and hidden shelves are untouched, and "
        "everything else looks exactly the same as before.",
    ),
    test_steps=(
        ("Open Discover and confirm your pinned, expanded and hidden shelves "
         "are exactly as you left them.", "view:discover"),
        "Collapse a shelf, restart MetaTV, and confirm it is still collapsed.",
        "Expand a shelf, restart, and confirm it is still expanded.",
        "Hide a shelf, restart, and confirm it is still hidden.",
    ),
)
