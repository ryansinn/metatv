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

from datetime import datetime

from loguru import logger

from metatv.core.models import Provider, ProviderURL


class UrlCycler:
    """One definition of "try a provider's URLs in reliability order and record what happened".

    Wraps a :class:`~metatv.core.models.Provider`. :meth:`candidates` exposes
    its :meth:`~metatv.core.models.Provider.ordered_urls` (the 3-tier
    reliability ranking); :meth:`record_success`/:meth:`record_failure` update
    the matching :class:`~metatv.core.models.ProviderURL`'s counters and
    timestamps in memory as each candidate is tried.

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

    def candidates(self) -> list[str]:
        """Return the provider's base URLs in reliability-first order.

        Delegates to :meth:`Provider.ordered_urls` — this is the one place
        (besides ``core/models.py`` itself) that call is allowed to appear.
        """
        return self.provider.ordered_urls()

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

    def record_success(self, base_url: str) -> None:
        """Record a successful attempt against *base_url*.

        Bumps ``success_count``, stamps ``last_success``, and clears
        ``last_error`` on the matching ``ProviderURL``. A *base_url* with no
        matching entry — e.g. the legacy ``provider.url`` fallback, which has
        no ``ProviderURL`` row — is logged at DEBUG and otherwise ignored;
        this must never raise.
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
        self._dirty = True
        logger.info(f"{self.operation}: recorded success for {base_url}")

    def record_failure(self, base_url: str, error: str) -> None:
        """Record a failed attempt against *base_url*.

        Bumps ``failure_count``, stamps ``last_failure``, and stores *error*
        as ``last_error`` on the matching ``ProviderURL``. A *base_url* with
        no matching entry is logged at DEBUG and otherwise ignored; this must
        never raise.
        """
        pu = self._find(base_url)
        if pu is None:
            logger.debug(
                f"{self.operation}: no ProviderURL entry for {base_url!r} — failure not recorded"
            )
            return
        pu.failure_count += 1
        pu.last_failure = datetime.now()
        pu.last_error = error
        self._dirty = True
        logger.warning(f"{self.operation}: recorded failure for {base_url}: {error}")

    @property
    def dirty(self) -> bool:
        """True if at least one outcome (success or failure) was recorded.

        Lets a caller with a ``Database`` handle skip a pointless write when
        nothing changed (e.g. every candidate had no matching ``ProviderURL``).
        """
        return self._dirty
