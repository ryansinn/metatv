"""Behavioral tests for the Xtream bulk-read timeout (slow-server tolerance).

Background: IPTV Ninja's panel returns standard, valid Xtream JSON, but its server
trickles large catalogs slowly (measured: an 18 MB live list at ~227 KB/s = 81 s).
The old `ClientTimeout(total=60)` killed that healthy-but-slow transfer, so the whole
provider loaded 0 channels. The fix (`_CONTENT_READ_TIMEOUT`, sock_read-based, no total)
tolerates a steady trickle while still failing a genuinely stalled socket.

These tests drive the REAL `XtreamAPI.get_live_streams` against an in-process server
that streams the catalog in chunks with deliberate gaps:

  * test_get_live_streams_reads_full_slow_trickle — with the production timeout, a
    transfer that runs well past a tight `total` deadline (but keeps sending) is read
    in full. This is the case that regressed.
  * test_total_deadline_would_drop_the_same_trickle — restore a short `total` deadline
    and the identical trickle is killed mid-stream, pinning *why* the timeout must be
    sock_read-based. `_get_streams` re-raises the timeout (for URL failover), so it
    propagates to the caller here.

Per CLAUDE.md "Tests must prove behavior, not shape": no substring/AST assertions — the
changed read path is executed against a live socket.
"""

from __future__ import annotations

import asyncio
import json

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from metatv.providers import xtream as xtream_mod
from metatv.providers.xtream import XtreamAPI

# A catalog big enough to span several trickled chunks.
_PAYLOAD = [
    {"num": i, "stream_type": "live", "name": f"CH {i}", "stream_id": 1000 + i}
    for i in range(40)
]


def _make_trickle_app(n_chunks: int, chunk_delay: float) -> web.Application:
    """Serve _PAYLOAD as JSON over /player_api.php, written in n_chunks with a gap
    of chunk_delay seconds between each (simulating a slow-but-steady server)."""
    body = json.dumps(_PAYLOAD).encode()

    async def handler(request: web.Request) -> web.StreamResponse:
        resp = web.StreamResponse(
            status=200, headers={"Content-Type": "application/json"}
        )
        await resp.prepare(request)
        step = max(1, len(body) // n_chunks)
        for i in range(0, len(body), step):
            await resp.write(body[i : i + step])
            await asyncio.sleep(chunk_delay)  # yields → client reads this chunk
        await resp.write_eof()
        return resp

    app = web.Application()
    app.router.add_get("/player_api.php", handler)
    return app


async def _drive(n_chunks: int, chunk_delay: float):
    """Start an in-process trickle server and call the real get_live_streams against it."""
    server = TestServer(_make_trickle_app(n_chunks, chunk_delay))
    await server.start_server()
    try:
        base = str(server.make_url("")).rstrip("/")
        async with XtreamAPI(base, "u", "p") as api:
            return await api.get_live_streams()
    finally:
        await server.close()


def test_get_live_streams_reads_full_slow_trickle():
    """Production timeout must read a ~1 s trickle (10 chunks × 0.1 s) in full.

    The whole transfer outlasts any tight `total` deadline, but each gap is far under
    sock_read, so a healthy slow server completes — the IPTV Ninja case.
    """
    result = asyncio.run(_drive(n_chunks=10, chunk_delay=0.1))
    assert isinstance(result, list)
    assert len(result) == len(_PAYLOAD)
    assert result[0]["name"] == "CH 0"
    assert result[-1]["stream_id"] == 1000 + len(_PAYLOAD) - 1


def test_total_deadline_would_drop_the_same_trickle(monkeypatch):
    """Restoring a short `total` deadline kills the identical healthy trickle.

    This pins the regression: if someone swaps _CONTENT_READ_TIMEOUT back to a `total`
    deadline shorter than a slow catalog's transfer time, the provider loads 0 again.
    """
    monkeypatch.setattr(
        xtream_mod, "_CONTENT_READ_TIMEOUT", aiohttp.ClientTimeout(total=0.3)
    )
    with pytest.raises((asyncio.TimeoutError, TimeoutError)):
        asyncio.run(_drive(n_chunks=10, chunk_delay=0.1))
