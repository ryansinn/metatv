from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=92,
    version="0.9.0",
    date="2026-06-28",
    title="EPG Browse: filter sticks, clean channel names, standard clear, source detail",
    items=(
        "The EPG → Browse search filter no longer reverts to ALL content: a slow "
        "background schedule load can no longer land after your search and wipe it — "
        "Browse always shows results for the text currently in the search box.",
        "Browse channel names now show the clean detected title (region/category "
        "prefixes and quality tags like 'HD' stripped) instead of the raw provider name.",
        "Browse now respects your global Exclusions and disabled/expired sources — "
        "channels from hidden sources no longer leak into the schedule.",
        "The Browse search box uses the standard clear (×) button, matching every "
        "other search field in the app.",
        "The EPG header now names each EPG source and shows freshness, flagging stale "
        "guides (e.g. '2 sources · 1 stale', with per-source detail on hover) instead "
        "of a bare '2 sources'.",
    ),
    test_steps=(
        "EPG → Browse: type a query (e.g. 'news') and wait a few seconds. Confirm the "
        "list stays filtered to matches and does NOT flash back to the full schedule.",
        "EPG → Browse: confirm channel names in the Channel column are clean (no 'US|' "
        "prefix, no trailing 'HD') — e.g. 'ESPN' rather than 'US| ESPN HD'.",
        "Disable a source (or have an expired one), then EPG → Browse: confirm none of "
        "that source's channels appear in the schedule.",
        "EPG → Browse: confirm the search box shows a × clear button when it has text, "
        "and clicking it clears the search and restores the full schedule.",
        "With 2+ EPG sources configured, open EPG and read the header status: confirm "
        "it shows the source count plus any stale count, and hovering reveals each "
        "source name with its freshness (and '(stale)' on out-of-date guides).",
    ),
    addresses=(
        "flagged:454e01bf-dc9c-48d4-abf9-61c8b8438655",
        "flagged:8f941952-b00b-47d7-85c2-c04ae3172ae2",
        "flagged:fd315e75-d54d-4a04-a017-1db032d40038",
        "flagged:c3e1aaf3-ccfb-45db-8d28-5c5c7181e7da",
    ),
)
