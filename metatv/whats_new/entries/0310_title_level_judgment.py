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
    ),
    version="0.28.0",
    date="2026-08-15",
    test_steps=(
        "Rate the same title +1 from two different source/language variants (if "
        "available), then open Recommendations — its genre/cast influence reflects "
        "one rated title, not two stacked signals (no directly-visible number, but "
        "recommendations should not feel skewed toward that title's attributes "
        "twice as strongly as a single rating would produce).",
        "Favorite one variant of a title and rate a different variant of the SAME "
        "title — the rating wins; the favorite does not add a second, separate "
        "signal on top of it.",
    ),
)
