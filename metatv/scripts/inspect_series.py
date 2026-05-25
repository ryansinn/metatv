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
    config = Config.load()
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect series episode data across providers"
    )
    parser.add_argument("title", help="Title substring to search for")
    args = parser.parse_args()
    inspect(args.title)


if __name__ == "__main__":
    main()
