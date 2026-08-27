from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=398,
    version="0.52.0",
    date="2026-08-27",
    title="The 'hidden by filters' bar stops disappearing on big result sets",
    items=(
        "The bar that tells you how much a filter is hiding, and lets you "
        "reveal it, vanished entirely when a lot was hidden. It counted by "
        "comparing two lists that are both capped at 5,000 rows - so once both "
        "hit the cap the difference came out as zero, and a zero count hides "
        "the bar.",
        "It now says '= 5,000' when it knows only that at least a page is "
        "hidden, instead of claiming zero. The reveal button stays where you "
        "need it.",
        "The obvious alternative - counting the real total - was tried and "
        "rejected on measurement: it took three seconds on a large library, "
        "which would have undone the channel-list speed-up.",
    ),
    test_steps=(
        "Apply a filter that hides a very large number of titles - a language "
        "or a content-type exclusion across the whole library.",
        "The gold bar must still appear. Before this change it disappeared "
        "once enough was hidden.",
        "Check the count reads with a 'at least' marker rather than a bare "
        "number when the amount hidden is large.",
        "Click the reveal on that segment and confirm the hidden titles "
        "appear.",
        "Apply a filter that hides only a handful and confirm the count is an "
        "exact number with no marker - small cases must stay precise.",
        "Confirm the channel list still loads as fast as before; no counting "
        "query was added to the load path.",
    ),
)
