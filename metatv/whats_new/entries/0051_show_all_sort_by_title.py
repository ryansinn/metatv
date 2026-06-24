from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=51,
    version="0.9.0",
    date="2026-06-24",
    title="Recipe 'Show all' sorts by clean title (ignores 4K-/prefix junk + case)",
    items=(
        "Recipe 'Show all' now sorts by the detected title rather than the raw "
        "channel name, so quality/region prefixes like '4K -' or '|EN|' no longer "
        "push titles out of alphabetical order ('4K - Ahsoka' sorts under 'A').",
        "Sorting is case-insensitive, so titles no longer split into separate "
        "A→Z runs by capitalization.",
    ),
    test_steps=(
        "Open a recipe with many matches → 'Show all' → titles are alphabetical by their real name; a '4K - ' title sorts under its title letter, not under '4'.",
        "Scroll all the way down (grid and list) → it stays one continuous A→Z run — it does NOT reach Z and restart at A.",
    ),
)
