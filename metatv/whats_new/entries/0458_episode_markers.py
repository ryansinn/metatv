from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=458,
    version="0.58.0",
    date="2026-08-30",
    title="One card per show, not one per episode",
    items=(
        "Some of your sources file a series as loose movies — one entry per "
        "episode, named \"Konusanlar S01E57\". Browse showed all 414 of them "
        "as 414 separate titles. Across your library that is 960 rows which "
        "are really 48 shows.",
        "The episode number is what made them look like different titles. It "
        "now comes out of the name and is kept as its own season and episode, "
        "so the 414 rows collapse into one Konusanlar card the same way every "
        "other duplicate already does.",
        "Only the S01E57 spelling. The \"1x05\" form was checked against your "
        "whole library and every single match was a real film — 10x10, 8x10 "
        "Tasveer, 12x12 — so treating it as an episode number would have "
        "renamed five movies and stamped them with a season.",
        "Nothing else in the library gains a season or episode: all 784,203 "
        "other titles were checked.",
    ),
    test_steps=(
        "Launch MetaTV and let the startup migration finish.",
        ("Search Browse for \"Konusanlar\". You should see ONE result, not "
         "hundreds — and its title should be just \"Konusanlar\", with no "
         "S01E57 in it.", "view:browse"),
        "Search for \"Sihirli Annem\", \"Leyla ile Mecnun\" and \"Gibi\". Each "
        "should be a single card.",
        "Search for \"10x10\". The 2018 film must still be called 10x10 — not "
        "renamed, and not filed as an episode of anything.",
        "Search for \"Se7en\" and \"WWE Raw\" and confirm neither has changed.",
    ),
)
