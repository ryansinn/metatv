"""Populate special content categorization for channels

This script analyzes channels and categorizes them into special views:
- PPV (Pay-Per-View events with dates)
- Live Events ([EVENT] or [LIVE-EVENT] tags)
- Sports (sports-related channels)

Usage:
    # Dry-run to see what would be updated
    python -m metatv.scripts.populate_special_content --dry-run
    
    # Update all channels
    python -m metatv.scripts.populate_special_content
    
    # Update only channels from specific provider
    python -m metatv.scripts.populate_special_content --provider "provider_id"
    
    # Force re-categorization of already categorized channels
    python -m metatv.scripts.populate_special_content --force
    
    # Show detailed progress
    python -m metatv.scripts.populate_special_content --verbose

Future expansions:
    - Auto-run on provider refresh
    - Incremental updates (only new/changed channels)
    - Parse sport leagues and teams
    - Parse event dates for live events
    - Clean up expired PPV events
"""

import argparse
from loguru import logger

from metatv.core.config import Config
from metatv.core.database import Database, ChannelDB
from metatv.core.special_content import update_channel_special_content


def populate_special_content(
    config: Config,
    provider_id: str = None,
    force: bool = False,
    dry_run: bool = False,
    verbose: bool = False,
    sports_only: bool = False,
) -> None:
    """Populate special content categorization for channels.

    Args:
        config: Application configuration.
        provider_id: Only process channels from this provider (None = all).
        force: Re-categorize already categorized channels.
        dry_run: Show what would be updated without making changes.
        verbose: Show detailed progress per channel.
        sports_only: Only (re-)parse sport_type/league_name/team_name for
                     channels already flagged as sports.  Fast targeted backfill
                     after keyword map changes without touching all 284k channels.
    """

    db = Database(config.database_url)
    session = db.get_session()

    try:
        query = session.query(ChannelDB)

        if sports_only:
            # Targeted mode: only sports channels missing sport_type
            query = query.filter(ChannelDB.special_view == 'sports')
            if not force:
                query = query.filter(ChannelDB.sport_type.is_(None))
            logger.info(
                "Sports-only mode: re-parsing sport_type/league_name/team_name "
                "for sports channels" + (" (all)" if force else " (missing sport_type)")
            )
        else:
            if provider_id:
                query = query.filter(ChannelDB.provider_id == provider_id)
                logger.info(f"Processing channels from provider: {provider_id}")
            else:
                logger.info("Processing all channels")

            if not force:
                query = query.filter(ChannelDB.special_view.is_(None))
                logger.info("Skipping already categorized channels (use --force to re-categorize)")
            else:
                logger.info("Force mode: Re-categorizing all channels")
        
        channels = query.all()
        total = len(channels)
        
        logger.info(f"Found {total:,} channels to process")
        
        if total == 0:
            logger.info("No channels to process")
            return
        
        # Track statistics
        stats = {
            'ppv': 0,
            'live_event': 0,
            'sports': 0,
            'uncategorized': 0,
        }
        
        updated = 0
        
        for i, channel in enumerate(channels, 1):
            if i % 1000 == 0 or verbose:
                logger.info(f"Progress: {i:,}/{total:,} ({i*100//total}%)")

            if sports_only:
                # Only re-parse sport/league/team fields; don't change special_view
                from metatv.core.special_content import parse_sports_channel
                sports_data = parse_sports_channel(channel, config)
                channel.sport_type = sports_data['sport_type']
                channel.league_name = sports_data['league_name']
                channel.team_name = sports_data['team_name']
                updated += 1
                stats['sports'] = stats.get('sports', 0) + 1
                if verbose:
                    logger.debug(
                        f"  [sports] {channel.name} → "
                        f"{sports_data['sport_type']} / "
                        f"{sports_data['league_name']} / "
                        f"{sports_data['team_name']}"
                    )
            else:
                was_updated = update_channel_special_content(channel, config)
                if was_updated:
                    updated += 1
                    category = channel.special_view
                    if category:
                        stats[category] = stats.get(category, 0) + 1
                        if verbose:
                            logger.debug(f"  [{category}] {channel.name}")
                    else:
                        stats['uncategorized'] += 1
        
        logger.info(f"\n{'='*60}")
        if sports_only:
            logger.info("SPORTS PARSING SUMMARY")
            logger.info(f"{'='*60}")
            logger.info(f"Sports channels processed: {total:,}")
            logger.info(f"Updated: {updated:,}")
            # Show sport_type breakdown
            from sqlalchemy import func as sqlfunc
            sport_rows = session.query(
                ChannelDB.sport_type, sqlfunc.count(ChannelDB.id)
            ).filter(ChannelDB.special_view == 'sports').group_by(
                ChannelDB.sport_type
            ).all()
            logger.info("\nSport type breakdown:")
            for sport, count in sorted(sport_rows, key=lambda r: -(r[1])):
                label = sport if sport else 'unknown'
                logger.info(f"  {label:<25} {count:>6,}")
        else:
            logger.info("CATEGORIZATION SUMMARY")
            logger.info(f"{'='*60}")
            logger.info(f"Total processed: {total:,}")
            logger.info(f"Updated: {updated:,}")
            logger.info(f"")
            logger.info(f"Categories:")
            logger.info(f"  💰 PPV:         {stats.get('ppv', 0):>6,} channels")
            logger.info(f"  🎪 Live Events: {stats.get('live_event', 0):>6,} channels")
            logger.info(f"  ⚽ Sports:       {stats.get('sports', 0):>6,} channels")
            logger.info(f"  ❓ Other:        {stats.get('uncategorized', 0):>6,} channels")
        logger.info(f"{'='*60}")
        
        if dry_run:
            logger.info("DRY RUN: No changes committed to database")
            session.rollback()
        else:
            session.commit()
            logger.success(f"✅ Committed {updated:,} channel updates to database")
        
    except Exception as e:
        logger.error(f"❌ Error during categorization: {e}")
        import traceback
        traceback.print_exc()
        session.rollback()
        raise
    finally:
        session.close()


def main():
    """Command-line entry point"""
    parser = argparse.ArgumentParser(
        description="Populate special content categorization for channels",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry-run to preview changes
  python -m metatv.scripts.populate_special_content --dry-run
  
  # Update all channels
  python -m metatv.scripts.populate_special_content
  
  # Update specific provider
  python -m metatv.scripts.populate_special_content --provider "provider_id"
  
  # Force re-categorize all channels
  python -m metatv.scripts.populate_special_content --force
  
  # Show detailed per-channel progress
  python -m metatv.scripts.populate_special_content --verbose
        """
    )
    
    parser.add_argument(
        '--provider',
        type=str,
        help='Only process channels from this provider ID'
    )
    
    parser.add_argument(
        '--force',
        action='store_true',
        help='Re-categorize already categorized channels'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be updated without making changes'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed progress per channel'
    )

    parser.add_argument(
        '--sports-only',
        action='store_true',
        help=(
            'Only re-parse sport_type/league_name/team_name for channels already '
            'flagged as sports. Fast targeted backfill after keyword map changes.'
        )
    )

    args = parser.parse_args()
    
    # Configure logging
    if args.verbose:
        logger.remove()
        logger.add(lambda msg: print(msg, end=''), level="DEBUG")
    
    # Load configuration
    config = Config.load()
    logger.info(f"Loaded config. Database: {config.database_url}")
    
    populate_special_content(
        config=config,
        provider_id=args.provider,
        force=args.force,
        dry_run=args.dry_run,
        verbose=args.verbose,
        sports_only=args.sports_only,
    )


if __name__ == "__main__":
    main()
