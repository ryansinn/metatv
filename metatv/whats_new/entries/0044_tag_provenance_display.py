from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=44,
    version="0.9.0",
    date="2026-06-23",
    title="Tag provenance + confidence in details pane",
    items=(
        (
            "The details pane now shows a 'Tags' section for every channel, "
            "listing its stored content tags (language, region, genre, platform, "
            "quality, decade, collection) grouped by category."
        ),
        (
            "Each tag chip is labeled with its provenance: a solid ■ marker means "
            "the provider directly supplied that value; a hollow □ marker means "
            "MetaTV inferred it from the channel name, category header, or EPG data."
        ),
        (
            "Low-confidence tags (inferred from a single signal) are shown in "
            "muted/dashed style so you can immediately see which labels are "
            "strong assertions vs. educated guesses — but every tag is always shown "
            "(DR-0006: confidence ranks, never suppresses)."
        ),
        (
            "Hover any tag chip to see a tooltip with the exact feeder(s) that "
            "produced it, the provenance label, and the confidence percentage."
        ),
    ),
    test_steps=(
        "Select a live channel with a prefix (e.g. 'UK BBC One') → open the details pane"
        " → confirm a 'Tags' collapsible section appears with at least one chip.",
        "Verify chips show either a solid ■ (source-given) or hollow □ (inferred) provenance marker.",
        "Hover a tag chip → tooltip must show feeder name, provenance label, and confidence %.",
        "Select a channel with no tags → 'Tags' section must be absent or empty (not a blank header).",
    ),
)
