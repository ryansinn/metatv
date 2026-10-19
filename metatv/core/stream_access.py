"""How MetaTV opens a stream — the rules, independent of which program obeys them.

mpv plays, the stream-details probe asks mpv, and the signal check runs ffmpeg.
They must agree on who they say they are and how they treat a dropped or stalled
connection, or one says "dead" about a stream another plays. Each tool spells
these rules in its own flags (``players/mpv_args.py`` for mpv, ``stream_probe``
for the ffmpeg CLI); the rules themselves live here, once.

The User-Agent comes from :mod:`metatv.core.http_headers`, which the
``requests``-based paths (validation, diagnostics, downloads, recordings) send
directly; those paths run their own reconnect loops and use only the headers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from metatv.core.http_headers import stream_user_agent

# Always-on reconnect for transient drops (PLAY-12: the owner's one-connection panel holds a new
# connection while counting the previous stream — #635 measured 14-26s, up to ~40s on 2026-09-07).
# reconnect_on_http_error=5xx covers a 5xx reply; reconnect_on_network_error covers no reply at
# all. 4xx excluded — told no must still fail fast (ConnectionAccountant.PROVIDER_COOLDOWN_S).
# ffmpeg's backoff (delay=0, then delay=1+2*delay per failure, stopping once the next delay exceeds
# reconnect_delay_max) measured 2026-09-11 against an always-5xx server: max=8 -> +0,+0,+1,+4,+11s
# (11s, PLAY-10's old value — short); max=30 -> 26s (still short of the panel's ~40s); max=60 ->
# +0,+0,+1,+4,+11,+26,+57s (57s — covers it).
# NO socket read timeout (PLAY-18): on the owner's source a stalled connection that resumes beats
# a reconnect — PLAY-14's timeout=20s turned every stall into refused reconnects ("it only plays
# the first 2 minutes"). mpv's own --network-timeout (default 60s) is a read timeout too, and on a
# one-connection source worse: ffmpeg reconnects while STILL holding the stalled socket, the source
# counts two, and every reconnect gets 509 until mpv is killed (PLAY-20, reproduced 2026-09-29).
RECONNECT_DELAY_MAX_S = 60


@dataclass(frozen=True)
class StreamAccess:
    """One set of rules for opening a stream.

    Attributes:
        reconnect_delay_max_s: ffmpeg's ``reconnect_delay_max``; None means
            never reconnect.
        read_timeout_s: Give up on a connection that stalls this long; None
            means wait for it to resume.
        user_agent: The User-Agent to send.
    """

    reconnect_delay_max_s: int | None
    read_timeout_s: float | None
    user_agent: str = field(default_factory=stream_user_agent)


#: Playback, and anything that must see a stream the way playback does.
PLAYBACK = StreamAccess(reconnect_delay_max_s=RECONNECT_DELAY_MAX_S, read_timeout_s=None)

#: A seconds-long health sample: fail fast instead. Without the read timeout a
#: hung connection sits until the outer timeout, turning a 1.2 s "dead" into 17 s.
PROBE = StreamAccess(reconnect_delay_max_s=None, read_timeout_s=8.0)


def ffmpeg_reconnect_options(policy: StreamAccess) -> dict[str, str]:
    """The ffmpeg protocol options *policy*'s reconnect rule needs, in order.

    Both mpv (through ``--stream-lavf-o``) and the ffmpeg CLI hand these to the
    same libavformat HTTP protocol, so the option names are shared.
    """
    if policy.reconnect_delay_max_s is None:
        return {}
    return {
        "reconnect": "1",
        "reconnect_streamed": "1",
        "reconnect_delay_max": str(policy.reconnect_delay_max_s),
        "reconnect_on_http_error": "5xx",
        "reconnect_on_network_error": "1",
    }
