from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=351,
    version="0.41.0",
    date="2026-08-25",
    title="The sidebar chrome catches up with the rows",
    items=(
        "\"Clear Watched\" and \"Clear History\" move into a ⋯ overflow at the "
        "foot of their section. A full-width button charged about 29px — more "
        "than a whole compact row — every session, whether or not there was "
        "anything to clear.",
        "Section headers end with → instead of ⤢. The arrow is the escalation "
        "to the full view; ⤢ was describing the destination's layout rather "
        "than the action.",
        "Recommended's refresh joins the same overflow, so every section's "
        "occasional actions are in the same place.",
        "The collapse chevron is a bare glyph rather than a bordered box — "
        "clicking anywhere on the header already toggles the section, so the "
        "button frame promised a control that was never the only way in.",
        "Watch Alerts looks like every other section again. Manage and + move "
        "from the header into the top of its body, each in its own ring so the "
        "boundary between them is obvious, and + keeps only its glyph and a "
        "tooltip.",
        "The Sources footer says one thing — the most urgent. It was showing "
        "up to four at once; now no sources, then none active, then expiring, "
        "then a plain count.",
        "\"Alerts Matched\" loses its 🚨. The render's group headings are text.",
    ),
    test_steps=(
        "Watch Queue → the ⋯ at the bottom right holds both Clear Watched and "
        "Clear All; no full-width button anywhere in the section.",
        "History → the same ⋯ holds Clear History, and one more row fits than "
        "before.",
        "Recommended → its ⋯ holds Refresh recommendations, and the header no "
        "longer carries a ⟳.",
        "Every section header → the right-hand control is an → arrow; clicking "
        "it still opens the full view.",
        "Click a section header anywhere → it collapses and expands, and the "
        "chevron is a bare glyph with no box around it.",
        "Watch Alerts → Manage and + sit at the TOP of the section body, each "
        "with a visible ring around it; hover + and the tooltip reads \"Watch "
        "for new content…\". Both still work.",
        "Collapse Watch Alerts → the header is the standard shape: title, news "
        "or count, arrow. Manage and + are reachable again by expanding it.",
        "Sources footer → with sources active and none expiring it reads "
        "\"N active\"; disable them all and it reads \"No active sources\".",
        "Watch Queue → the \"ALERTS MATCHED\" heading has no emoji.",
    ),
)
