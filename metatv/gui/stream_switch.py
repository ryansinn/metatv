"""Same-provider stream switching: skip the probe the running stream already answers.

PLAY-10 (2026-09-05). On a one-connection provider, switching from a playing
stream to another stream on the SAME provider used to fail the first time and
work on the second double-click ~20s later. The mechanism (established from
code + logs, see the PR): ``MPVPlayer.play`` sends ``loadfile … replace`` to
the running instance, which closes the old connection and opens the new one
at once — but the Xtream panel keeps counting the just-closed connection
until its own reaper expires it (#635 measured 14-26s of HTTP 500 "failed to
redirect to stream origin"). The pre-play probe
(``main_window_streaming.validate_stream_url``) is itself one more connection
the panel must reap, and it ran on every switch even though the CURRENTLY
PLAYING stream is standing proof the source is reachable right now.

This module is the single definition of "is this play a same-provider
switch, and if so what does it change":

* :func:`switch_context` reads the running window's provider + URL (via
  ``PlayerManager``) and the provider's connection-accountant capacity to
  decide whether the next play is a same-provider switch, and whether the
  provider has exactly one connection (the case this whole slice exists for).
* :func:`prefer_live_host` rewrites the next URL onto the host that is
  CURRENTLY streaming — proven live right now — instead of re-resolving from
  provider order, but never onto a host outside the provider's own candidate
  list (never routes traffic somewhere ``UrlCycler`` wouldn't have tried).

Both are pure functions over caller-supplied objects — this module holds no
``Config`` and makes no I/O, same as ``core/channel_visibility.py`` and
``core/url_policy.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from metatv.core.models import Provider
from metatv.core.url_cycle import UrlCycler, rebase_stream_url


@dataclass(frozen=True)
class SwitchContext:
    """What :func:`switch_context` learned about the play about to replace this one.

    Attributes:
        same_provider: True when the instance key this play would target is
            currently running content from the SAME provider — the running
            stream is standing proof the source is reachable right now, so
            the probe/failover cycles that exist to discover that are
            redundant for this one play.
        live_base_url: ``scheme://netloc`` of the URL currently playing into
            that instance key, or None (nothing running, or unknown). The
            host :func:`prefer_live_host` prefers when it applies.
        one_connection: True when the provider's connection accountant
            resolves its capacity to exactly 1 — the case a switch actually
            risks the provider-still-counting-the-old-stream failure PLAY-10
            fixes; False for any other capacity or when accounting isn't
            available.
    """

    same_provider: bool
    live_base_url: str | None
    one_connection: bool


def switch_context(player_manager, connection_accountant, provider_id: str | None,
                    key: str) -> SwitchContext:
    """Decide whether the play about to start is a same-provider switch.

    Args:
        player_manager: The app's ``PlayerManager`` (or a test double
            exposing ``is_running``, ``provider_for_key``, ``live_base_url``
            with the real class's signatures).
        connection_accountant: The provider's ``ConnectionAccountant``, or
            None when accounting isn't available — ``one_connection`` is
            False in that case rather than guessed.
        provider_id: The channel's provider_id for the play about to start.
        key: The mpv instance key that play would target (whatever
            ``PlayerManager.resolve_key``/``play()`` already resolves for it).

    Returns:
        The :class:`SwitchContext` for this play.
    """
    same_provider = (bool(player_manager.is_running(key))
                      and player_manager.provider_for_key(key) == provider_id)
    live_base = player_manager.live_base_url(key)
    one_connection = (connection_accountant is not None
                       and connection_accountant.capacity(provider_id) == 1)
    return SwitchContext(same_provider=same_provider, live_base_url=live_base,
                          one_connection=one_connection)


def prefer_live_host(url: str, live_base_url: str | None, provider_model: Provider) -> str:
    """Rewrite *url* onto the host that is currently streaming, when it is safe to.

    Rewrites only when *live_base_url* is set, differs from *url*'s own base,
    AND is one of the provider's own ranked candidates (``UrlCycler`` —
    :meth:`~metatv.core.url_cycle.UrlCycler.candidates`) — never a host
    outside the provider's configured list, however plausible it looks.
    Otherwise *url* is returned unchanged.

    Args:
        url: The next stream's URL as resolved from the channel row.
        live_base_url: ``scheme://netloc`` of the host currently playing into
            the target instance (``SwitchContext.live_base_url``), or None.
        provider_model: The channel's provider, for candidate-list membership.

    Returns:
        *url*, rewritten onto *live_base_url* when that host both differs and
        is a real candidate for this provider; otherwise *url* unchanged.
    """
    if not live_base_url:
        return url
    parsed = urlsplit(url)
    url_base = f"{parsed.scheme}://{parsed.netloc}"
    if live_base_url.rstrip("/") == url_base.rstrip("/"):
        return url
    candidates = {c.rstrip("/") for c in UrlCycler(provider_model, "resolve_playable_url").candidates()}
    if live_base_url.rstrip("/") not in candidates:
        return url
    return rebase_stream_url(url, url_base, live_base_url)
