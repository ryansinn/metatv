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
        "A collection whose name merely contains a quality/media/sub word — "
        "like \"SERIES MANIA\" — is left untouched; only a chip that is "
        "ENTIRELY redundant noise, or a leading bracket marker that's "
        "entirely noise, gets cleaned up.",
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
        "Find a row whose collection name legitimately contains a word like "
        "\"SERIES\" as part of a real name (not just a redundant tag) — the "
        "full name is still shown unchanged.",
    ),
)
