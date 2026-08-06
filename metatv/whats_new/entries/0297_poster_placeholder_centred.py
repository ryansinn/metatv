"""What's New entry: the "No poster available" message was pinned to the left
border of an otherwise empty card."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=297,
    title="\"No poster available\" is centred in its frame",
    items=(
        "When a title has no artwork, the details pane says so on an empty "
        "card — and that message sat hard against the card's left border, "
        "with the rest of a tall empty frame stretching away to the right.",
        "It was inheriting an alignment meant for something else. Poster ART "
        "is deliberately left-aligned so the slim action rail floating over "
        "the card's left edge always overlays the picture rather than the "
        "margin. The placeholder text is not a picture being positioned in a "
        "frame, it is a message about an empty one, so it now centres.",
        "The poster label works this out from whether it is currently holding "
        "an image, so art still hugs the left edge exactly as before and no "
        "call site has to remember which case it is in.",
    ),
    version="0.27.0",
    date="2026-08-04",
    test_steps=(
        "Find a title with no poster (Discover or a live channel with no "
        "logo) and open its details. \"No poster available\" is centred both "
        "horizontally and vertically in the empty card.",
        "Click a title that DOES have a poster. The artwork still sits against "
        "the left edge of the card, with the action rail overlaying the "
        "picture and the padding on the right.",
        "Click back and forth between a title with a poster and one without — "
        "each renders correctly every time, not just on first load.",
    ),
)
