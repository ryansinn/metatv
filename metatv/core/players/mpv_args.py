"""The stream-access rules (:mod:`metatv.core.stream_access`) as mpv flags.

The player and the stream-details probe both launch mpv on a stream URL, and
both start the command line with :func:`stream_args`.
"""

from __future__ import annotations

from metatv.core.stream_access import PLAYBACK, StreamAccess, ffmpeg_reconnect_options


def _reconnect_flag(policy: StreamAccess) -> str | None:
    options = ffmpeg_reconnect_options(policy)
    if not options:
        return None
    return "--stream-lavf-o=" + ",".join(f"{k}={v}" for k, v in options.items())


def _read_timeout_flag(policy: StreamAccess) -> str:
    # 0 = FFmpeg's default: no read timeout. mpv's own default is 60s, so
    # "never" has to be said explicitly.
    seconds = policy.read_timeout_s
    return f"--network-timeout={0 if seconds is None else f'{seconds:g}'}"


RECONNECT_FLAG = _reconnect_flag(PLAYBACK)
NO_READ_TIMEOUT_FLAG = _read_timeout_flag(PLAYBACK)


def stream_args(policy: StreamAccess = PLAYBACK) -> list[str]:
    """User-Agent, reconnect and read-timeout flags — in that order.

    The order matters: user-supplied args come after these, so mpv's last-value
    rule lets the user override any of them.
    """
    reconnect = _reconnect_flag(policy)
    return [f"--user-agent={policy.user_agent}",
            *([reconnect] if reconnect else []),
            _read_timeout_flag(policy)]
