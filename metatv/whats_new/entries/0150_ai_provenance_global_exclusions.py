from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=150,
    version="0.10.0",
    date="2026-07-22",
    title="Globally exclude AI content — new \"Content Provenance\" exclusions",
    items=(
        "The Global Exclusions dialog now has a \"Content Provenance\" section, "
        "separate from the source-category Content Types list. It lists the "
        "AI-provenance types — AI Generated and AI Voiceover — each with a live "
        "channel count. Check one to hide that kind of content everywhere: search, "
        "Discovery, Recommendations, the recipe/tag-cloud, and EPG On-Now.",
        "Content Type tag values now render friendly names instead of raw slugs. "
        "Everywhere they surface — the details-pane Content Type chips, the "
        "recipe/tag-cloud pantry, and the new dialog section — \"ai_generated\" reads "
        "\"AI Generated\" and \"ai_voiceover\" reads \"AI Voiceover\".",
        "Excluded AI variants are hidden from browsing but never erased: they still "
        "appear in a title's Other Versions panel, greyed out. Pause the Exclusions "
        "chip and everything reappears; resume to re-hide.",
    ),
    test_steps=(
        "Open the Exclusions dialog (bottom-bar chip → right-click, or the chip when "
        "nothing is set) and confirm a \"Content Provenance\" section lists "
        "\"AI Generated\" and \"AI Voiceover\" with channel counts — not the raw "
        "\"ai_generated\" / \"ai_voiceover\" slugs.",
        "Check \"AI Generated\", click OK, then search for an \"[MV] … (AI Generated)\" "
        "item: it no longer appears in the channel list or Discovery; the \"(AI)\" "
        "voiceover items are unaffected.",
        "Open any tagged item's details and confirm the Content Type chip now reads "
        "\"AI Generated\" / \"AI Voiceover\" (friendly name), not the slug.",
        "Left-click the Exclusions chip to PAUSE, and confirm the AI Generated items "
        "reappear; click again to RESUME and confirm they hide again.",
    ),
)
