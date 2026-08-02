"""What's New entry for the background metadata enrichment queue (roadmap)."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=249,
    title="Background Metadata Enrichment",
    items=(
        "A new Tools → Background Metadata Enrichment view fills in missing or "
        "stale posters, plot, cast, and ratings across your whole library — "
        "favorited, queued, and recently played titles first — with a progress "
        "bar and Start/Pause/Resume/Cancel controls.",
        "It's safe to pause or quit mid-pass: it always resumes from where it "
        "left off rather than recrawling. A channel whose fetch keeps failing "
        "is counted and shown with a reason instead of being retried forever.",
        "Off by default — enable automatic background enrichment on launch via "
        "Settings, or just run a pass manually any time from the Tools menu.",
    ),
    version="0.23.0",
    date="2026-08-03",
    test_steps=(
        "Open Tools → Background Metadata Enrichment and click Start — the "
        "status flips to Running, the progress bar fills in, and 'Now "
        "enriching: <title>' updates as titles are processed.",
        "Click Pause mid-run — the state flips to Paused and the progress bar "
        "stops advancing; click Resume (same button) — it continues from the "
        "same done/total count rather than restarting from zero.",
        "Click Cancel while running — the state flips to Cancelled and no "
        "further titles are processed.",
        "Leave a source with no metadata providers registered (or disconnect "
        "network) and start a pass — failed titles appear under 'Recent "
        "Failures' with a reason, and the pass keeps going rather than "
        "stopping.",
        "Close and relaunch the app mid-pass, then reopen the view and click "
        "Start again — already-enriched titles are not re-fetched.",
    ),
)
