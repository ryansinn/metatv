"""What's New entry: episodes now fail over to alternate hosts, and a
successful failover sticks to the episode's row (mirrors #306 for channels)."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=308,
    title="Episodes now fail over to alternate hosts",
    items=(
        "Channels and movies already fail over to a source's alternate "
        "hosts when the primary host is down — episodes did not; a dead "
        "episode host meant the episode simply wouldn't play, even when "
        "the same source had a working alternate URL. Episode playback "
        "now routes through the same failover chokepoint the channel path "
        "uses, so an episode gets exactly the same alternate-host retries.",
        "As with the channel fix, a successful failover is written back to "
        "that episode's own row, so the next play of the same episode "
        "starts from the host that's known to work instead of re-waiting "
        "on the dead primary host's validation timeout every time.",
    ),
    version="0.27.1",
    date="2026-08-15",
    test_steps=(
        "Play an episode whose primary host is unreachable but whose "
        "source has a working alternate URL configured — playback starts "
        "via the alternate host instead of failing outright.",
        "Play that same episode again — it starts immediately from the "
        "alternate host, without re-waiting on the dead primary host.",
        "Play an episode whose source has no working host at all — the "
        "existing 'Stream Unavailable' notification still appears, "
        "referencing the original URL.",
    ),
)
