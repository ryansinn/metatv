"""Diagnostic script for inspecting series episode data across providers.

Detects:
- Duplicate episode_ids within a season (explains "only first episode plays")
- Episode count mismatches between providers for the same normalized title
- Partial seasons (fewer episodes than other providers)

Usage:
    venv/bin/python -m metatv.scripts.inspect_series "Dan Da Dan"
    venv/bin/python -m metatv.scripts.inspect_series "arrested development"
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from metatv.core.content_dedup import normalize_title
from metatv.core.database import ChannelDB, Database, EpisodeDB, ProviderDB, SeasonDB


def _get_db() -> Database:
    from metatv.core.config import Config
    config, _ = Config.load()  # Config.load() returns (config, recovered_from_backup)
    return Database(config.database_url)


def inspect(title_fragment: str) -> None:
    db = _get_db()
    session = db.get_session()
    try:
        # Load providers for display names
        providers = {p.id: p.name for p in session.query(ProviderDB).all()}

        # Find all series channels matching the fragment
        fragment = title_fragment.lower()
        channels = (
            session.query(ChannelDB)
            .filter(
                ChannelDB.media_type == "series",
                ChannelDB.name.ilike(f"%{title_fragment}%"),
            )
            .order_by(ChannelDB.name)
            .all()
        )

        if not channels:
            print(f'No series found matching "{title_fragment}"')
            return

        print(f'\nSeries matching "{title_fragment}":')
        print("─" * 70)

        # Track per-normalized-title episode counts for cross-provider comparison
        norm_to_season_counts: dict[str, dict[int, int]] = {}

        channel_data = []
        for ch in channels:
            norm = normalize_title(ch.name, ch.detected_prefix)
            provider_name = providers.get(ch.provider_id, ch.provider_id)

            seasons = (
                session.query(SeasonDB)
                .filter(SeasonDB.series_id == ch.id)
                .order_by(SeasonDB.season_number)
                .all()
            )

            season_info = []
            has_dup_episode_ids = False
            for season in seasons:
                episodes = (
                    session.query(EpisodeDB)
                    .filter(EpisodeDB.season_id == season.id)
                    .order_by(EpisodeDB.episode_num)
                    .all()
                )
                ep_ids = [e.episode_id for e in episodes]
                dup_ids = [eid for eid, cnt in Counter(ep_ids).items() if cnt > 1]
                if dup_ids:
                    has_dup_episode_ids = True

                stream_sample = None
                if episodes:
                    stream_sample = episodes[0].stream_url

                season_info.append({
                    "num": season.season_number,
                    "ep_count": len(episodes),
                    "ep_ids": ep_ids,
                    "dup_ids": dup_ids,
                    "stream_sample": stream_sample,
                })

                # Accumulate for cross-provider comparison
                if norm not in norm_to_season_counts:
                    norm_to_season_counts[norm] = {}
                existing = norm_to_season_counts[norm].get(season.season_number, 0)
                norm_to_season_counts[norm][season.season_number] = max(existing, len(episodes))

            channel_data.append({
                "ch": ch,
                "norm": norm,
                "provider_name": provider_name,
                "seasons": season_info,
                "has_dup_episode_ids": has_dup_episode_ids,
            })

        # Second pass: display with cross-provider warnings
        for data in channel_data:
            ch = data["ch"]
            provider_name = data["provider_name"]
            norm = data["norm"]
            seasons = data["seasons"]

            prefix_tag = f"[{ch.detected_prefix}]" if ch.detected_prefix else "[?]"
            print(f"\n{prefix_tag} {ch.name}")
            print(f"  provider={provider_name}  source_id={ch.source_id}  channel_id={ch.id}")
            print(f"  normalized: \"{norm}\"")

            if not seasons:
                print("  (no seasons loaded)")
                continue

            for s in seasons:
                ep_count = s["ep_count"]
                max_count = norm_to_season_counts.get(norm, {}).get(s["num"], ep_count)
                missing = max_count - ep_count

                ids_preview = ", ".join(s["ep_ids"][:8])
                if len(s["ep_ids"]) > 8:
                    ids_preview += f", ... ({len(s['ep_ids'])} total)"

                flag = ""
                if s["dup_ids"]:
                    flag = f"  *** DUPLICATE episode IDs: {s['dup_ids']} — only first will play ***"
                elif missing > 0:
                    flag = f"  *** Only {ep_count}/{max_count} episodes — provider may have partial season ***"

                print(f"  Season {s['num']}: {ep_count} episodes  (IDs: {ids_preview})")
                if s["stream_sample"]:
                    # Truncate long URLs
                    url = s["stream_sample"]
                    if len(url) > 80:
                        url = url[:77] + "..."
                    print(f"    stream sample: {url}")
                if flag:
                    print(f"   {flag}")

    finally:
        session.close()


def dump_raw(title_fragment: str) -> None:
    """Re-fetch ``get_series_info`` LIVE and dump the raw season/episode key structure.

    Answers the question stored data cannot: does the provider actually *send*
    seasons we silently drop? The synthetic-season path keys on the ``episodes``
    dict and only creates a season for keys where ``str(k).isdigit()`` — so a
    provider that groups under non-numeric keys (e.g. ``"Temporada 5"``) would have
    those episodes discarded and never written to the DB, making them invisible to
    every stored-data check.

    Prints only structural keys/counts and each episode's own ``season`` fields
    (the hypothesis: a numeric season may survive on the episode even when the
    grouping key is non-numeric) — never stream URLs or credentials.

    Note: this performs a live provider API call per matched series using the
    stored provider credentials.
    """
    import asyncio

    from metatv.core.repositories import RepositoryFactory
    from metatv.providers.factory import get_provider

    db = _get_db()
    session = db.get_session()
    try:
        repos = RepositoryFactory(session)
        channels = (
            session.query(ChannelDB)
            .filter(
                ChannelDB.media_type == "series",
                ChannelDB.name.ilike(f"%{title_fragment}%"),
            )
            .order_by(ChannelDB.name)
            .all()
        )
        if not channels:
            print(f'No series found matching "{title_fragment}"')
            return

        for ch in channels:
            provider_db = repos.providers.get_by_id(ch.provider_id)
            print(f"\n[{ch.detected_prefix or '?'}] {ch.name}  source_id={ch.source_id}")
            if not provider_db:
                print(f"  (provider {ch.provider_id} not found)")
                continue
            provider = repos.providers.to_model(provider_db)
            plugin = get_provider(provider.type)
            if not plugin:
                print(f"  (no plugin for provider type {provider.type})")
                continue
            try:
                data = asyncio.run(plugin.fetch_series_info(provider, ch.source_id))
            except Exception as e:  # noqa: BLE001 - diagnostic tool, surface any error
                print(f"  fetch error: {e}")
                continue
            if not isinstance(data, dict):
                print(f"  unexpected response type: {type(data)}")
                continue

            seasons = data.get("seasons", [])
            episodes = data.get("episodes", {})

            # Raw seasons metadata — look for "Temporada"/non-numeric names.
            n = len(seasons) if isinstance(seasons, list) else "N/A"
            print(f"  raw seasons[] count={n}")
            if isinstance(seasons, list):
                for s in seasons:
                    if isinstance(s, dict):
                        print(f"    season_number={s.get('season_number')!r}  name={s.get('name')!r}")

            # Raw episodes grouping — the keys the synthetic-season path keys on.
            if isinstance(episodes, dict):
                keys = [str(k) for k in episodes.keys()]
                numeric = sorted(int(k) for k in keys if k.isdigit())
                nonnumeric = [k for k in keys if not k.isdigit()]
                print(f"  raw episodes{{}} keys (numeric, kept): {numeric}")
                if nonnumeric:
                    print(f"    *** NON-NUMERIC keys DROPPED by s.isdigit(): {nonnumeric} ***")
                # The hypothesis: does an episode keep a numeric season field even
                # when its grouping key is non-numeric?
                for k, eps in episodes.items():
                    if isinstance(eps, list) and eps and isinstance(eps[0], dict):
                        ep = eps[0]
                        info = ep.get("info") if isinstance(ep.get("info"), dict) else {}
                        print(f"    key={str(k)!r} -> {len(eps)} eps; sample season fields: "
                              f"season={ep.get('season')!r} season_num={ep.get('season_num')!r} "
                              f"info.season={info.get('season')!r}")
            elif isinstance(episodes, list):
                print(f"  raw episodes is a LIST (len={len(episodes)})")
                if episodes and isinstance(episodes[0], dict):
                    ep = episodes[0]
                    print(f"    sample season fields: season={ep.get('season')!r} "
                          f"season_num={ep.get('season_num')!r}")
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect series episode data across providers"
    )
    parser.add_argument("title", help="Title substring to search for")
    parser.add_argument(
        "--live", action="store_true",
        help="Re-fetch get_series_info live and dump the raw season/episode key "
             "structure (surfaces non-numeric/Temporada keys we'd drop). Makes a "
             "live provider API call per matched series.",
    )
    args = parser.parse_args()
    if args.live:
        dump_raw(args.title)
    else:
        inspect(args.title)


if __name__ == "__main__":
    main()
