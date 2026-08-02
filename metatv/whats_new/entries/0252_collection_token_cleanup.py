"""What's New entry for the redundant-collection-token cleanup."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=252,
    title="Collection chip no longer repeats what's already on the row",
    items=(
        "The collection chip (line 2 of a list row, e.g. \"APPLE+ KIDS\") no "
        "longer repeats a quality tier, media type, or multi/sub marker the "
        "row already shows via its own quality chip, media-type icon, or "
        "subtitle-marker chip — e.g. \"MULTISUB SERIES 4K\" now renders no "
        "chip at all (every token was a duplicate) and \"|MULTI| APPLE+ "
        "KIDS\" renders as just \"APPLE+ KIDS\".",
        "A trailing quality or subtitle/dub/multi-track word is also peeled "
        "off a real collection name (looping through more than one, e.g. "
        "\"FILMOVI 4K UHD\" -> \"FILMOVI\", \"HINDI SUBS\" -> \"HINDI\") — "
        "even when the rest of the name is kept.",
        "A media-type word (MOVIES, FILMS, SERIES, …) is never peeled off "
        "the edge of an otherwise-real name — \"TAMIL MOVIES\", \"NORDIC "
        "FILMS\", and \"MOVIES 2018-2021\" are left exactly as they are, "
        "since the media word is part of the collection's actual name "
        "there, not a duplicate tag. It's only removed as part of a chip "
        "that's entirely redundant noise (like \"MULTISUB SERIES 4K\") or a "
        "leading bracket marker that's entirely noise.",
        "Existing channels are backfilled automatically on next launch; new "
        "channels get the clean value immediately at ingestion.",
    ),
    version="0.23.0",
    date="2026-08-03",
    test_steps=(
        "Find a list row whose collection chip previously showed a quality "
        "tier that also appears on the row's own quality chip (e.g. a \"4K\" "
        "collection value on a channel whose quality chip is also \"4K\") — "
        "the collection chip no longer shows the redundant \"4K\".",
        "Find (or check) a row whose collection value was purely redundant "
        "tokens (quality + media-type + multi/sub, nothing else) — line 2 "
        "shows no collection chip at all, with no stray separator or empty "
        "box where it used to be.",
        "Find a row whose collection value starts with a bracketed marker "
        "like \"|MULTI|\" — the chip now shows just the remaining text after "
        "the marker (e.g. \"APPLE+ KIDS\"), not the bracket.",
        "Find a row whose collection value is a real name with a trailing "
        "quality/sub/dub word (e.g. something like \"HINDI SUBS\" or "
        "\"FILMOVI 4K UHD\") — the trailing noise word(s) are gone, the real "
        "name stays.",
        "Find a row whose collection name legitimately contains a media-type "
        "word as part of the name (e.g. something like \"TAMIL MOVIES\" or "
        "\"NORDIC FILMS\") — the full name is still shown unchanged.",
    ),
)
