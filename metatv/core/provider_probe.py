"""Async connection probe for Xtream-compatible IPTV providers.

UI-free: no Qt imports. Accepts raw URLs, username, and password;
returns structured results so callers can emit signals or handle them however they need.
"""

from __future__ import annotations

from time import time

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


async def probe_url(url: str, username: str, password: str) -> tuple[bool, int, str]:
    """Test a single Xtream API URL.

    Returns:
        (success, latency_ms, human-readable message)
    """
    import asyncio
    import aiohttp

    start = time()
    clean = url.rstrip("/")
    auth_url = f"{clean}/player_api.php?username={username}&password={password}"
    try:
        async with aiohttp.ClientSession(headers=_PROBE_HEADERS) as session:
            async with session.get(auth_url, timeout=aiohttp.ClientTimeout(total=12)) as resp:
                ms = int((time() - start) * 1000)
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    user_info = data.get("user_info", {}) if isinstance(data, dict) else {}
                    auth = user_info.get("auth", 0)
                    status = user_info.get("status", "")
                    if auth and status.lower() == "active":
                        return True, ms, f"Active  {ms} ms"
                    elif auth:
                        return False, ms, f"Account {status}"
                    else:
                        return False, ms, "Auth failed"
                else:
                    return False, int((time() - start) * 1000), f"HTTP {resp.status}"
    except asyncio.TimeoutError:
        return False, int((time() - start) * 1000), "Timeout"
    except Exception as e:
        return False, int((time() - start) * 1000), str(e)[:80]


async def probe_all_urls(
    urls: list[str],
    username: str,
    password: str,
) -> list[tuple[str, bool, int, str]]:
    """Test all URLs in parallel.

    Returns:
        List of (url, success, latency_ms, message), sorted: successes fastest-first,
        failures after.
    """
    import asyncio

    async def _one(url: str) -> tuple[str, bool, int, str]:
        success, ms, msg = await probe_url(url, username, password)
        return url, success, ms, msg

    results = await asyncio.gather(*[_one(u) for u in urls], return_exceptions=False)
    return sorted(results, key=lambda r: (0 if r[1] else 1, r[2]))
