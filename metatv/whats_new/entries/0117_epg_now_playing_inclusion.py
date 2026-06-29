from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=117,
    version="0.9.0",
    date="2026-06-28",
    title="EPG Browse: 'now' now shows what's ON right now (mid-show), not just what's next",
    items=(
        "Browse opening at 'Now' now includes shows that are CURRENTLY AIRING — a "
        "movie two hours into a four-hour run is on right now, so it appears "
        "(mid-progress, at its real start time) instead of vanishing because it "
        "started in the past. The list is currently-airing shows first, then upcoming.",
        "The timeline scrubber's default left edge is the start of the OLDEST show "
        "that is on right now, so you can scrub back to see the beginning of "
        "everything currently airing — but no further by default.",
        "The old 'Hide EPG older than' setting is now 'Allow browsing back' "
        "(Settings → Metadata & API Keys → EPG): leave it at 0 to stop at the oldest "
        "currently-airing show, or raise it to scrub further into the recent past.",
    ),
    test_steps=(
        "Open EPG → Browse with the handle at 'Now'. Confirm the top rows are shows "
        "that started earlier but are still on (their Time column shows a past start), "
        "followed by upcoming shows — not an empty gap until the next show starts.",
        "Confirm a show that already finished (stop time in the past) does NOT appear "
        "anywhere in the list at the 'Now' position.",
        "Drag the scrubber handle fully left. Confirm the left edge stops at the start "
        "of the oldest show currently airing (you can see its beginning) and does not "
        "go further back.",
        "Open Settings → Metadata & API Keys → EPG, set 'Allow browsing back' to e.g. "
        "6 h, click OK, return to Browse. Confirm the scrubber's left edge now reaches "
        "further into the past (up to ~6 hours back, bounded by available guide data).",
    ),
)
