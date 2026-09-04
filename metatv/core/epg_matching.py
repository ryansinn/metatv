"""Matching an XMLTV feed's channels to the channels in the library.

Extracted from ``EpgManager`` (#331): a distinct, independently testable
concern, and the manager was 269 lines past the project's file-size rule before
the shutdown fix needed room. ``EpgManager._build_match_map`` stays as a thin
delegate — a good deal of the suite drives it by that name, and it remains the
one place the manager reaches matching from.

Takes ``config`` explicitly rather than a manager: the two blocklist reads were
the method's only tie to ``self``.
"""

from __future__ import annotations

import re

from loguru import logger

from metatv.core.channel_name_utils import epg_tld_compatible
from metatv.core.database import ChannelDB
from metatv.core.repositories import RepositoryFactory
from metatv.core.xmltv_parser import normalize_channel_name


# The trailing dot-suffix some feeds use as a language/region TLD idiom on an
# epg_id ("UandEden.uk" -> "uk"); only a 2-3 letter alpha suffix counts — anything
# else is not a TLD and the region gate abstains (channel_name_utils.epg_tld_compatible).
_EPG_ID_TLD_RE = re.compile(r"\.([A-Za-z]{2,3})$")


def _epg_id_tld(epg_id: str) -> str | None:
    """Extract the lowercase TLD suffix from an XMLTV epg_id, or None if absent."""
    if not epg_id:
        return None
    m = _EPG_ID_TLD_RE.search(epg_id)
    return m.group(1).lower() if m else None


def build_match_map(
    session, xmltv_channels, provider_id: str, config
) -> dict[str, str]:
    """Build xmltv_epg_id → channel_db_id lookup.

    Resolution order (first match wins):
    1. Exact ``epg_channel_id`` match — highest confidence, provider-agnostic.
    2. Same-provider fuzzy name match — normalized channel name from the feed's
       own provider wins over any cross-source match.
    3. Cross-provider fuzzy name match — fills gaps when the feed's own provider
       has no matching channel (e.g. a bare XMLTV feed covering multiple sources).

    Channels belonging to hidden (inactive or expired) providers are excluded from
    the fuzzy candidate pool entirely, so guide data never attaches to a
    disabled/expired source at fetch time.

    Two persistent config-driven guards, both consulted here so they can never
    be bypassed by ``relink_all()`` (which re-runs this on every EPG view
    activation) or by a provider re-ingestion rewriting ``ChannelDB.epg_channel_id``:

    * ``config.epg_link_blocklist`` — channel_db_ids the user manually cleared
      ("Clear EPG link"). Excluded from ALL tiers (1/2/3).
    * ``config.epg_fuzzy_prefix_blocklist`` — ``detected_prefix`` values (e.g.
      "24/7") that denote show-loop/rotation feeds, not real broadcasts.
      Excluded from tiers 2/3 only; tier-1 exact ids still apply.

    Tiers 2/3 are additionally region-gated: a candidate's ``detected_prefix``/
    ``detected_region`` is checked against the EPG feed's TLD (parsed from its
    epg_id) via ``channel_name_utils.epg_tld_compatible`` — an unrecognized
    code/TLD abstains (matches as before); a recognized mismatch is rejected.
    """
    repos = RepositoryFactory(session)
    hidden_ids: set[str] = set(repos.providers.get_hidden_provider_ids())
    blocked_ids: set[str] = set(config.epg_link_blocklist or [])
    fuzzy_prefix_blocklist: set[str] = {
        p.strip().upper() for p in (config.epg_fuzzy_prefix_blocklist or []) if p
    }

    # ── Tier 1: exact epg_channel_id match ──────────────────────────────
    # Select only the two scalar columns needed — avoids loading raw_data
    # (potentially large JSON) for every channel in a 1M+ library.
    db_channels_with_id = session.query(
        ChannelDB.id, ChannelDB.epg_channel_id,
    ).filter(
        ChannelDB.epg_channel_id.isnot(None),
        ChannelDB.is_hidden == False,
    ).all()
    exact: dict[str, str] = {
        epg_id: cid
        for cid, epg_id in db_channels_with_id
        if epg_id and cid not in blocked_ids
    }

    # ── Tiers 2 & 3: fuzzy name candidates, excluding hidden providers ──
    # Build two separate dicts so same-provider always beats cross-provider.
    # Last-writer-wins within each dict is fine: duplicate normalized names
    # are rare and either candidate would be acceptable. Values carry
    # (channel_db_id, detected_prefix, detected_region) so the region gate
    # below can consult them without a second query.
    # yield_per streams results in fixed-size buffers to avoid materialising
    # the full channel table (240k–1M rows) into memory at once.
    all_live = session.query(
        ChannelDB.id, ChannelDB.name, ChannelDB.provider_id,
        ChannelDB.detected_prefix, ChannelDB.detected_region,
    ).filter(
        ChannelDB.media_type == "live",
        ChannelDB.is_hidden == False,
    ).yield_per(10000)

    same_provider: dict[str, tuple[str, str | None, str | None]] = {}
    cross_provider: dict[str, tuple[str, str | None, str | None]] = {}

    for cid, name, prov_id, prefix, region in all_live:
        if prov_id in hidden_ids:
            continue  # never attach guide data to a disabled/expired source
        if cid in blocked_ids:
            continue  # manually cleared — never re-enter fuzzy matching
        if prefix and prefix.strip().upper() in fuzzy_prefix_blocklist:
            continue  # show-loop/rotation feed — fuzzy name matching is unreliable
        norm = normalize_channel_name(name)
        if not norm:
            # Placeholder/separator names ('HD', blanks) normalize to "" and
            # would all collide on the same key (last-writer-wins), attaching a
            # guide to an unrelated channel. Never key the fuzzy pool on "".
            continue
        candidate = (cid, prefix, region)
        if prov_id == provider_id:
            same_provider[norm] = candidate
        else:
            cross_provider[norm] = candidate

    result: dict[str, str] = {}
    for xch in xmltv_channels:
        if xch.epg_id in exact:
            # Tier 1 — exact epg_channel_id (never region-gated)
            result[xch.epg_id] = exact[xch.epg_id]
            continue

        norm = normalize_channel_name(xch.display_name)
        epg_tld = _epg_id_tld(xch.epg_id)

        if norm in same_provider:
            # Tier 2 — same-provider fuzzy
            cid, prefix, region = same_provider[norm]
            if epg_tld_compatible((prefix, region), epg_tld):
                result[xch.epg_id] = cid
            else:
                logger.debug(
                    f"EPG region gate: rejected same-provider fuzzy match "
                    f"{xch.display_name!r} (epg_id={xch.epg_id!r}, tld={epg_tld!r}) "
                    f"against channel prefix={prefix!r} region={region!r}"
                )
        elif norm in cross_provider:
            # Tier 3 — cross-provider fuzzy
            cid, prefix, region = cross_provider[norm]
            if epg_tld_compatible((prefix, region), epg_tld):
                result[xch.epg_id] = cid
            else:
                logger.debug(
                    f"EPG region gate: rejected cross-provider fuzzy match "
                    f"{xch.display_name!r} (epg_id={xch.epg_id!r}, tld={epg_tld!r}) "
                    f"against channel prefix={prefix!r} region={region!r}"
                )

    matched = len(result)
    logger.info(
        f"EPG channel matching: {matched}/{len(xmltv_channels)} XMLTV channels "
        f"matched to playable streams (provider={provider_id})"
    )
    return result

# ------------------------------------------------------------------
# Relink — DB-only re-match (no network fetch)
# ------------------------------------------------------------------

