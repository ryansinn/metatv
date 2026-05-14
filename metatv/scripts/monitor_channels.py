"""Monitor specific channels by source ID to track provider refresh behavior.

Useful for understanding how a provider handles channel updates over time:
- Do expired event channels get updated in place (same source_id, new name)?
- Do they disappear and reappear with new source_ids?
- Do channels accumulate, or are old ones pruned?

Usage:
    # Check a specific set of source IDs
    python -m metatv.scripts.monitor_channels 1961251 1961250 1961249 1961248

    # Check from a saved watchlist file
    python -m metatv.scripts.monitor_channels --file watchlist.txt

    # Save current snapshot of source IDs to a file for later diffing
    python -m metatv.scripts.monitor_channels 1961251 1961250 --save watchlist.txt

    # Show full channel details instead of one-line summary
    python -m metatv.scripts.monitor_channels 1961251 --verbose

    # Find all channels matching a name fragment and print their source IDs
    python -m metatv.scripts.monitor_channels --search "flohockey"
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from loguru import logger

from metatv.core.config import Config
from metatv.core.database import Database, ChannelDB


def lookup_channels(
    session,
    source_ids: List[str],
    verbose: bool = False,
) -> None:
    """Look up channels by source_id and report their current state."""
    found = 0
    gone = 0

    for sid in source_ids:
        ch = session.query(ChannelDB).filter_by(source_id=sid).first()
        if ch:
            found += 1
            if verbose:
                print(f"\n{'─'*60}")
                print(f"  source_id   : {ch.source_id}")
                print(f"  id          : {ch.id}")
                print(f"  name        : {ch.name}")
                print(f"  provider_id : {ch.provider_id}")
                print(f"  stream_url  : {ch.stream_url or '(none)'}")
                print(f"  special_view: {ch.special_view or '(none)'}")
                print(f"  sport_type  : {ch.sport_type or '(none)'}")
                print(f"  league_name : {ch.league_name or '(none)'}")
                print(f"  category    : {ch.category or '(none)'}")
                print(f"  is_hidden   : {ch.is_hidden}")
            else:
                stream = "has_stream" if ch.stream_url else "NO_STREAM"
                print(f"  FOUND  {sid:<12}  [{stream}]  {ch.name[:70]}")
        else:
            gone += 1
            print(f"  GONE   {sid:<12}  (no channel with this source_id)")

    print()
    print(f"Results: {found} found, {gone} gone (of {len(source_ids)} checked)")


def search_channels(session, query: str, limit: int = 30) -> None:
    """Find channels matching a name fragment and print their source IDs."""
    rows = (
        session.query(ChannelDB)
        .filter(ChannelDB.name.ilike(f"%{query}%"))
        .order_by(ChannelDB.name)
        .limit(limit)
        .all()
    )

    if not rows:
        print(f"No channels found matching '{query}'")
        return

    print(f"Channels matching '{query}' ({len(rows)} shown, max {limit}):\n")
    for ch in rows:
        stream = "has_stream" if ch.stream_url else "NO_STREAM"
        print(f"  source_id={ch.source_id:<12}  [{stream}]  {ch.name[:70]}")

    print(f"\nTo monitor these, copy the source_ids above and run:")
    ids = " ".join(ch.source_id for ch in rows)
    print(f"  python -m metatv.scripts.monitor_channels {ids}")
    print(f"\nOr save them:")
    print(f"  python -m metatv.scripts.monitor_channels {ids} --save watchlist.txt")


def save_watchlist(path: str, source_ids: List[str], session) -> None:
    """Save source IDs and current channel names to a watchlist file."""
    out = Path(path)
    lines = [f"# MetaTV channel watchlist — saved {datetime.now().isoformat(timespec='seconds')}"]
    for sid in source_ids:
        ch = session.query(ChannelDB).filter_by(source_id=sid).first()
        name = ch.name if ch else "(not found)"
        lines.append(f"{sid}  # {name}")

    out.write_text("\n".join(lines) + "\n")
    print(f"Saved {len(source_ids)} source IDs to {out.resolve()}")


def load_watchlist(path: str) -> List[str]:
    """Load source IDs from a watchlist file, ignoring blank lines and comments."""
    p = Path(path)
    if not p.exists():
        logger.error(f"Watchlist file not found: {path}")
        sys.exit(1)

    ids = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Support "source_id  # optional comment" format
        sid = line.split("#")[0].strip()
        if sid:
            ids.append(sid)
    return ids


def main():
    parser = argparse.ArgumentParser(
        description="Monitor specific IPTV channels by source ID across provider refreshes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Check four specific channels
  python -m metatv.scripts.monitor_channels 1961251 1961250 1961249 1961248

  # Find channels to watch, then save a watchlist
  python -m metatv.scripts.monitor_channels --search "flohockey"
  python -m metatv.scripts.monitor_channels 1961251 1961250 --save watchlist.txt

  # After a provider refresh, check the watchlist
  python -m metatv.scripts.monitor_channels --file watchlist.txt

  # Full details for a channel
  python -m metatv.scripts.monitor_channels 1961251 --verbose
        """,
    )

    parser.add_argument(
        "source_ids",
        nargs="*",
        help="Source IDs to look up (provider-assigned numeric IDs)",
    )
    parser.add_argument(
        "--file", "-f",
        metavar="PATH",
        help="Load source IDs from a watchlist file instead of CLI args",
    )
    parser.add_argument(
        "--save", "-s",
        metavar="PATH",
        help="Save the given source IDs (with current names) to a watchlist file",
    )
    parser.add_argument(
        "--search",
        metavar="QUERY",
        help="Find channels matching this name fragment and print their source IDs",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=30,
        help="Max results for --search (default: 30)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show full channel details instead of one-line summary",
    )

    args = parser.parse_args()

    config = Config.load()
    db = Database(config.database_url)
    session = db.get_session()

    try:
        print(f"Database: {config.database_url}")
        print(f"Checked : {datetime.now().isoformat(timespec='seconds')}")
        print()

        if args.search:
            search_channels(session, args.search, limit=args.limit)
            return

        # Collect source IDs
        source_ids: List[str] = []
        if args.file:
            source_ids = load_watchlist(args.file)
            print(f"Loaded {len(source_ids)} source IDs from {args.file}\n")
        if args.source_ids:
            source_ids.extend(args.source_ids)

        if not source_ids:
            parser.print_help()
            sys.exit(1)

        if args.save:
            save_watchlist(args.save, source_ids, session)
            print()

        lookup_channels(session, source_ids, verbose=args.verbose)

    finally:
        session.close()


if __name__ == "__main__":
    main()
