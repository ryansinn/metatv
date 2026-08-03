"""What's New entry for Discover Collection shelves."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=256,
    title="Collections now appear as Discover shelves",
    items=(
        "Every provider category MetaTV already groups into a \"Collection\" "
        "(e.g. \"Apple+ Kids\", \"Hindu Subs\") now gets its own shelf on the "
        "🧭 Discover screen, right alongside Genre and Decade shelves — no "
        "re-scan needed, since the collection name was already computed when "
        "the channel was ingested.",
        "A collection needs at least 2 members to earn a shelf — a one-off "
        "category isn't worth cluttering Discover with.",
        "Collection shelves respect the same Global Exclusions, Adult filter, "
        "and disabled/expired source rules as every other shelf — content "
        "from a hidden source never appears in a shelf or counts toward its "
        "total.",
        "Shelves are ordered by member count (most first), then "
        "alphabetically, so the shelf order stays stable across reloads.",
    ),
    version="0.24.0",
    date="2026-08-02",
    test_steps=(
        "Open 🧭 Discover with a library that has provider categories like "
        "\"Apple+ Kids\" or similar — new shelves titled with those collection "
        "names appear alongside the Genre/Decade shelves, collapsed by "
        "default like other collapsed shelves.",
        "Expand a collection shelf — it fetches and shows cards only from "
        "that collection, and reloading Discover doesn't reorder the shelf "
        "relative to other collection shelves.",
        "Disable (or let expire) a source that contributes to a collection "
        "shared with another active source — that shelf's card count drops "
        "to just the still-active source's items, and a collection that "
        "exists ONLY on the disabled source disappears entirely.",
        "Click 'See All' on a collection shelf — the browse grid title shows "
        "the clean collection name, not the raw 'collection:' key.",
    ),
)
