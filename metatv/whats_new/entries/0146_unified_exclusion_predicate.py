from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=146,
    version="0.10.0",
    date="2026-07-22",
    title="Every surface now reads Global Exclusions the same way",
    items=(
        "The \"language wins over region\" rule (a channel is hidden by its "
        "prefix; a channel with no prefix falls back to its region) is now the "
        "single shared predicate behind the channel list, the details \"Other "
        "Versions\" panel, EPG On Now, and the facet/recipe/tag counts. Before "
        "this, those surfaces each interpreted your exclusions slightly "
        "differently, so the same channel could be hidden in one place and shown "
        "in another.",
        "Two surfaces now hide a bit MORE, matching the channel list: \"Other "
        "Versions\" greys out prefix-less variants filed under an excluded region, "
        "and EPG On Now hides prefix-less channels from an excluded region — while "
        "still keeping any variant whose language prefix you did not exclude.",
        "One surface now hides a bit LESS, matching the channel list: facet, "
        "recipe, and tag-cloud counts stop over-hiding language-tagged content "
        "filed under an excluded region, so their numbers agree with what the "
        "channel list actually shows.",
    ),
    test_steps=(
        "Exclude a region-ish code (e.g. India / IN) in Global Exclusions, open a "
        "movie's details, and check Other Versions: a prefix-less variant filed "
        "under IN is now greyed out (filtered), while an EN-prefixed variant filed "
        "under IN still appears normally.",
        "With IN excluded, open EPG → On Now: prefix-less channels whose region is "
        "IN are hidden, but channels carrying an explicit un-excluded language "
        "prefix (e.g. EN) still appear.",
        "With IN excluded, compare a language-tagged genre/recipe count to the "
        "channel list for the same filter: the facet/recipe count now matches the "
        "channel list (EN rows filed under IN are counted, not silently dropped).",
    ),
)
