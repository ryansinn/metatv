from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=691,
    version="0.136.0",
    date="2026-10-09",
    title="Copy chips show what the stream really is",
    items=(
        "Once a copy has been played or probed, its chip in 'Available in' "
        "shows the measured quality with a ✓ instead of the name's claim.",
        "A copy whose audio contradicts its label says so on the chip — "
        "'Sweden (SE) · English audio'. Subtitles and full measurements are in "
        "the chip's tooltip.",
    ),
    test_steps=(
        "Play or 'Get stream details' on a copy, reselect the title — that copy's "
        "chip badge reads e.g. 'FHD ✓'; unmeasured copies keep their plain badge.",
        "On a copy named 4K that measures 1080p — the badge reads 'FHD ✓' and the "
        "tooltip says 'Name says 4K'.",
        "Measure an SE copy that is really English — its chip reads "
        "'Sweden (SE) · English audio'.",
        "Hover a measured chip — the tooltip lists size, audio languages and subtitles.",
    ),
)
