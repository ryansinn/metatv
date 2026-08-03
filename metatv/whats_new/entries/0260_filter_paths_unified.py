"""What's New entry for the unified visibility/exclusion chokepoint."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=260,
    title="Recommendations, Discover, and filter counts now agree with Global Exclusions",
    items=(
        "Recommendations, Discover shelves, and the filter panel's facet "
        "counts now all read the SAME Global Exclusions logic — previously "
        "each had its own slightly different copy, which is why "
        "Recommendations could keep surfacing content the Global Exclusions "
        "screen said was hidden.",
        "Fixed a real gap in that shared logic: a title with no detected "
        "language tag but an excluded region tag is now hidden everywhere "
        "(it used to slip through on Discover and Recommendations even "
        "though the channel list already hid it) — a title WITH an "
        "un-excluded language tag is still shown even if its region tag "
        "happens to be excluded ('language wins over region').",
        "The filter panel's facet value counts (the numbers next to each "
        "genre/region/collection option) now match what the corresponding "
        "filtered list actually shows — the counts used to ignore the "
        "language/category/content-type exclusions and only honor the "
        "keyword exclusion, so a count could look nonzero for an option "
        "that returned nothing.",
        "Hidden and expired sources remain an absolute gate everywhere — "
        "this change never reveals anything from a disabled source, it only "
        "makes the existing exclusion rules consistent.",
    ),
    version="0.24.0",
    date="2026-08-02",
    test_steps=(
        "Open Settings → Global Exclusions and exclude a region/category that "
        "some of your titles carry ONLY as a region tag (no language prefix) "
        "— those titles disappear from the channel list as before.",
        "Open 🧭 Discover and 💡 Recommendations — titles matching that same "
        "excluded region (with no language prefix) no longer appear on any "
        "shelf or in the recommended list, matching the channel list.",
        "A title that HAS a language prefix you have NOT excluded still "
        "appears on Discover/Recommendations even if its region tag happens "
        "to be excluded — excluding a region never hides a title whose own "
        "language tag is fine.",
        "Open the channel-list filter panel — a facet's shown count (e.g. a "
        "genre or collection value) now matches the number of results you "
        "actually get when you filter to just that value.",
        "Disable a source (Settings → Sources → toggle off) — its content "
        "still never appears or counts anywhere across the channel list, "
        "Discover, Recommendations, or the filter panel.",
    ),
)
