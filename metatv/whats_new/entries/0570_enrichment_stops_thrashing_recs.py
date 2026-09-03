from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=570,
    version="0.89.0",
    date="2026-09-03",
    title="Recommendations stay responsive while TMDb enrichment runs in the background",
    items=(
        "TMDb enrichment lands a batch of newly-collapsed titles roughly every "
        "5 seconds during an active run, and each batch was re-running the "
        "app's full canonical refresh (Recommended weights + scoring, "
        "Preferences, Discover, filter stats, the channel list) immediately — "
        "so a multi-minute enrichment pass turned into a five-second stall "
        "loop the whole time.",
        "Refreshes now coalesce: they wait for enrichment to go quiet for a "
        "minute, fire anyway after 5 minutes if it never goes quiet, or fire "
        "immediately the moment enrichment finishes draining. The new titles "
        "still appear — just batched together instead of thrashing the UI.",
        "Manual actions (hide, rate, refresh a source, edit a provider) are "
        "untouched and still refresh instantly.",
    ),
    test_steps=(
        "Right after a source refresh, while enrichment is running, scroll "
        "and use Recommended → it stays responsive instead of re-loading "
        "every few seconds; the new merges appear together once enrichment "
        "quiets or finishes.",
        "Hide a channel from Recommendations while enrichment is running → "
        "the list updates immediately, with no wait.",
    ),
)
