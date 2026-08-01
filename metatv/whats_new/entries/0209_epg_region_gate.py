from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=209,
    version="0.18.0",
    date="2026-08-01",
    title="Smarter EPG matching — region-gated + show-loop channels skipped",
    items=(
        "EPG name-matching (the fallback used when a channel has no exact guide "
        "id) now checks that the channel's region matches the guide feed's "
        "region before accepting a match — an English-region channel can no "
        "longer fuzzy-match a Spanish guide feed by generic name collision "
        "(e.g. two unrelated \"Sports 1\" channels).",
        "The check only applies to name-based fuzzy matching — an exact guide-id "
        "match is never second-guessed — and abstains (matches as before) for "
        "any region it doesn't recognize, so it only removes bad matches, never "
        "blocks good ones.",
        "Show-loop / rotation channels (24/7 movie channels, generic filler "
        "feeds) are now skipped from name-based guide matching entirely — their "
        "titles are too generic to match reliably by name.",
    ),
    test_steps=(
        "Refresh EPG for a provider with channels from multiple regions → "
        "check the log for 'EPG region gate: rejected' entries where a "
        "cross-region name collision would previously have matched wrong.",
        "A channel with a real region (e.g. detected as US/UK) still matches "
        "guide feeds from a compatible region exactly as before.",
        "A '24/7'-style channel no longer picks up an unrelated guide via name "
        "matching, but still keeps an exact guide-id match if the provider "
        "supplies one.",
    ),
)
