"""A refusal is about the caller, not about the address that delivered it.

Owner: "getting 403 or 405 errors can be normal when vpn ip is blocked or subs
have expired, so perhaps make the loop through urls a bit more intelligent".

Every host on an account returns the same 403 when the calling IP is blocked or
the subscription lapsed. Counting that against a host demotes a working address
for something it did not do — and when every host is refused, it demotes all of
them equally AND puts every one into cooldown, so the next genuine attempt is
delayed across the board. The ranking learns nothing and the user waits longer.

The attempt is still recorded. The history is true and the diagnosis reads it;
it simply must not be evidence about the host.
"""

import pytest

from metatv.core.models import Provider, ProviderURL
from metatv.core.url_cycle import UrlCycler

DECAY = 0.8


@pytest.fixture
def cycler():
    provider = Provider(id="p1", type="xtream", name="P", url="http://a")
    provider.urls = [ProviderURL(url="http://a"), ProviderURL(url="http://b")]
    return UrlCycler(provider, "test"), provider


# ── the fix ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status", [401, 403, 405, 429])
def test_a_refusal_does_not_demote_the_host(cycler, status: int) -> None:
    """Three refusals must leave the host's standing untouched."""
    c, provider = cycler
    for _ in range(3):
        c.record_failure("http://a", f"{status} refused", status=status)

    url = provider.urls[0]
    assert url.failure_count == 0, f"HTTP {status} counted against the host"
    assert url.health_score(DECAY) == 1.0, f"HTTP {status} dragged health down"


def test_a_refusal_is_still_recorded(cycler) -> None:
    """Not counted is not the same as not remembered."""
    c, provider = cycler
    c.record_failure("http://a", "403 refused", status=403)

    attempts = provider.urls[0].recent_attempts
    assert len(attempts) == 1, "the attempt was dropped instead of marked"
    assert attempts[0].host_at_fault is False
    assert provider.urls[0].last_error == "403 refused"


def test_a_refusal_does_not_put_the_host_in_cooldown() -> None:
    """If it did, a blocked IP would bench every address at once.

    Read off the candidates log line, which reports the cooldown decision for
    each host. Captured through a loguru sink rather than pytest's ``caplog``:
    this project logs exclusively through loguru, which does not propagate to
    the stdlib handlers caplog installs, so caplog sees nothing at all.
    """
    from loguru import logger

    provider = Provider(id="p1", type="xtream", name="P", url="http://a")
    provider.urls = [ProviderURL(url="http://a"), ProviderURL(url="http://b")]
    c = UrlCycler(provider, "test")

    c.record_failure("http://a", "403", status=403)

    lines: list[str] = []
    sink = logger.add(lines.append, level="INFO", format="{message}")
    try:
        c.candidates()
    finally:
        logger.remove(sink)

    line = next((m for m in lines if "candidates —" in m), None)
    assert line is not None, f"no candidates line was logged: {lines}"
    assert "cooldown=True" not in line, f"a refused host was benched: {line}"


def test_a_real_failure_does_put_the_host_in_cooldown() -> None:
    """The mirror, so the test above cannot pass by cooldown never firing."""
    from loguru import logger

    provider = Provider(id="p1", type="xtream", name="P", url="http://a")
    provider.urls = [ProviderURL(url="http://a"), ProviderURL(url="http://b")]
    c = UrlCycler(provider, "test")

    c.record_failure("http://a", "connection reset")

    lines: list[str] = []
    sink = logger.add(lines.append, level="INFO", format="{message}")
    try:
        c.candidates()
    finally:
        logger.remove(sink)

    line = next((m for m in lines if "candidates —" in m), None)
    assert line is not None
    assert "cooldown=True" in line, f"a genuinely failed host was NOT benched: {line}"


# ── and what must STILL be blamed on the host ───────────────────────────────

def test_a_connection_failure_still_demotes_the_host(cycler) -> None:
    """The behaviour being narrowed, not removed."""
    c, provider = cycler
    for _ in range(3):
        c.record_failure("http://a", "connection reset")

    url = provider.urls[0]
    assert url.failure_count == 3
    assert url.health_score(DECAY) == 0.0


@pytest.mark.parametrize("status", [500, 502, 503])
def test_a_server_error_is_still_the_hosts_problem(cycler, status: int) -> None:
    """5xx means THIS host is broken — exactly what the ranking is for."""
    c, provider = cycler
    c.record_failure("http://a", f"{status} server error", status=status)
    assert provider.urls[0].failure_count == 1


def test_an_empty_response_is_still_the_hosts_problem(cycler) -> None:
    """Four call sites report this with no status, and they are right to."""
    c, provider = cycler
    c.record_failure("http://a", "empty response", response_time_ms=12)
    assert provider.urls[0].failure_count == 1
    assert provider.urls[0].recent_attempts[0].host_at_fault is True


# ── the trap this deliberately avoids ───────────────────────────────────────

def test_the_status_comes_from_the_exception_not_the_message(cycler) -> None:
    """A host on port 8403 must not read as a 403 forever.

    The error text is ``str(exc)``, which embeds the URL. Sniffing "403" out of
    it would permanently exempt any host whose port or path contains those
    digits — the reason ``status`` is an int parameter rather than inferred.
    """
    c, provider = cycler
    c.record_failure("http://a", "Cannot connect to host a:8403 ssl:default", status=None)
    assert provider.urls[0].failure_count == 1, (
        "a port containing '403' was mistaken for an HTTP 403 refusal"
    )
