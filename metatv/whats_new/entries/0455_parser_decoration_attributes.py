from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=455,
    version="0.57.0",
    date="2026-08-30",
    title="Channel names stop carrying their own labels",
    items=(
        "Providers decorate channel names with tiny raised letters - ESPN NEWS "
        "with a small HD after it - and the app could not read them. They stayed "
        "in the title as decoration, and 3,405 channels ended up with no quality "
        "recorded at all, while the identical channel from another source showed "
        "HD correctly.",
        "Those are now read: 14,597 channels gain a quality chip they always had "
        "in their name, and 17,883 titles get shorter.",
        "A pixel size like 3840P now shows as the quality it means - 4K - rather "
        "than sitting in the title. 1080p reads as FHD, 720p as HD.",
        "HD/RAW written with a slash is two attributes and now reads as two.",
        "A tag like [VIP] was being stored as a LANGUAGE, because any two or "
        "three letters in brackets were assumed to be a country code. Fixed.",
        "Video encodings (H.264, H.265/HEVC) moved out of the quality chip. An "
        "encoding is not a resolution, and using it as one meant 1,534 channels "
        "showed \"HEVC\" where their actual quality should have been.",
        "Accented titles are untouched - the folding is per character, so Ángel "
        "and Amélie survive exactly as they are.",
    ),
    test_steps=(
        "Find a channel whose name had small raised letters after it and confirm "
        "the title is now clean with a quality chip instead.",
        "Confirm a channel named with 3840P or 1080p now shows 4K or FHD.",
        "Confirm titles with accents (Ángel, Amélie) still display correctly.",
        "Confirm an HEVC channel no longer shows HEVC as its quality.",
        "Restart and confirm the one-time re-scan runs and the library still "
        "browses, searches and dedupes normally.",
    ),
)
