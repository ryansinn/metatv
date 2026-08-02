from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=241,
    version="0.21.0",
    date="2026-08-02",
    title="Cleaner categories + reorganized Comfy row chips",
    items=(
        "Provider categories that carried a leading marker duplicating "
        "channel-name language info (e.g. '|EN| ANIME', '|AR-SUB| AMAZON "
        "PRIME') no longer clutter the category chip — the marker is "
        "stripped into a clean collection chip, and the language/subtitle "
        "info it carried now shows as its own chip instead of being lost.",
        "Comfy and Comfy+ channel rows are reorganized: line 1 now ends "
        "with the quality chip hugging the title, then year/region/"
        "subtitle/language chips flush right (your channel's own language "
        "always sits furthest right); line 2 now shows just the clean "
        "collection chip flush right. Compact density is unchanged.",
    ),
    test_steps=(
        "Set Row density to 'Comfy' in Settings → Interface, then scroll the "
        "channel list to a title from a category like '|EN| ANIME' or "
        "'|AR-SUB| AMAZON PRIME' → line 1 ends with year/region/language "
        "chips flush right (no raw '|EN|'/'|AR-SUB|' text visible anywhere), "
        "and line 2 shows a clean collection chip (e.g. 'ANIME') flush "
        "right with no leftover pipe marker. Switch density to 'Compact' → "
        "the row layout is unchanged from before this release.",
    ),
)
