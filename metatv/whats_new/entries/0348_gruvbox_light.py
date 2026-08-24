from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=348,
    version="0.41.0",
    date="2026-08-24",
    title="Gruvbox Light — a warm light theme",
    items=(
        "Gruvbox now has a light variant too, so the only light theme is no "
        "longer a cold blue-grey one. Cream background, dark brown text.",
        "It uses Gruvbox's OWN published light accents — the darker red, green "
        "and blue that exist precisely because the bright ones are unreadable "
        "on cream — rather than being the dark theme turned inside out.",
    ),
    test_steps=(
        "Settings → Interface → Appearance → Theme → Gruvbox Light → OK. The "
        "app recolours to a cream background with dark brown text, immediately.",
        "Check the channel list: titles are dark brown, the quality badge is "
        "readable, and the language badge is legible on both a normal and a "
        "selected row.",
        "Select a row → every badge on it stays readable against the "
        "selection tint.",
        "Open the details pane → section headers, the region chips and the "
        "\"+ N more\" link all read clearly on cream.",
        "Favourite something and look at the star button in the details rail → "
        "its label is dark on the gold fill, not cream-on-gold.",
        "Open the preview overlay (⤢ on Similar Titles) → it stays the dark "
        "cinema panel it is in every theme, and its text is legible.",
        "Switch between Gruvbox and Gruvbox Light and back → no leftover "
        "patches from either.",
    ),
)
