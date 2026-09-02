"""One chokepoint for cycling a provider's URLs and recording what happened.

Seven+ code paths across the app cycle through :meth:`Provider.ordered_urls`
(`core/models.py`) looking for a working host, but almost none of them fed the
ranker back — a chronically slow-but-working host could sit at the top of
``ordered_urls()`` forever because nothing ever recorded its outcome. This
module is the single definition of "try a provider's URLs in reliability
order and record what happened" that every one of those call sites shares.

``providers/xtream.py`` is async (aiohttp); ``gui/main_window_streaming.py``'s
failover loop is sync (requests). This module deliberately does NOT try to
unify the await/loop mechanics — each caller keeps its own local loop. What's
shared is the *data* side: which URLs, in what order, and how an outcome is
recorded onto the in-memory :class:`~metatv.core.models.Provider`.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from loguru import logger

from metatv.core.url_policy import UrlRankingPolicy, get_url_ranking_policy
from metatv.core.connection_diagnosis import REFUSAL_STATUSES
from metatv.core.models import ConnectionAttempt, Provider, ProviderURL


class UrlCycler:
    """One definition of "try a provider's URLs in reliability order and record what happened".

    Wraps a :class:`~metatv.core.models.Provider`. :meth:`candidates` exposes
    its :meth:`~metatv.core.models.Provider.ordered_urls` (ranked on cooldown,
    recency-weighted health, and latency — see that method's docstring);
    :meth:`record_success`/:meth:`record_failure` update the matching
    :class:`~metatv.core.models.ProviderURL`'s counters, timestamps, and
    ``recent_attempts`` history in memory as each candidate is tried.

    Deliberately NOT routed through ``ConnectionTracker.record_success`` /
    ``record_failure`` (``core/connection_tracker.py``): those are ``async``
    and each call ``get_client_ip()`` — an HTTPS round-trip to api.ipify.org
    with a 5s timeout. Paying that extra network round-trip on every URL
    attempt in the fetch/play hot paths is unacceptable. ``ConnectionTracker``
    stays exactly as it is, used only by the explicit "Test Connection"
    button, which already budgets for that cost. Do not "unify" the two —
    they solve different problems at different price points.

    This object only mutates the in-memory ``Provider`` — it never touches a
    database. ``providers/`` (and this module) must not gain ``Database``
    access, per the engine/control/view layering rule; persisting the outcome
    is the caller's (control-layer) job, via
    :func:`metatv.core.repositories.provider.persist_url_stats`.
    """

    def __init__(self, provider: Provider, operation: str) -> None:
        """Args:
            provider: The provider whose URLs are being cycled.
            operation: Short label for the operation in progress (e.g.
                ``"fetch_channels"``, ``"fetch_series_info"``) — included in
                log lines so a slow or failing host is traceable to the call
                that hit it.
        """
        self.provider = provider
        self.operation = operation
        self._dirty = False

    def candidates(self, policy: UrlRankingPolicy | None = None) -> list[str]:
        """Return the provider's base URLs in reliability-first order.

        Delegates to :meth:`Provider.ordered_urls` — this is the one place
        (besides ``core/models.py`` itself) that call is allowed to appear.
        *policy* defaults to the process-wide ranking policy (resolved once
        disk I/O — field defaults only) so existing no-arg callers are
        unaffected.

        Emits one INFO log line listing every candidate with its health,
        median latency, and cooldown state — how the owner validates the
        decay/cooldown constants against real traffic instead of guessing.
        """
        if policy is None:
            policy = get_url_ranking_policy()

        ordered = self.provider.ordered_urls(policy)

        now = datetime.now()
        cooldown = timedelta(minutes=policy.cooldown_minutes)
        parts = []
        for base_url in ordered:
            pu = self._find(base_url)
            if pu is None:
                parts.append(f"{base_url} [untracked]")
                continue
            health = pu.health_score(policy.health_decay)
            latency = pu.median_latency_ms()
            # A host refused for an account-level reason is not benched: all of
            # them would be, so the cooldown would delay every retry rather
            # than steer around a bad address.
            last = pu.recent_attempts[-1] if pu.recent_attempts else None
            in_cooldown = (
                last is not None and not last.success and last.host_at_fault
                and (now - last.timestamp) <= cooldown
            )
            parts.append(
                f"{base_url} [health={health:.2f} latency={latency}ms cooldown={in_cooldown}]"
            )
        logger.info(f"{self.operation}: candidates — " + ", ".join(parts))

        return ordered

    def _find(self, base_url: str) -> ProviderURL | None:
        """Return the ``ProviderURL`` matching *base_url*, or ``None``.

        Matches trailing-slash-insensitively, mirroring ``ordered_urls()``'s
        own normalization.
        """
        target = base_url.rstrip('/')
        for pu in self.provider.urls:
            if pu.url.rstrip('/') == target:
                return pu
        return None

    def record_success(self, base_url: str, response_time_ms: int | None = None) -> None:
        """Record a successful attempt against *base_url*.

        Bumps ``success_count``, stamps ``last_success``, and clears
        ``last_error`` on the matching ``ProviderURL`` — and appends a
        :class:`~metatv.core.models.ConnectionAttempt` (via
        :meth:`~metatv.core.models.ProviderURL.add_attempt`) so the
        recency-weighted ranker in ``Provider.ordered_urls()`` has something
        to weigh. A *base_url* with no matching entry — e.g. the legacy
        ``provider.url`` fallback, which has no ``ProviderURL`` row — is
        logged at DEBUG and otherwise ignored; this must never raise.

        Args:
            base_url: The URL that was attempted.
            response_time_ms: Elapsed time of the attempt in milliseconds
                (``time.monotonic()`` before/after), or ``None`` if the
                caller didn't time it.
        """
        pu = self._find(base_url)
        if pu is None:
            logger.debug(
                f"{self.operation}: no ProviderURL entry for {base_url!r} — success not recorded"
            )
            return
        pu.success_count += 1
        pu.last_success = datetime.now()
        pu.last_error = None
        pu.add_attempt(ConnectionAttempt(success=True, response_time_ms=response_time_ms))
        # The one-shot boost has done its job the moment this attempt is
        # recorded — evidence resumes control from here.
        pu.try_first = False
        self._dirty = True
        logger.info(f"{self.operation}: recorded success for {base_url}")

    def record_failure(self, base_url: str, error: str, response_time_ms: int | None = None,
                       status: int | None = None) -> None:
        """Record a failed attempt against *base_url*.

        Bumps ``failure_count``, stamps ``last_failure``, and stores *error*
        as ``last_error`` on the matching ``ProviderURL`` — and appends a
        :class:`~metatv.core.models.ConnectionAttempt` so the ranker sees it.
        A *base_url* with no matching entry is logged at DEBUG and otherwise
        ignored; this must never raise.

        Args:
            base_url: The URL that was attempted.
            error: Error message to store as ``last_error``.
            response_time_ms: Elapsed time of the attempt in milliseconds
                before it failed, or ``None`` if unknown/not timed.
            status: HTTP status when the host answered, else ``None``. Pass
                ``getattr(exc, "status", None)`` — ``aiohttp.ClientResponseError``
                carries it. A REFUSAL status marks the attempt as not the
                host's fault: it is recorded for history and diagnosis, but
                does not bump ``failure_count``, does not drag ``health_score``
                down, and does not put the host in cooldown.

                Taken as an int rather than sniffed out of *error*: the message
                is ``str(exc)``, which embeds the URL — so a host on port 8403
                would read as a 403 forever.
        """
        pu = self._find(base_url)
        if pu is None:
            logger.debug(
                f"{self.operation}: no ProviderURL entry for {base_url!r} — failure not recorded"
            )
            return
        # A refusal is about the caller (blocked IP, dead subscription) and is
        # returned identically by every host on the account, so it is no
        # evidence about THIS address.
        host_at_fault = status is None or str(status) not in REFUSAL_STATUSES

        if host_at_fault:
            pu.failure_count += 1
        pu.last_failure = datetime.now()
        pu.last_error = error
        pu.add_attempt(ConnectionAttempt(
            success=False, error_message=error, response_time_ms=response_time_ms,
            host_at_fault=host_at_fault,
        ))
        # The one-shot boost has done its job the moment this attempt is
        # recorded — evidence resumes control from here, win or lose.
        pu.try_first = False
        self._dirty = True
        if host_at_fault:
            logger.warning(f"{self.operation}: recorded failure for {base_url}: {error}")
        else:
            logger.warning(
                f"{self.operation}: {base_url} refused with HTTP {status} — recorded, but "
                f"not counted against this host (every host on the account returns it): {error}"
            )

    @property
    def dirty(self) -> bool:
        """True if at least one outcome (success or failure) was recorded.

        Lets a caller with a ``Database`` handle skip a pointless write when
        nothing changed (e.g. every candidate had no matching ``ProviderURL``).
        """
        return self._dirty
