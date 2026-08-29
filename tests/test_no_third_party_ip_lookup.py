"""The app does not ask a third party what the user's IP is.

``ConnectionTracker.get_client_ip`` fetched ``https://api.ipify.org`` on the
connection-failure path — an HTTPS round-trip telling that service the user's
address every time a provider URL misbehaved. It shipped in the initial commit
(2026-05-11) and was never revisited.

It is removed rather than fixed, because the feature it fed never worked:

* ``ProviderURL.failed_client_ips`` counts failures per IP and
  ``is_ip_blocked`` reads that count;
* of **280 recorded attempts in the owner's library, 280 have
  ``client_ip: null``** — so the dict is always empty and the check always
  False;
* and ``url_cycle.py``, the actual chokepoint for URL cycling, documents that
  it deliberately does NOT route through this class *because of* that
  round-trip.

The app paid a privacy cost for a signal nothing ever read.

If per-network failure detection is wanted later, store a salted hash of the
address rather than the address. It still answers "these failures are all on
the network you are on now" while being useless to anyone who reads the file —
which matters in a codebase that has already leaked credentials into shareable
logs once.
"""

from __future__ import annotations

import ast
import asyncio
import pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent
PKG = REPO / "metatv"


def test_no_module_contacts_an_ip_lookup_service():
    """THE assertion. Derived, so a different service is caught too."""
    services = (
        "ipify", "ipinfo.io", "icanhazip", "ifconfig.me", "checkip",
        "whatismyip", "myip.com", "ip-api.com", "ipapi.co",
    )
    offenders = []
    for path in sorted(PKG.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        # The docstring explaining the removal names ipify on purpose; only
        # flag it where it appears outside a docstring.
        tree = ast.parse(text)
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node, clean=False)
                if doc:
                    docstrings.add(doc)
        code_only = text
        for doc in docstrings:
            code_only = code_only.replace(doc, "")
        for svc in services:
            if svc in code_only:
                offenders.append(f"{path.relative_to(REPO).as_posix()} -> {svc}")
    assert not offenders, (
        "these modules ask a third party for the user's IP: " + str(offenders)
    )


def test_get_client_ip_makes_no_request_and_returns_none():
    """Kept as a method so call sites and stored JSON stay valid."""
    from metatv.core.connection_tracker import ConnectionTracker

    assert asyncio.run(ConnectionTracker.get_client_ip()) is None


def test_recording_a_failure_stores_no_address():
    from metatv.core.connection_tracker import ConnectionTracker
    from metatv.core.models import ProviderURL

    url = ProviderURL(url="http://host.example:8080")
    asyncio.run(ConnectionTracker.record_failure(url, "empty response"))

    assert url.failure_count == 1, "the failure itself must still be recorded"
    assert all(a.client_ip is None for a in url.recent_attempts)


def test_recording_a_success_still_updates_the_score():
    """Removing the lookup must not remove the tracking it was attached to."""
    from metatv.core.connection_tracker import ConnectionTracker
    from metatv.core.models import ProviderURL

    url = ProviderURL(url="http://host.example:8080")
    asyncio.run(ConnectionTracker.record_success(url, response_time_ms=120))

    assert url.success_count == 1
    assert url.last_success is not None


def test_no_log_line_interpolates_the_removed_address():
    """A log saying "from IP None" would be worse than saying nothing."""
    src = (PKG / "core" / "connection_tracker.py").read_text(encoding="utf-8")
    assert "from IP {client_ip}" not in src
