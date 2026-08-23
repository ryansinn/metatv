#!/usr/bin/env python3
"""Re-fetch metadata for rows that lost fields to the pre-#438 cache clobber.

Why this exists
---------------
Until PR #438, ``MetadataManager._save_metadata_cache`` assigned every field
unconditionally. A cached row that aged past its TTL was refetched on the next
details-pane open, and if the provider chain returned less than it had the
first time — a transient failure, a rate limit, a title it no longer matched —
the thin result was written straight over the stored record. A title alone was
enough to pass the save gate, so poster, plot, cast and crew went to NULL.

#438 stopped that: writes now fill in, never blank out. But it cannot undo what
already happened, and the damaged rows are in the worst possible state for
self-healing — an empty ``poster_url`` with a FRESH ``fetched_at``, so the cache
considers them current and will not refetch them for another 30 days.

This script finds those rows and forces one refetch each. Safe by construction
now: with #438 in place a response that returns nothing can no longer make a row
worse, so re-running this is harmless.

Usage
-----
    venv/bin/python scripts/repair_lost_posters.py            # dry run
    venv/bin/python scripts/repair_lost_posters.py --apply    # do it
    venv/bin/python scripts/repair_lost_posters.py --apply --limit 10

Close the app first. Both processes can hold the SQLite file open, but a repair
run competing with a live UI for the single writer is a slow way to find that
out.

What the first real run found (owner's library, 2026-08-23)
-----------------------------------------------------------
70 damaged rows; **10 restored, 60 not**. The split is not random and is worth
knowing before running this anywhere else:

* The 10 that came back are the ones whose artwork was in the bulk catalog —
  ``raw_data.stream_icon`` — which ``ProviderMetadataProvider`` reads straight
  out of the database. Nothing was ever really lost for those.
* The 60 that did not had ``stream_icon: null``. Their posters came from the
  provider's PER-TITLE detail endpoint (``get_vod_info``), and nothing in the
  tree re-reads that for artwork: the enrichment sweep does call it, but
  ``raw_parse.harvest_detail_metadata`` keeps only genre/plot/cast/director and
  discards ``movie_image``/``cover_big``.

So this script recovers everything currently recoverable, and the remaining 60
need that harvest widened before a rerun can help them. That is a separate
change; this file is deliberately not the place to grow a second, divergent
copy of the detail-blob parser.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _parse_args():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--apply", action="store_true",
                   help="actually refetch; without it, only report what would be tried")
    p.add_argument("--limit", type=int, default=0,
                   help="stop after N titles (0 = no limit)")
    p.add_argument("--field", default="poster_url",
                   help="the emptied field to hunt for (default: poster_url)")
    return p.parse_args()


def _damaged(db, field: str) -> list[tuple[str, str, str]]:
    """``(channel_id, channel_name, metadata_title)`` for every row holding a
    title with *field* empty.

    A title with no poster is the clobber's signature: the save gate needs a
    title, so a row that has one and nothing else is a row a thin refetch wrote
    over. Rows that never had metadata at all have no ``metadata_id`` and are
    not touched — those are simply un-enriched, not damaged.
    """
    from sqlalchemy import or_

    from metatv.core.database import ChannelDB, MetadataDB

    out = []
    with db.session_scope(commit=False) as session:
        column = getattr(MetadataDB, field)
        rows = (
            session.query(ChannelDB.id, ChannelDB.name, MetadataDB.title)
            .join(MetadataDB, ChannelDB.metadata_id == MetadataDB.id)
            .filter(MetadataDB.title.isnot(None))
            .filter(or_(column.is_(None), column == ""))
            .all()
        )
        out = [(r[0], r[1], r[2]) for r in rows]
    return out


def main() -> int:
    args = _parse_args()

    from loguru import logger

    from metatv.core.config import Config
    from metatv.core.database import Database
    from metatv.core.metadata_manager import MetadataManager, MetadataProviderRegistry
    from metatv.metadata_providers.omdb import OMDbProvider
    from metatv.metadata_providers.provider_metadata import ProviderMetadataProvider
    from metatv.metadata_providers.tmdb import TMDbProvider

    logger.remove()
    logger.add(sys.stderr, level="WARNING")

    config, _recovered = Config.load()
    db = Database(config.database_url)

    damaged = _damaged(db, args.field)
    if args.limit:
        damaged = damaged[: args.limit]

    print(f"{len(damaged)} title(s) hold a title with no {args.field}.")
    if not damaged:
        return 0
    for _cid, name, title in damaged[:10]:
        print(f"  · {title or name}")
    if len(damaged) > 10:
        print(f"  … and {len(damaged) - 10} more")

    if not args.apply:
        print("\nDry run. Re-run with --apply to refetch these.")
        return 0

    # The SAME chain MainWindow builds, in the same order — the provider plugin
    # first (free, reads raw_data already in the DB), then the external APIs,
    # each a no-op until its key is set. Assembling a different chain here would
    # repair rows differently from how the app would have filled them.
    registry = MetadataProviderRegistry(config)
    registry.register(ProviderMetadataProvider(db))
    registry.register(TMDbProvider(config, db))
    registry.register(OMDbProvider(config, db))
    manager = MetadataManager(registry, db)

    restored = 0
    still_missing = []

    async def _run():
        nonlocal restored
        for index, (cid, name, title) in enumerate(damaged, 1):
            label = title or name
            try:
                result = await manager.get_metadata(cid, force_refresh=True)
            except Exception as exc:  # noqa: BLE001 — one bad title must not stop the pass
                print(f"  [{index}/{len(damaged)}] {label}: ERROR {exc}")
                still_missing.append(label)
                continue
            value = getattr(result, args.field, None) if result else None
            if value:
                restored += 1
                print(f"  [{index}/{len(damaged)}] {label}: restored")
            else:
                still_missing.append(label)
                print(f"  [{index}/{len(damaged)}] {label}: still missing")

    asyncio.run(_run())

    print(f"\nRestored {restored} of {len(damaged)}.")
    if still_missing:
        print(f"{len(still_missing)} still missing — the providers genuinely have "
              f"nothing for these, which #438 now records without erasing anything:")
        for label in still_missing[:15]:
            print(f"  · {label}")
        if len(still_missing) > 15:
            print(f"  … and {len(still_missing) - 15} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
