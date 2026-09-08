"""DB-2: derive a channel's playable stream URL at play time.

``ChannelDB.stream_url`` was baked in once, at ingestion, from whatever host
and credentials were true THEN — 785,926 rows (100% of channels) store the
full credentialed URL (``{host}/live/{user}/{pass}/{id}.ts``) in plaintext,
with no invalidation, so a provider that rotates its password or drops a dead
host leaves stale rows behind (3,356 real rows already carry credentials or a
host that no longer match their provider — measured against the owner's
library). The column's own comment already says "can be reconstructed
dynamically"; this module is that reconstruction.

Single chokepoint: :func:`derive_channel_stream_url` is called from the one
play path (``main_window_streaming.play_media``) instead of trusting the
stored column. It is deliberately NOT called from the ~40 other
``channel.stream_url`` readers (downloads, signal-check, stream-retry,
series-playback queueing, dev scripts) — those keep reading the column as a
transitional value for now. Converting every reader (so the column itself can
finally be dropped) is future work; converting the highest-traffic reader
first is what proves the derivation correct against real playback before the
rest follow.

Holds no engine-layer purity requirement (unlike ``providers/xtream.py`` and
``core/url_cycle.py``, which must not gain ``Database`` access per DR-0007) —
this lives in the control layer and opens its own short read-only session.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from loguru import logger

from metatv.core.repositories import RepositoryFactory
from metatv.core.url_cycle import UrlCycler
from metatv.providers.xtream import build_stream_url

if TYPE_CHECKING:
    from metatv.core.database import Database


def derive_channel_stream_url(db: "Database", channel) -> Optional[str]:
    """Return a freshly-built playable URL for *channel*, or ``None`` to fall back.

    Resolves the channel's provider, ranks its hosts through the
    :class:`~metatv.core.url_cycle.UrlCycler` chokepoint (never
    ``Provider.ordered_urls()`` directly — see
    ``tests/test_url_cycle.py``'s drift guard) and takes the top-ranked
    candidate, then rebuilds the exact URL shape
    ``providers/xtream.py::convert_to_channel`` bakes at ingestion — but
    against the CURRENT best host and CURRENT credentials, not whatever was
    true the last time this channel was refreshed.

    Returns ``None`` (never raises) when the provider can't be resolved,
    isn't an Xtream provider, or carries no username/base URL — nothing the
    stored column could do better either, so the caller reads
    ``channel.stream_url`` (the transitional column) in that case.

    Args:
        db: The live ``Database`` — opens one short read-only session.
        channel: Anything carrying ``provider_id``, ``source_id``,
            ``media_type`` and ``raw_data`` (``PlayableChannelDTO`` /
            ``ChannelDB`` both qualify).

    Returns:
        The playable URL, or ``None``.
    """
    try:
        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            provider_db = repos.providers.get_by_id(channel.provider_id)
            provider = repos.providers.to_model(provider_db) if provider_db else None
    except Exception as e:
        # Never raises (docstring): the caller falls back to the stored column
        # on any failure here, same as it would have without this derivation.
        logger.debug(f"derive_channel_stream_url: provider lookup failed: {e}")
        return None

    if provider is None or provider.type != "xtream" or not provider.username:
        return None

    candidates = UrlCycler(provider, "play_media").candidates()
    base_url = candidates[0] if candidates else provider.url
    if not base_url:
        return None

    raw_data = getattr(channel, "raw_data", None) or {}
    extension = raw_data.get("container_extension") or "ts"
    return build_stream_url(
        base_url, provider.username, provider.password or "",
        channel.media_type, channel.source_id, extension,
    )
