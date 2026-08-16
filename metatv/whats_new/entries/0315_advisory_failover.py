"""What's New entry: an HTTP 401/403/511 from one alternate host no longer
aborts the whole failover sweep — those codes are advisory (auth/gating),
not proof the content is gone, so the next host still gets a chance."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=315,
    title="A blocked host no longer stops the search for a working one",
    items=(
        "When a source has several alternate hosts and the first one "
        "returned an HTTP 401, 403, or 511 (common for shared-account caps "
        "or geo-gating), the app gave up immediately instead of trying the "
        "other 18 hosts it had just listed — a real log showed exactly this: "
        "19 hosts to try, one 403, then \"Episode stream unavailable\" three "
        "seconds later. Those codes are host-level and advisory — mpv often "
        "negotiates playback fine even after a pre-flight check saw one — so "
        "the sweep now keeps going past them and only stops for a genuine "
        "content error (e.g. \"This channel is not available\").",
        "The very first attempt on every play (the channel or episode's "
        "primary URL) is now recorded through the same host-reliability "
        "tracker as every alternate — previously a permanently dead primary "
        "host kept a perfect health score forever because its own failure "
        "was never counted.",
        "Episodes now get the same \"Play Anyway\" option channels already "
        "had when a stream fails pre-flight with one of these advisory "
        "codes, and an advisory failure is no longer recorded as a confirmed "
        "dead stream.",
    ),
    version="0.31.0",
    date="2026-08-16",
    test_steps=(
        "Play an episode or channel from a source with multiple configured "
        "alternate hosts where the first host returns HTTP 403 (or simulate "
        "by temporarily blocking one host). The app should continue trying "
        "the remaining hosts instead of failing after the first one.",
        "Play a stream whose pre-flight check fails with HTTP 401, 403, or "
        "511 on every host. The resulting \"Stream Unavailable\" notification "
        "should offer a \"Play Anyway\" action (for both channels and "
        "episodes), and mpv should still be given the chance to play it.",
    ),
)
