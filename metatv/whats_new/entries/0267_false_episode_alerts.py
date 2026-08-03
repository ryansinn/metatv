"""What's New entry for the fabricated new-episode counts: series baselines were
keyed by provider alone, so several listings on one provider overwrote a single
slot and each was measured against the same stale number."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=267,
    title="New-episode alerts were reporting numbers that weren't real",
    items=(
        "Monitored series showed impossible growth — one series reported 132 "
        "new episodes, another 23 — and the numbers climbed on every launch.",
        "A series is tracked across every listing that carries it, but the "
        "remembered episode count was stored per SOURCE rather than per "
        "listing. One source often carries the same show several times over "
        "(different languages, qualities, or duplicate uploads), so each of "
        "those listings wrote into the same slot and each was compared against "
        "whichever count happened to be there — a listing with more episodes "
        "than the one before it looked like brand-new arrivals every time.",
        "Because the total could only ever climb, a safety cap eventually "
        "pinned the figure to the source's entire episode count. That is why "
        "the badge read like a total rather than anything new.",
        "Each listing now remembers its own count, so a second listing of a "
        "show can no longer be mistaken for new episodes of the first. "
        "Genuine new episodes are still detected on any listing, on any "
        "source.",
        "Existing counts produced by this fault are cleared on first launch "
        "rather than corrected, because there is no way to tell how much of "
        "one was real. Any listing whose count cannot be matched to a specific "
        "entry is re-measured quietly on the next check — no alert for a "
        "back-catalogue you have already seen.",
    ),
    version="0.25.0",
    date="2026-08-03",
    test_steps=(
        "Launch the app and open the sidebar's Watch Queue → Alerts Matched. "
        "Any previously inflated counts (e.g. \"+132 eps\") are gone — the "
        "series either shows no badge or a small, plausible number.",
        "Check ~/.config/metatv/logs/ for lines reading \"resetting "
        "unseen_new=… (produced by the provider-keyed baseline collision)\" — "
        "one per affected series, on the first launch only.",
        "Relaunch a second time: those reset lines do NOT appear again, and "
        "the counts stay at zero rather than climbing.",
        "Confirm real detection still works: with a monitored series, wait for "
        "a scheduled check (or use Refresh on its source). A series that has "
        "genuinely gained episodes still reports the gain and names the source "
        "that grew.",
    ),
)
