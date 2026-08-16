"""What's New entry: recommendations now judge a TITLE, not each provider row."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=310,
    title="Recommendations: taste is judged per title, not per provider row",
    items=(
        "The same film or show usually exists as several channel rows — one per "
        "provider/language variant. Rating or favoriting more than one variant used "
        "to multiply that title's weight in your taste profile (genre/actor scores "
        "stacked 2x, 3x...) and could let a single film's cast clear the "
        "actor-corroboration threshold on its own.",
        "Signals are now collapsed to one per title (by the same stored content "
        "identity Browse/Discover already use) before weights are computed, so "
        "rating three language copies of one movie counts as one act of taste — "
        "not three.",
        "Disliking one variant now suppresses every sibling copy of that title from "
        "recommendations, not just the one row you happened to be looking at.",
    ),
    version="0.27.1",
    date="2026-08-15",
    test_steps=(
        "Rate the same title +1 from two different source/language variants (if "
        "available), then open Recommendations — its genre/cast influence reflects "
        "one rated title, not two stacked signals (no directly-visible number, but "
        "recommendations should not feel skewed toward that title's attributes "
        "twice as strongly as a single rating would produce).",
        "Dislike (thumbs-down) one variant of a title that has multiple source "
        "copies — none of that title's other copies should appear in "
        "Recommendations afterward, while unrelated titles keep appearing normally.",
    ),
)
