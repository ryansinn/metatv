from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=66,
    version="0.9.0",
    date="2026-06-24",
    title="Language-aware audio facets — Sub, Dub, and Audio Format detection",
    items=(
        "Channel names with sub/dub/multi annotations (e.g. '(ENG DUB)', "
        "'(SPANISH ENG-SUB)', '[Multi-Sub]', '(VOSTFR)', '(DUAL AUDIO)') now "
        "produce captured facets: language:, subtitle:, dub:, and format:.",
        "The language: facet is the union of all languages the annotation denotes "
        "(audio track + dub + subtitle languages), so searching for 'English' finds "
        "both English-audio and English-subtitled content.",
        "subtitle: and dub: facets identify the specific role of each language — "
        "'subtitle:English' on a Spanish-audio / English-subtitled channel, "
        "'dub:Kurdish' on a Kurdish-dubbed channel.",
        "format: captures the presentation type: Dub, Original, Multi, or Dual. "
        "format:Original is inferred (lower confidence) when only a SUB marker is "
        "present; explicit DUB, Multi, or Dual markers are captured with high confidence.",
        "New filter sections — Subtitle Language, Dub Language, and Audio Format — "
        "appear in the Filter Panel and Recipe Builder once channels with these "
        "annotations are in your library.",
        "Tags appear in the channel Details pane Tags section immediately below Language.",
        "A one-time full re-tag migration runs at launch to backfill all existing channels.",
    ),
    test_steps=(
        "Find a channel with '(ENG DUB)' in its name and open its details pane. "
        "In the Tags section, confirm 'Language: English', 'Dub: English', and "
        "'Audio Format: Dub' chips appear.",
        "Find a channel with '(SPANISH ENG-SUB)' or similar. Open details pane. "
        "Confirm Language shows Spanish and English, Subtitle shows English, "
        "and Audio Format shows Original (with a low-confidence indicator).",
        "Find a '[Multi-Sub]' channel. Confirm Subtitle: Multi and Audio Format: Multi.",
        "Open the Filter Panel. Confirm new 'Subtitle Language', 'Dub Language', "
        "and 'Audio Format' sections appear (they appear once the library has such channels).",
        "In the Filter Panel, check only 'Dub' under Audio Format. Confirm the channel "
        "list filters to only dubbed content.",
        "Open the Recipe Builder (✦ chip). Confirm the new facets appear in the Pantry "
        "sidebar when audio-annotated channels exist in the library.",
        "After the first launch, confirm the 'Cleaning channel title qualifiers' and "
        "'Backfilling content tags' migration indicators complete without error.",
    ),
)
