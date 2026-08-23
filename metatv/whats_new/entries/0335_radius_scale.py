from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=335,
    version="0.41.0",
    date="2026-08-23",
    title="Corners round consistently across the app",
    items=(
        "Fifteen different corner roundings shipped across the interface — "
        "every whole number from 0 to 14, plus one 22. Two of them, 3px and "
        "4px, accounted for two thirds of all uses and are indistinguishable "
        "at any size this app draws.",
        "They now come from four steps, so a chip, a card and an overlay each "
        "round by an amount you can actually tell apart, and the same kind of "
        "thing rounds the same way wherever it appears.",
        "Pill-shaped badges are deliberately untouched. A pill has to be "
        "exactly half its own height, and Qt renders a square — not a rounder "
        "box — the moment a radius goes over that, so those keep their own "
        "measured values rather than being tidied onto the scale.",
    ),
    test_steps=(
        "Open the app and look at the filter chips, the cards in Discover and "
        "the panels in Settings → corners are rounded, none square, none "
        "over-rounded into a lozenge.",
        "Open a poster lightbox (details → Similar titles → ⤢) → the overlay "
        "card, its header and its buttons are all still rounded.",
        "Check the round badges — the Watched tick on a poster, the trail-map "
        "status badges, the genre chips in the lightbox → all still fully "
        "pill-shaped, not squared off.",
        "Switch theme through Midnight, Graphite and Daylight → rounding is "
        "identical in all three (corners are not a palette property).",
        "Open EPG, Recommended, Discover and Recipe in turn → no panel or "
        "chip anywhere has picked up a hard rectangle.",
    ),
)
