from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=231,
    version="0.20.0",
    date="2026-08-02",
    title="Global Exclusions now offer region tokens that affect prefix-null channels",
    items=(
        "A channel with no language prefix falls back to its region token for "
        "exclusion evaluation (e.g. a title with no [EN] marker but region (FR) "
        "is hidden when FR is excluded). Previously, region tokens were never "
        "offered as checkboxes in the Global Exclusions dialog, leaving users "
        "unable to see or toggle channels hidden by region. The fix surfaces "
        "all region-only tokens (codes that appear on prefix-null channels) in "
        "the dialog with a tooltip: 'Region token — applies to channels that "
        "carry no language prefix'. Region codes that also exist as prefixes "
        "show the merged count.",
    ),
    test_steps=(
        "In Global Exclusions, verify a region token (e.g. FR applied to a "
        "title with no prefix but region (FR)) appears with a tooltip. Exclude "
        "it and confirm the title vanishes from Discover/Recommendations; "
        "uncheck it and confirm it reappears. Verify a region code that is also "
        "a prefix (e.g. FR both [FR]-prefixed and (FR)-regional) shows the "
        "combined count.",
    ),
)
