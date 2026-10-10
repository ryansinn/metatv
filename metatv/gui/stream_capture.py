"""Capture what a playing stream actually contains (PLAYED-1).

Driven by the playback health poll: once a play has really progressed, read
mpv's track list and video parameters and store them for the channel; read
again after :data:`CAPTURE_AGAIN_AFTER_S`, when mpv's bitrate estimate has
settled. The mpv read and the write run off the UI thread through the host's
``_run_query`` seam; the details pane is then refreshed through
``_load_stream_info`` — the same path a future "Get details" probe will use
after storing its own record with ``source="probe"``.
"""
from __future__ import annotations

import time
from typing import Any

from loguru import logger

from metatv.core.stream_info import MPV_PROPS, merge_bitrate, parse_mpv

#: Second read, once mpv's running bitrate estimate is meaningful.
CAPTURE_AGAIN_AFTER_S = 30.0


def on_health_tick(host: Any, key: "str | None") -> None:
    """Call on every health tick that reports a loaded file.

    Captures at most twice per play: at first progress, and again after
    :data:`CAPTURE_AGAIN_AFTER_S`. A play that has not progressed (yet) resets
    the window's state, so the next play of the same channel measures again.
    """
    state: dict = host.__dict__.setdefault("_stream_capture", {})
    if not host.__dict__.get("_health_ever_progressed"):
        state.pop(key, None)
        return
    playing = {**(host.__dict__.get("_playing_channels") or {}),
               **(host.__dict__.get("_playing_episodes") or {})}
    channel_id = playing.get(key)
    if channel_id is None and len(playing) == 1:
        channel_id = next(iter(playing.values()))    # shared window: null key
    if not channel_id:
        return
    st = state.get(key)
    if st is None or st["channel_id"] != channel_id:
        st = state[key] = {"channel_id": channel_id, "first_at": time.monotonic(), "reads": 0}
    if st["reads"] == 0 or (
            st["reads"] == 1 and time.monotonic() - st["first_at"] >= CAPTURE_AGAIN_AFTER_S):
        st["reads"] += 1
        _capture(host, key, channel_id)


def _capture(host: Any, key: "str | None", channel_id: str) -> None:
    player_manager = host.player_manager

    def query(repos) -> "str | None":
        info = parse_mpv(player_manager.get_properties(list(MPV_PROPS), key=key))
        if info is None:
            return None
        prev = repos.stream_info.get(channel_id)
        if prev and prev["source"] == "played":
            info = merge_bitrate(prev["info"], info)
        repos.stream_info.upsert(channel_id, info, source="played")
        return channel_id

    host._run_query(
        query,
        lambda stored: host._load_stream_info(stored) if stored else None,
        commit=True,
        on_error=lambda e: logger.debug("stream capture failed for {}: {}", channel_id, e),
    )
