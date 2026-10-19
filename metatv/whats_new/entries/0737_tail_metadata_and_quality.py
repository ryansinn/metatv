from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=737,
    version="0.174.0",
    date="2026-10-19",
    title="More titles get their quality; notes after the year land in the right place",
    items=("A quality written after the year (\"London Calling (2025) 4K\") or before a bracketed "
           "note (\"Troll 2 4K (MULTI-SUBS) (2025)\") is now recorded as the title's quality, "
           "and the 4K leaves the title. About 2,300 titles in a large library gain a quality, "
           "including live channels like \"SKY SPORT 4K [LIVE-EVENT]\".",
           "Words after the year that name a collection, dub, subtitles or genre — \"ARABIAN "
           "1001 NIGHTS COLLECTION\", \"DUBBING\", \"VOSTFR\", \"ANIMACJA\" — are read as that, not "
           "as an actor's name. Existing titles are re-read once on the next launch."),
    test_steps=("After the one-time re-read on launch, find \"London Calling\" — no 4K in the title, "
                "and its quality shows 4K; find \"Troll 2\" — title \"Troll 2\" with 4K quality.",
                "Find \"A Thousand & One Nights\" (1969) — Details shows the collection "
                "\"ARABIAN 1001 NIGHTS\"."),
)
