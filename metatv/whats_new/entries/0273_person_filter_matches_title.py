"""What's New entry: filtering by a person now finds titles that name that
person in the filename, matching what search already did."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=273,
    title="Filtering by an actor now finds films that name them in the title",
    items=(
        "Searching \"Nicolas Cage\" found \"EN - Adaptation. 4K (2002) NICOLAS "
        "CAGE\", but filtering by Nicolas Cage did not. Same name, same title, "
        "opposite answers.",
        "Sources often append the lead actor to a filename, and MetaTV tidies "
        "that out of the displayed title — so the name is right there on the "
        "listing while being invisible to the filter. Since most titles have no "
        "cast information downloaded at all, the filter was usually empty "
        "rather than usually right.",
        "A person filter now also matches the title itself, so it agrees with "
        "search.",
        "Live channels are deliberately left out of this: a channel called "
        "\"Tom Hanks Channel\" is a coincidence of naming, not a credit, and it "
        "has no business showing up in a filmography.",
    ),
    version="0.26.0",
    date="2026-08-03",
    test_steps=(
        "Find a movie whose name ends with an actor's name (e.g. \"… (2002) "
        "NICOLAS CAGE\"). In the details pane, click that actor if listed, or "
        "type the actor's name in search to confirm the title appears.",
        "Now apply the person filter for that actor — the film appears, where "
        "before the list came back empty.",
        "Confirm the guard: if you have a LIVE channel named after a person "
        "(e.g. a 24/7 channel with a celebrity's name), filtering by that "
        "person does NOT return the live channel.",
        "Confirm nothing regressed for enriched titles: filter by an actor "
        "whose film has downloaded cast data — it still appears.",
    ),
)
