"""What's New entry: alternate-host attempts now record how long they took,
so the ranker's latency term actually has data to rank on."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=307,
    title="Host ranking now sees real latency",
    items=(
        "When a source has multiple alternate hosts, ranking picks the best "
        "one to try first using health, cooldown, and latency. But latency "
        "was never actually recorded — every attempt stored a blank value, "
        "so a chronically slow-but-technically-working host could sit at "
        "the front of the line forever.",
        "Small, size-comparable requests (server info, series/movie info "
        "lookups, category lists, and — most importantly — the live "
        "failover check when a stream fails to play) now time each "
        "attempt and record it, so a slow host actually loses ranking "
        "priority to a faster one. The full-catalog refresh is left "
        "unrecorded on purpose: its time is dominated by how much content "
        "there is, not by how responsive the host is, so mixing it in "
        "would make the median meaningless.",
    ),
    version="0.28.0",
    date="2026-08-15",
    test_steps=(
        "Configure a source with two alternate hosts, one noticeably "
        "slower than the other — after a few plays/refreshes, the faster "
        "host should rank first (check the source's connection/log "
        "details for latency values).",
        "Play a channel whose primary host is down but has a working "
        "alternate — failover still succeeds and playback starts "
        "normally.",
        "Trigger a library refresh — behavior is unchanged (still "
        "completes normally); refresh time is not affected by the "
        "latency change.",
    ),
)
