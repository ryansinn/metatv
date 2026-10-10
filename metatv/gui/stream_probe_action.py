"""The details pane's "Get stream details" button (PLAYED-2).

Measures the channel on screen without playing it: takes the provider's
connection slot through the accountant (never preempting playback — and
cancelling itself if playback preempts it), runs the headless mpv probe off
the UI thread, stores the record with ``source="probe"``, and refreshes the
pane through the same ``_load_stream_info`` path a played capture uses.
"""
from __future__ import annotations

import threading
from typing import Any

from loguru import logger

from metatv.core.stream_details_probe import probe_details
from metatv.core.stream_url_derivation import derive_channel_stream_url

_HOLDER_PREFIX = "details-probe:"


def request_probe(host: Any) -> None:
    """Probe the channel the details pane is showing."""
    pane = host.details_pane
    channel = pane.current_channel
    if channel is None or host.__dict__.get("_details_probe"):
        return
    provider_id = getattr(channel, "provider_id", None)
    holder = _HOLDER_PREFIX + channel.id
    accountant = host.player_manager.connection_accountant
    if accountant is not None and provider_id:
        if not accountant.acquire(provider_id, "probe", holder).granted:
            host.status("That source's connection is in use — stop playback to get "
                        "stream details", level="warn")
            return
        if not host.__dict__.get("_details_probe_listening"):
            accountant.add_preempt_listener(lambda _p, h, _k: _on_preempted(host, h))
            host._details_probe_listening = True

    cancel = threading.Event()
    host._details_probe = {"holder": holder, "cancel": cancel}
    pane.set_probe_running(True)
    host.status(f"Getting stream details for {channel.name}…", ms=0)
    db, channel_id = host.db, channel.id

    def query(repos) -> bool:
        try:
            url = derive_channel_stream_url(db, channel) or getattr(channel, "stream_url", None)
            info = probe_details(url, cancel=cancel) if url else None
        finally:
            if accountant is not None and provider_id:
                accountant.release(provider_id, holder)
        if info:
            repos.stream_info.upsert(channel_id, info, source="probe")
        return bool(info)

    host._run_query(
        query,
        lambda ok: _done(host, channel_id, ok, cancel.is_set()),
        commit=True,
        on_error=lambda e: (logger.warning("stream probe failed for {}: {}", channel_id, e),
                            _done(host, channel_id, False, False)),
    )


def _on_preempted(host: Any, holder_id: str) -> None:
    probe = host.__dict__.get("_details_probe")
    if probe and probe["holder"] == holder_id:
        probe["cancel"].set()              # playback wants the connection: give it back


def _done(host: Any, channel_id: str, ok: bool, cancelled: bool) -> None:
    host._details_probe = None
    host.details_pane.set_probe_running(False)
    if ok:
        host.status("Stream details updated")
        host._load_stream_info(channel_id)
    elif cancelled:
        host.status("Stream check stopped — playback took the connection")
    else:
        host.status("Couldn't read the stream — it may be offline or refusing connections",
                    level="warn")
