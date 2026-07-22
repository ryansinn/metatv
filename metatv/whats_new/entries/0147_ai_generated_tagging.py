from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=147,
    version="0.10.0",
    date="2026-07-22",
    title="AI-generated content and AI voiceovers are now tagged (and excludable)",
    items=(
        "Two new AI-provenance markers are recognised at ingestion and stored as "
        "Content Type tags you can filter on. A trailing \"(AI Generated)\" suffix "
        "(the fabricated music-video \"collaborations\") tags the item "
        "content_type:ai_generated — the CONTENT itself is AI-made. A trailing "
        "\"(AI)\" suffix (Polish \"Lektor\" voice-over VOD) tags it "
        "content_type:ai_voiceover — an AI dub, not AI content. They are kept as "
        "two distinct values so you can tolerate AI dubs while excluding AI content, "
        "or vice-versa.",
        "The \"(AI)\" voiceover marker is stripped from the title (so the item reads "
        "cleanly and collapses onto the real film as a language variant), and it no "
        "longer masquerades as a bogus \"AI\" region. The \"(AI Generated)\" content "
        "marker is deliberately kept in the title so a fabricated work never merges "
        "with a real same-title production.",
        "Open the Recipe / tag-cloud view and you will find a Content Type facet "
        "with ai_generated and ai_voiceover; exclude a value there to hide that kind "
        "of content everywhere the recipe drives.",
    ),
    test_steps=(
        "Find an \"[MV] … (AI Generated)\" movie, open its details, and confirm a "
        "\"Content Type\" tag group shows an \"ai_generated\" chip; the title still "
        "shows the \"(AI Generated)\" marker (kept on purpose so it stays a distinct "
        "production).",
        "Find a Polish \"… Lektor (AI)\" movie, open its details, and confirm a "
        "\"Content Type\" group shows an \"ai_voiceover\" chip while the title reads "
        "cleanly with the \"(AI)\" marker removed (and it is not tagged region \"AI\").",
        "Open the Recipe / tag-cloud view, locate the Content Type facet, and "
        "confirm both new values (ai_generated, ai_voiceover) appear with counts.",
        "Toggle the ai_generated value to excluded in the recipe and confirm the "
        "\"(AI Generated)\" items drop out of the results while the \"(AI)\" "
        "voiceover items remain.",
    ),
)
