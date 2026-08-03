"""What's New entry for the Series Monitor baseline-stability fix (#259)."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=259,
    title="Fixed inflated new-episode counts",
    items=(
        "New-episode counts in Watch Queue's 'Alerts Matched' could grow "
        "without bound and change on almost every app launch, for series "
        "mirrored across more than one source. A hiccup on one source (an "
        "empty or malformed response) was silently recorded as 'this show "
        "now has 0 episodes', so the very next successful check counted the "
        "whole back-catalog as brand new — repeatedly, on every launch. A "
        "flaky source's episode count is never trusted below what was seen "
        "before, and a response with no usable episode data is now skipped "
        "and logged instead of overwriting your count. Any counts already "
        "inflated by this bug are corrected automatically the next time the "
        "app loads your monitored-series list — no other data (favorites, "
        "ratings, history, watch progress) is touched.",
    ),
    version="0.24.0",
    date="2026-08-02",
    test_steps=(
        "Open Watch Queue → 'Alerts Matched' for a series that was previously "
        "showing an inflated/ever-growing 'new episodes' count → the count now "
        "reflects a sane, stable number (no more than the show's real episode "
        "total) after the app has loaded once.",
        "Restart the app a few times with a monitored series present → its "
        "'new episodes' count does not keep climbing between launches unless "
        "episodes genuinely aired.",
        "Mark a monitored series' new episodes as seen (or open the series) → "
        "the badge clears to zero, same as before — this fix does not change "
        "when the badge clears, only how the count is computed.",
    ),
)
