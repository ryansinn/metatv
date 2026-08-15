"""What's New entry: a successful stream failover now sticks to the item
instead of being thrown away the moment playback starts."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=306,
    title="A successful failover now sticks",
    items=(
        "When the primary host for a channel or movie is down, playback "
        "already fails over to a working alternate host — but the working "
        "URL was thrown away the instant playback started. The stored URL "
        "still pointed at the dead host, so every future play of that same "
        "item re-started from the dead host, waited out the same validation "
        "timeout, and failed over again — forever.",
        "The working URL is now written back to that item's own row the "
        "moment a failover succeeds, so the next play starts from the host "
        "that's known to work. Only the played item is touched; other "
        "channels on the same source are unaffected.",
    ),
    version="0.27.1",
    date="2026-08-15",
    test_steps=(
        "Play a channel/movie whose primary host is unreachable but whose "
        "source has a working alternate URL configured — playback starts "
        "via the alternate host after the usual failover.",
        "Play that same item again — it starts immediately from the "
        "alternate host, without re-waiting on the dead primary host's "
        "validation timeout.",
    ),
)
