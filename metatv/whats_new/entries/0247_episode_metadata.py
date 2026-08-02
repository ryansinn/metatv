"""What's New entry for per-episode plot/air-date/rating surfacing."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=247,
    title="Episode Plot, Air Date & Rating",
    items=(
        "Selecting an episode in a series now shows that EPISODE's own plot, air date, "
        "and rating instead of falling back to the series-level summary — the data was "
        "already being downloaded from your provider, it just wasn't surfaced anywhere. "
        "Existing episodes already in your library are backfilled automatically in the "
        "background — no re-scan or network access needed.",
    ),
    version="0.23.0",
    date="2026-08-03",
    test_steps=(
        (
            "Open a series you've already loaded and click into an episode that has "
            "provider-supplied plot/rating data.",
            "The details pane shows the EPISODE's own plot text (not the series' "
            "summary), plus a '★ X.X of 10' rating line and an 'Aired: YYYY-MM-DD' "
            "line under the episode title.",
        ),
        (
            "Click an episode whose provider data has no rating.",
            "No rating chip is shown (no '★ 0.0 of 10') — the row is simply absent, "
            "matching how an absent series-level rating is hidden elsewhere in the pane.",
        ),
        (
            "Click back to the series root (or a season row).",
            "The episode rating/air-date line disappears along with the episode byline; "
            "the series-level plot and rating (if any) are shown instead.",
        ),
        (
            "Restart the app once after upgrading, with an existing library that has "
            "series/episodes loaded from a prior version.",
            "A background migration backfills plot/air date/rating for previously-loaded "
            "episodes (visible as a brief 'Backfilling episode plot, air date & rating' "
            "step in the migration progress indicator, if one is shown) — no network "
            "activity, and episodes without provider metadata are left untouched.",
        ),
    ),
)
