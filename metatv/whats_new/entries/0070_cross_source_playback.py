from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=70,
    version="0.9.0",
    date="2026-06-24",
    title="Cross-source playback resilience",
    items=(
        "Stream failures now offer 'Play Anyway' — bypass the pre-flight check and let mpv decide. "
        "Auth/gating codes (HTTP 401, 403, 511) like shared-account caps are marked advisory rather "
        "than hard failures, so you are never blocked from attempting playback.",
        "Automatic cross-source failover: when all URLs for a channel fail, MetaTV silently tries "
        "the same content (by content_key) on your other active sources before showing an error. "
        "Only one failure toast is shown regardless of how many URLs were attempted.",
        "Failure toasts surface sibling alternatives: active siblings get 'Try X' action buttons; "
        "inactive-source siblings get 'Reactivate & play' so you can opt in without visiting settings.",
        "Details pane 'Also available as' chips are now source pickers: each chip shows the source "
        "icon, region/language prefix, and quality tier. Click to play that source's variant directly. "
        "Inactive-source chips are dimmed with a 'Reactivate & play' right-click option.",
    ),
    test_steps=(
        "Simulate a stream failure (e.g. disconnect network briefly) — the failure toast shows "
        "'Play Anyway' as the first action. Click it; mpv attempts the original URL directly.",
        "With two active sources that share the same content (same content_key), disable the primary "
        "source's stream URL or cap it (HTTP 511) — MetaTV should silently switch to the working "
        "source and play without showing an error toast.",
        "Open the details pane for a channel that exists on multiple sources. The 'Also available as' "
        "section shows chips with source icons + region/quality. Click a chip — it plays that source's "
        "variant (with Split Streams on, in its own window).",
        "An inactive-source chip appears dimmed. Right-clicking offers 'Reactivate source & play'. "
        "Clicking it reactivates the provider and begins playback.",
    ),
)
