"""What's New entry: log stream-ID reuse when it hits content the user engaged
with. Diagnostic only — detects and logs when a provider recycles a stream_id
for different content on a channel the user favorited/hid/rated/queued/played,
so the evidence survives instead of being silently overwritten by the next
refresh. Changes no behaviour: no favorite/queue/rating is moved, dropped, or
re-pointed."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=313,
    title="Stream-ID reuse on engaged content is now logged",
    items=(
        "A channel's identity is provider_id + the provider's numeric stream_id. "
        "When a different account on the same Xtream panel reuses those same "
        "stream_ids for different titles, a refresh keeps your favorite / hidden "
        "/ suppressed / played / queued / rated state on the id but silently "
        "swaps in the new provider's content underneath it — so a favorite can "
        "quietly point at a different movie after a refresh, with nothing "
        "recording that it happened.",
        "Every refresh now snapshots the titles of your engaged channels before "
        "the upsert and compares them after. Any engaged channel whose title "
        "changed logs a WARNING (grep for \"STREAM-ID REUSE\" in "
        "~/.config/metatv/logs/metatv.log) naming the channel id and both the "
        "old and new titles, so the evidence is recoverable instead of getting "
        "overwritten by the next refresh.",
        "This is detection only — nothing about favorites, the watch queue, "
        "ratings, or history changes. Deciding what to DO when this fires "
        "(e.g. clearing the stale user state) is a separate, deliberate change.",
    ),
    version="0.30.0",
    date="2026-08-16",
    test_steps=(
        "Refresh an ordinary source (Sources → a provider → Refresh) and check "
        "~/.config/metatv/logs/metatv.log afterward — it should contain NO "
        "\"STREAM-ID REUSE\" lines for a normal refresh (occasional provider "
        "re-titles of un-engaged channels stay silent by design).",
        "Favorite a channel, then (in a test DB or via a controlled scenario) "
        "change that same channel row's name and re-run a refresh — the log "
        "now contains a \"STREAM-ID REUSE\" WARNING line naming the channel id "
        "and showing both the old and new titles.",
    ),
)
