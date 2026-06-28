from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=77,
    version="0.8.0",
    date="2026-06-28",
    title="Filtered variants collapse into a hidden FILTERED VARIANTS section",
    items=(
        '"Also available as:" label now sits on its own line directly above the chip'
        " flow, giving chips the full width instead of sharing a row with the label.",
        "Filtered/hidden variants are no longer mixed into the active chip row."
        " They collapse into a FILTERED VARIANTS sub-section that is hidden by default;"
        " click the > chevron to expand it.",
        "Right-click menus on greyed chips (Unhide / Remove filter / Manage filters)"
        " work exactly as before inside the collapsed section.",
    ),
    test_steps=(
        "Open a channel that has many variants (some filtered out via Content Categories)."
        ' The "Also available as:" label should appear on its own line above the chips,'
        " and chips should wrap across the full available width.",
        "Confirm that filtered/hidden variants are NOT visible in the main chip row."
        ' A "FILTERED VARIANTS" header with a > chevron should appear below the active chips.',
        'Click the > chevron next to "FILTERED VARIANTS" — the greyed-out chips for'
        " filtered variants should expand into view and the chevron should change to ⌄.",
        "Click the chevron again — the filtered chips should collapse back out of view.",
        "Right-click a greyed chip inside the expanded section — the"
        ' "Unhide / Remove filter / Manage filters" menu should appear and work normally.',
    ),
)
