"""Canonical HTTP headers for stream access (validation, diagnostics, playback).

Single source of truth so the User-Agent used to validate/probe a stream matches
the one mpv uses to play it. A provider that gates on User-Agent (Cloudflare, etc.)
otherwise lets preflight pass and playback fail.
"""
from __future__ import annotations

STREAM_HTTP_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}


def stream_user_agent() -> str:
    """Return the canonical User-Agent string for stream access."""
    return STREAM_HTTP_HEADERS["User-Agent"]
