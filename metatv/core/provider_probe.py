"""Async connection probe for Xtream-compatible IPTV providers.

UI-free: no Qt imports, and no user-facing presentation. ``probe_url`` returns a
structured :class:`ProbeResult` (status code + raw latency + machine-readable
detail); formatting that into a badge string is the caller's job. This keeps the
module reusable by a future headless backend without dragging UI vocabulary
(or English) into ``core``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from time import time

import aiohttp

_PROBE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}


class ProbeStatus(str, Enum):
    """Outcome category for a single URL probe (UI-agnostic)."""

    ACTIVE = "active"            # auth ok, account active — the only success state
    INACTIVE = "inactive"       # auth ok but account not active (expired/banned/etc.)
    AUTH_FAILED = "auth_failed"  # server replied but credentials rejected
    HTTP_ERROR = "http_error"    # non-200 HTTP status
    TIMEOUT = "timeout"          # request timed out
    ERROR = "error"             # connection / parse / other exception


@dataclass(frozen=True)
class ProbeResult:
    """Structured result of probing one URL.

    Attributes:
        url: The probed URL (echoed back so batch callers can correlate results).
        success: True only when the account is authenticated and active.
        latency_ms: Round-trip time in milliseconds.
        status: The :class:`ProbeStatus` category.
        detail: Status-specific machine-readable extra — the raw account-status
            string (INACTIVE), the HTTP status code (HTTP_ERROR), or the
            truncated exception text (ERROR). Empty otherwise.
    """

    url: str
    success: bool
    latency_ms: int
    status: ProbeStatus
    detail: str = ""


async def probe_url(url: str, username: str, password: str) -> ProbeResult:
    """Test a single Xtream API URL.

    Returns:
        A :class:`ProbeResult`. ``success`` is True only for an authenticated,
        active account.
    """
    start = time()
    clean = url.rstrip("/")
    auth_url = f"{clean}/player_api.php?username={username}&password={password}"
    try:
        async with aiohttp.ClientSession(headers=_PROBE_HEADERS) as session:
            async with session.get(auth_url, timeout=aiohttp.ClientTimeout(total=12)) as resp:
                ms = int((time() - start) * 1000)
                if resp.status != 200:
                    return ProbeResult(url, False, ms, ProbeStatus.HTTP_ERROR, str(resp.status))
                data = await resp.json(content_type=None)
                user_info = data.get("user_info", {}) if isinstance(data, dict) else {}
                auth = user_info.get("auth", 0)
                status = str(user_info.get("status", ""))
                if auth and status.lower() == "active":
                    return ProbeResult(url, True, ms, ProbeStatus.ACTIVE)
                if auth:
                    return ProbeResult(url, False, ms, ProbeStatus.INACTIVE, status)
                return ProbeResult(url, False, ms, ProbeStatus.AUTH_FAILED)
    except asyncio.TimeoutError:
        return ProbeResult(url, False, int((time() - start) * 1000), ProbeStatus.TIMEOUT)
    except Exception as e:
        return ProbeResult(url, False, int((time() - start) * 1000), ProbeStatus.ERROR, str(e)[:80])


async def probe_all_urls(
    urls: list[str],
    username: str,
    password: str,
    on_result: Callable[[ProbeResult], None] | None = None,
) -> list[ProbeResult]:
    """Test all URLs in parallel.

    Args:
        on_result: Optional callback invoked with each :class:`ProbeResult` as
            soon as that probe finishes (before the gather completes), so callers
            can stream incremental updates (e.g. emit a Qt signal per URL).

    Returns:
        All results sorted: successes fastest-first, then failures.
    """

    async def _one(url: str) -> ProbeResult:
        result = await probe_url(url, username, password)
        if on_result is not None:
            on_result(result)
        return result

    results = await asyncio.gather(*[_one(u) for u in urls])
    return sorted(results, key=lambda r: (0 if r.success else 1, r.latency_ms))
